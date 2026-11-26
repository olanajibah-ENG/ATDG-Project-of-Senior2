"""
views/folder_upload.py
======================
FolderUploadView — رفع مجلدات وملفات متعددة مع دعم versioning
"""

import io
import os
import uuid
import hashlib
import zipfile
import logging
import re
import json
from datetime import datetime

from bson import ObjectId
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from rest_framework.authentication import SessionAuthentication, BasicAuthentication

from core_ai.mongo_utils import get_mongo_db, save_to_gridfs
from core_ai.models.codefile import CodeFile
from core_ai.celery_tasks.analyze_task import analyze_code_file_task
from core_ai.services import project_versioning

logger = logging.getLogger(__name__)

# ====================== LANGUAGE DETECTION ======================
def detect_language_robust(content: str, filename: str = "") -> str:
    """كشف لغة البرمجة بدقة عالية"""
    if not content or len(content.strip()) < 5:
        return "text"

    ext = os.path.splitext(filename.lower())[-1]

    # أولوية قصوى للامتداد
    ext_map = {
        '.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.tsx': 'typescript',
        '.java': 'java', '.cs': 'c_sharp', '.cpp': 'cpp', '.c': 'c', '.go': 'go',
        '.rb': 'ruby', '.php': 'php', '.kt': 'kotlin', '.rs': 'rust'
    }

    if ext in ext_map:
        return ext_map[ext]

    # Heuristics
    lower = content.lower()
    if re.search(r'using\s+System|namespace\s+\w+|public class|class \w+ :', lower):
        return 'c_sharp'
    if re.search(r'#include|std::|template<|cout|cin|vector<', lower):
        return 'cpp'
    if re.search(r'def \w+\s*\(|import |from .* import|async def|class \w+:|if __name__ ==', lower):
        return 'python'
    if re.search(r'function |const |let |=>|export |async function|console\.', lower):
        return 'javascript'
    if '<?php' in lower or re.search(r'function \w+\s*\(', lower) and '$' in lower[:600]:
        return 'php'
    if re.search(r'fn |let |mut |impl |struct |trait |pub |mod ', lower):
        return 'rust'

    return 'text'


# امتدادات مدعومة
def is_support_file(path):
    from pathlib import PurePosixPath

    path = PurePosixPath(str(path).replace(chr(92), "/").lower())
    return (path.name in {"pyproject.toml", "setup.cfg", "pytest.ini", "conftest.py"}
            or path.suffix == ".txt" and (path.name.startswith("requirements") or "requirements" in path.parts[:-1]))


SUPPORTED_EXTENSIONS = {'.py', '.js', '.ts', '.tsx', '.java', '.cs', '.cpp', '.c', 
                       '.go', '.rb', '.php', '.kt', '.rs'}

IGNORED_PREFIXES = ('__MACOSX', '.', '__pycache__', '.git')
IGNORED_EXTENSIONS = ('.pyc', '.class', '.exe', '.dll', '.so', '.o', '.git', '.md', '.txt')
PROJECT_VERSIONS_COLLECTION = 'project_versions'


@method_decorator(csrf_exempt, name='dispatch')
class FolderUploadView(APIView):
    authentication_classes = [SessionAuthentication, BasicAuthentication]
    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        logger.info("[FOLDER-UPLOAD] Request received")

        project_name = request.data.get('project_name', '').strip()
        if not project_name:
            return Response({"error": "project_name is required"}, status=status.HTTP_400_BAD_REQUEST)

        upm_project_id = request.data.get('upm_project_id', '').strip() or project_name

        try:
            deleted_paths = self._read_list(request, 'deleted_paths')
            files_data, has_zip = self._extract_files(request, project_name, allow_empty=bool(deleted_paths))
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"[FOLDER-UPLOAD] Extraction error: {e}")
            return Response({"error": "Failed to process uploaded files"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # full    = the upload IS the project: a file that is not in it is deleted   (ZIP)
        # partial = only the uploaded files change; deletions come in deleted_paths (loose files, GitHub)
        upload_mode = project_versioning.infer_mode(request.data.get('upload_mode'), has_zip)

        if not files_data and not deleted_paths:
            return Response({
                "error": "No supported files found",
                "supported_extensions": list(SUPPORTED_EXTENSIONS)
            }, status=status.HTTP_400_BAD_REQUEST)

        db = get_mongo_db()
        if db is None:
            return Response({"error": "Database connection failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        version_number, prev_entries = self._get_next_version(db, upm_project_id)
        logger.info(f"[FOLDER-UPLOAD] project_id={upm_project_id}, version={version_number}, "
                    f"prev_files={len(prev_entries)}, mode={upload_mode}, deleted_paths={len(deleted_paths)}")

        # Loose files sent by name only (the UI keeps no folders) go back to the path they had.
        matched_paths = {}
        bare = getattr(self, '_bare_names', {})
        if not has_zip and bare:
            matched_paths, ambiguous = project_versioning.match_bare_names(prev_entries, bare)
            if ambiguous:
                names = ", ".join(f"{n} ({' / '.join(ps)})" for n, ps in sorted(ambiguous.items()))
                return Response({
                    "error": (f"These file names match more than one file of the previous version: {names}. "
                              f"Nothing was saved. Send each file's path in 'paths', or upload a zip."),
                    "code": "ambiguous_name",
                    "ambiguous": ambiguous,
                }, status=status.HTTP_409_CONFLICT)
            files_data = [(matched_paths.get(path, path), content) for path, content in files_data]
            matched_paths = {bare[g]: real for g, real in matched_paths.items()}

        # A full upload that would delete half the project or more is refused unless confirmed:
        # it is usually the wrong zip, or a zip with a different top folder. Nothing is saved.
        if upload_mode == project_versioning.FULL and not self._is_true(request.data.get('confirm_deletions')):
            risk = project_versioning.check_deletions(prev_entries, [path for path, _ in files_data])
            if risk:
                return Response(self._mass_deletion_body(risk), status=status.HTTP_409_CONFLICT)

        try:
            file_ids_list, skipped = self._save_files(
                db, files_data, upm_project_id, project_name, version_number, request
            )
        except Exception as e:
            logger.error(f"[FOLDER-UPLOAD] Save error: {e}")
            return Response({"error": f"Failed to save files: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        built = self._save_project_version(
            db, upm_project_id, project_name, version_number,
            file_ids_list, prev_entries, upload_mode, deleted_paths, request
        )

        logger.info(f"[FOLDER-UPLOAD] Completed — version={version_number}, saved={len(file_ids_list)}, skipped={skipped}")

        return Response({
            "project_id":     upm_project_id,
            "project_name":   project_name,
            "version_number": version_number,
            "file_count":     len(file_ids_list),
            "file_ids":       [f["file_id"] for f in file_ids_list],
            "files":          file_ids_list,
            "skipped":        skipped,
            "upload_mode":    upload_mode,
            "version_files":  built["counts"]["total_files"],
            "changes":        built["counts"],
            "deleted":        [c["filepath"] for c in built["file_changes"] if c["status"] == project_versioning.DELETED],
            "matched_paths":  matched_paths,
        }, status=status.HTTP_201_CREATED)

    @staticmethod
    def _is_true(value):
        return str(value or '').strip().lower() in ('1', 'true', 'yes', 'on')

    @staticmethod
    def _mass_deletion_body(risk):
        message = (f"This upload would delete {risk['deleted_count']} of the {risk['previous_count']} files "
                   f"of the previous version. Nothing was saved. If that is what you want, upload again "
                   f"with confirm_deletions=true.")
        hint = risk.get("top_folder")
        if hint:
            if hint["zip_has_it"]:
                message += (f" The zip seems to have an extra top folder '{hint['top_folder']}' "
                            f"that the previous version did not have.")
            else:
                message += (f" The zip seems to be missing the top folder '{hint['top_folder']}' "
                            f"that the previous version had: zip the folder itself, not its contents.")
        return {"error": message, "code": "mass_deletion", **risk}

    @staticmethod
    def _read_list(request, key):
        """A list sent as repeated form fields, or as one JSON string."""
        values = request.data.getlist(key) if hasattr(request.data, 'getlist') else request.data.get(key) or []
        if isinstance(values, str):
            values = [values]
        out = []
        for value in values:
            if isinstance(value, str) and value.strip().startswith('['):
                try:
                    out.extend(json.loads(value))
                    continue
                except ValueError:
                    raise ValueError(f"{key} is not valid JSON")
            if value:
                out.append(value)
        return [str(v).replace('\\', '/') for v in out]

    # ── Versioning ─────────────────────────────────────────────────────────────
    def _get_next_version(self, db, upm_project_id):
        """
        يرجع (version_number, prev_entries).
        prev_entries = ملفات آخر إصدار سابق، ملف واحد لكل مسار، بمساره بهداك الإصدار.
        """
        collection   = db[PROJECT_VERSIONS_COLLECTION]
        last_version = collection.find_one(
            {"project_id": upm_project_id},
            sort=[("version_number", -1)]
        )
        if not last_version:
            logger.info("[FOLDER-UPLOAD] New project → version 1")
            return 1, []

        v = last_version["version_number"] + 1
        entries = project_versioning.visible_files(last_version)
        if entries is None:   # older document without file_changes
            ids = []
            for fid in last_version.get("file_ids", []):
                try:
                    ids.append(ObjectId(str(fid)))
                except Exception:
                    pass
            docs = db[settings.CODE_FILES_COLLECTION].find(
                {"_id": {"$in": ids}},
                {"_id": 1, "filename": 1, "filepath": 1, "file_type": 1, "version_number": 1},
            )
            entries = project_versioning.dedupe_by_path([{
                "file_id": str(d["_id"]), "filename": d.get("filename", ""),
                "filepath": d.get("filepath") or d.get("filename", ""),
                "file_type": d.get("file_type", "unknown"), "version_number": d.get("version_number", 1),
            } for d in docs])
        logger.info(f"[FOLDER-UPLOAD] Existing project → version {v}")
        return v, entries

    def _save_project_version(self, db, project_id, project_name, version_number,
                              new_files_list, prev_entries, upload_mode, deleted_paths, request):
        """
        يبني الإصدار الجديد من السابق كجدول مسار ← ملف (core_ai/services/project_versioning.py):
          - الملف المرفوع بياخد مكان يلي بنفس المسار، أو بينضاف
          - full    : يلي ما انرفع بينحذف
          - partial : يلي ما انرفع بينقل متل ما هو، إلا يلي بـ deleted_paths
          - الحالة (new / modified / unchanged / deleted) بالمقارنة مع الإصدار السابق بنفس المسار
        """
        user_email = request.user.email if request.user.is_authenticated else request.data.get('user_email')
        built = project_versioning.build_version(prev_entries, new_files_list, upload_mode, deleted_paths)
        counts = built["counts"]

        db[PROJECT_VERSIONS_COLLECTION].insert_one({
            "project_id":      project_id,
            "project_name":    project_name,
            "version_number":  version_number,
            "upload_mode":     upload_mode,
            "file_ids":        built["file_ids"],        # ملفات الإصدار (بدون المحذوفة)، ملف لكل مسار
            "file_changes":    built["file_changes"],    # نفسها مع الحالة، والمحذوفة بالآخر
            "total_files":     counts["total_files"],
            "new_files":       counts["new_files"],
            "modified_files":  counts["modified_files"],
            "unchanged_files": counts["unchanged_files"],
            "deleted_files":   counts["deleted_files"],
            "user_email":      user_email,
            "created_at":      datetime.utcnow(),
        })
        logger.info(f"[FOLDER-UPLOAD] Version {version_number} saved ({upload_mode}): {counts}")
        return built

    # ── File Extraction ────────────────────────────────────────────────────────
    def _extract_files(self, request, project_name, allow_empty=False):
        """→ (files, has_zip). files = [(filepath, content)]
        Files that came with their name only are listed in self._bare_names {guessed path: name}."""
        self._bare_names = {}
        all_files = (
            list(request.FILES.getlist('file')) +
            list(request.FILES.getlist('files')) +
            list(request.FILES.getlist('folder'))
        )
        if not all_files:
            if allow_empty:
                return [], False          # a partial upload that only deletes
            raise ValueError("No files received. Send 'files' (multiple) or 'file' (single/ZIP).")

        if len(all_files) == 1 and all_files[0].name.lower().endswith('.zip'):
            return self._extract_from_zip(all_files[0]), True

        archives = [f for f in all_files if f.name.lower().endswith('.zip')]
        if archives:
            result = []
            for f in archives:
                result.extend(self._extract_from_zip(f))
            if result:
                return result, True

        # Django keeps only the base name of an uploaded file. A caller that knows the real paths
        # (GitHub sync) sends them in `paths`, in the same order as `files`.
        paths = self._read_list(request, 'paths')
        loose = list(request.FILES.getlist('files'))
        if paths and len(paths) != len(loose):
            raise ValueError("paths must have one entry per file in 'files'")
        path_of = {id(f): p for f, p in zip(loose, paths)} if paths else {}
        return self._extract_from_files(all_files, project_name, path_of), False

    def _extract_from_zip(self, uploaded_file):
        """استخراج من ZIP مع قراءة مرة واحدة"""
        result = []
        try:
            raw_data = uploaded_file.read()   # قراءة مرة واحدة
            with zipfile.ZipFile(io.BytesIO(raw_data)) as zf:
                for entry in zf.namelist():
                    if entry.endswith('/') or any(entry.startswith(p) for p in IGNORED_PREFIXES):
                        continue
                    ext = os.path.splitext(entry)[1].lower()
                    if ext not in SUPPORTED_EXTENSIONS and not is_support_file(entry):
                        continue
                    try:
                        content = zf.read(entry).decode('utf-8', errors='ignore')
                        result.append((entry, content))
                    except Exception as e:
                        logger.warning(f"[FOLDER-UPLOAD] Skipping {entry}: {e}")
        except zipfile.BadZipFile:
            raise ValueError("Invalid ZIP file.")
        except Exception as e:
            logger.error(f"[FOLDER-UPLOAD] ZIP extraction error: {e}")
            raise ValueError("Failed to extract ZIP file")

        logger.info(f"[FOLDER-UPLOAD] Extracted {len(result)} files from ZIP")
        return result

    def _extract_from_files(self, files, project_name, path_of=None):
        result = []
        for f in files:
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS and not is_support_file((path_of or {}).get(id(f)) or f.name):
                continue

            try:
                content = f.read().decode('utf-8', errors='ignore')
                given = (path_of or {}).get(id(f))
                if given:
                    filepath = given.replace('\\', '/').lstrip('/')
                else:
                    filepath = f.name if os.path.dirname(f.name) else f"{project_name}/{f.name}"
                    if not os.path.dirname(f.name):
                        self._bare_names[filepath] = f.name
                result.append((filepath, content))
            except Exception as e:
                logger.warning(f"[FOLDER-UPLOAD] Skipping {f.name}: {e}")
        return result

    # ── Save Files ─────────────────────────────────────────────────────────────
    def _save_files(self, db, files_data, project_id, project_name, version_number, request):
        collection          = db[settings.CODE_FILES_COLLECTION]
        analysis_collection = db[settings.ANALYSIS_RESULTS_COLLECTION]
        files_list          = []
        skipped             = 0
        user_email = request.user.email if request.user.is_authenticated else request.data.get('user_email')
        user_name  = request.user.username if request.user.is_authenticated else None

        for filepath, file_content in files_data:
            try:
                file_info = self._save_single_file(
                    collection, analysis_collection,
                    filepath, file_content, project_id, project_name,
                    version_number, user_email, user_name
                )
                files_list.append(file_info)
            except Exception as e:
                logger.error(f"[FOLDER-UPLOAD] Failed to save {filepath}: {e}")
                skipped += 1

        return files_list, skipped

    def _save_single_file(self, collection, analysis_collection, filepath, content,
                          project_id, project_name, version_number, user_email, user_name):
        """
        Content Addressing:
        - لو الملف موجود بنفس hash ونفس المشروع → يرجع نفس الـ id (unchanged)
          مع version_number القديم (ما يتحدث) — هيك نعرف إنه unchanged
        - لو hash جديد → يُحفظ كـ document جديد بـ version_number الحالي
        """
        file_hash = hashlib.md5(content.encode()).hexdigest()

        # same path + same content → the same file. Two paths with equal content (an empty
        # __init__.py in two packages) stay two files, and a moved file gets its new path.
        existing = collection.find_one(
            {'file_hash': file_hash, 'source_project_id': project_id, 'filepath': filepath},
            sort=[('version_number', -1)],
        )
        if existing and (not is_support_file(filepath) or existing.get("file_type") == "support"):
            logger.info(f"[FOLDER-UPLOAD] Reusing (unchanged): {filepath}")
            return {
                "file_id":        str(existing['_id']),
                "filename":       os.path.basename(filepath),
                "filepath":       filepath,
                "file_type":      existing.get('file_type', 'unknown'),
                "version_number": existing.get('version_number', 1),  # الإصدار القديم الأصلي
            }

        # === الكشف عن اللغة ===
        file_type = "support" if is_support_file(filepath) else detect_language_robust(content, filepath)
        basename = os.path.basename(filepath)

        gridfs_id = save_to_gridfs(
            content=content,
            filename=basename,
            metadata={
                'project_id': project_id, 'filepath': filepath,
                'file_type':  file_type,  'file_hash': file_hash,
                'version':    version_number,
            }
        )

        code_file = CodeFile(
            filename=basename, file_type=file_type, file_hash=file_hash,
            gridfs_id=gridfs_id, file_size=len(content.encode('utf-8')),
            source_project_id=project_id, project_name=project_name,
            version_number=version_number, user_email=user_email,
            user_name=user_name, analysis_status="NOT_ANALYSED" if file_type == "support" else "PENDING",
        )

        data_to_insert = code_file.model_dump(by_alias=True, exclude_unset=True)
        data_to_insert['filepath'] = filepath
        if '_id' in data_to_insert and data_to_insert['_id'] is None:
            del data_to_insert['_id']

        result  = collection.insert_one(data_to_insert)
        file_id = str(result.inserted_id)
        logger.info(f"[FOLDER-UPLOAD] Saved new: {filepath} → {file_type} v{version_number}")

        if file_type != "support":
            analyze_code_file_task.delay(file_id)

        return {
            "file_id":        file_id,
            "filename":       basename,
            "filepath":       filepath,
            "file_type":      file_type,
            "version_number": version_number,  # الإصدار الحالي
        }
