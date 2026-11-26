"""
folder_upload_proxy.py  ← معدّل بالكامل لـ Message Broker
======================
الفرق عن النسخة القديمة:
    قبل: UPM يبعث HTTP لـ AI وينتظر حتى يخلص (300 ثانية timeout)
    بعد: UPM يقرأ الملفات → يحطها في Redis كرسالة → يرجع task_id فوراً
         AI Celery worker يشيل الرسالة ويشتغل في الخلفية

شو اتحذف؟
    - كل كود requests.post() للـ AI
    - _save_to_mysql() من هون — انتقل لـ InternalUploadCompleteView
    - timeout المشاكل

شو أُضيف؟
    - قراءة محتوى الملفات وتحويلها لـ list قابل للتخزين في Redis
    - استدعاء process_upload_task.delay() بدل HTTP
    - رجوع task_id فوراً للفرونت
"""

import json
import os
import logging
from django.shortcuts import get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser

from core_upm.permissions import IsDeveloperRole
from core_upm.models.project import Project
from core_upm.celery_tasks.upload_tasks import process_upload_task

logger = logging.getLogger(__name__)

def is_support_file(path):
    from pathlib import PurePosixPath

    path = PurePosixPath(str(path).replace(chr(92), "/").lower())
    return (path.name in {"pyproject.toml", "setup.cfg", "pytest.ini", "conftest.py"}
            or path.suffix == ".txt" and (path.name.startswith("requirements") or "requirements" in path.parts[:-1]))


SUPPORTED_EXTENSIONS = (
    '.py', '.java', '.js', '.ts', '.cs',
    '.cpp', '.c', '.h', '.hpp', '.rb', '.go', '.kt',
    '.jsx', '.tsx', '.php', '.swift', '.scala', '.rs',
    '.zip',
)


@method_decorator(csrf_exempt, name='dispatch')
class FolderUploadProxyView(APIView):
    """
    POST /api/upm/projects/<project_id>/folder-upload/

    قبل: كان ينتظر AI يخلص → timeout خطر
    بعد: يرجع task_id فوراً → AI يشتغل في الخلفية

    Body (multipart/form-data):
        files : File[] — ملفات متعددة
        file  : File   — ملف واحد أو ZIP

    Response (فوري):
        {
            "task_id"     : "celery-task-uuid",
            "status"      : "processing",
            "message"     : "3 files queued for processing",
            "project_id"  : "uuid",
            "check_status": "/api/upm/tasks/celery-task-uuid/"
        }
    """
    permission_classes = [IsAuthenticated, IsDeveloperRole]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, project_id):
        logger.info(f"[FOLDER-UPLOAD] Request from:{request.user.username}, project:{project_id}")

        # 1. التحقق من المشروع والملكية
        project = get_object_or_404(Project, project_id=project_id)
        if project.user != request.user:
            return Response({"error": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        # 2. قراءة الملفات وتحويلها لـ list يتخزن في Redis
        files_data = []

        all_files = request.FILES.getlist('files') + request.FILES.getlist('file') + request.FILES.getlist('folder')
        single = request.FILES.get('file') if not request.FILES.getlist('file') else None
        if single:
            all_files.append(single)

        logger.info(f"[FOLDER-UPLOAD] Received files keys: {list(request.FILES.keys())}, count: {len(all_files)}")

        # paths: optional, one per file in 'files', in the same order (a browser sends names only;
        # a client that knows the folders, e.g. webkitRelativePath, sends them here)
        paths = self._read_paths(request)
        loose = request.FILES.getlist('files')
        if paths and len(paths) != len(loose):
            return Response({"error": "paths must have one entry per file in 'files'"},
                            status=status.HTTP_400_BAD_REQUEST)
        path_of = {id(f): p for f, p in zip(loose, paths)} if paths else {}

        for f in all_files:
            file_info = self._read_file(f, path_of.get(id(f)))
            if file_info:
                if id(f) in path_of and not file_info.get('is_zip'):
                    file_info['path'] = path_of[id(f)]
                files_data.append(file_info)
            else:
                logger.info(f"[FOLDER-UPLOAD] Skipped: {f.name} (unsupported extension)")

        if not files_data:
            return Response(
                {"error": "No supported files. Supported: .py .java .js .ts .cs .cpp .rb .go .kt"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 3. بعث الرسالة لـ Redis — هاد السطر هو جوهر Message Broker
        # .delay() = ضع الرسالة في Redis وارجع فوراً بدون انتظار
        # confirm_deletions=true: the user knows this upload deletes half the project or more
        confirm = str(request.data.get('confirm_deletions', '')).strip().lower() in ('1', 'true', 'yes', 'on')
        task = process_upload_task.delay(
            project_id   = str(project_id),
            project_name = project.project_name,
            user_email   = request.user.email,
            files_data   = files_data,
            confirm_deletions = confirm,
        )

        logger.info(f"[FOLDER-UPLOAD] Queued — task_id:{task.id}, files:{len(files_data)}")

        # 4. رجوع فوري بـ task_id — الفرونت يتابع الحالة منه
        return Response({
            "task_id":      task.id,
            "status":       "processing",
            "message":      f"{len(files_data)} file(s) queued for processing",
            "project_id":   str(project_id),
            "check_status": f"/api/upm/tasks/{task.id}/",
        }, status=status.HTTP_202_ACCEPTED)

    @staticmethod
    def _read_paths(request):
        """A list sent as repeated 'paths' fields, or as one JSON string."""
        values = request.data.getlist('paths') if hasattr(request.data, 'getlist') else request.data.get('paths') or []
        if isinstance(values, str):
            values = [values]
        out = []
        for value in values:
            if isinstance(value, str) and value.strip().startswith('['):
                try:
                    out.extend(json.loads(value))
                    continue
                except ValueError:
                    return []
            if value:
                out.append(value)
        return [str(v).replace('\\', '/').lstrip('/') for v in out]

    def _read_file(self, uploaded_file, path=None):
        """
        يقرأ محتوى ملف واحد ويرجعه كـ dict.
        ZIP → يُرسل كـ binary مباشرة للـ AI
        غيره → يُقرأ كـ text
        """
        name = uploaded_file.name
        ext = os.path.splitext(name)[1].lower()

        # ZIP — نبعثه binary مباشرة للـ AI
        if ext == '.zip':
            try:
                content_bytes = uploaded_file.read()
                return {
                    'filename':     name,
                    'content':      content_bytes.decode('latin-1'),  # binary-safe encoding
                    'content_type': 'application/zip',
                    'is_zip':       True,
                }
            except Exception as e:
                logger.warning(f"[FOLDER-UPLOAD] Failed to read ZIP {name}: {e}")
                return None

        if ext not in SUPPORTED_EXTENSIONS and not is_support_file(path or name):
            return None

        try:
            content = uploaded_file.read().decode('utf-8', errors='ignore')
            return {
                'filename':     name,
                'content':      content,
                'content_type': uploaded_file.content_type or 'text/plain',
                'is_zip':       False,
            }
        except Exception as e:
            logger.warning(f"[FOLDER-UPLOAD] Failed to read {name}: {e}")
            return None