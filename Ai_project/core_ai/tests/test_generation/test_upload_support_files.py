import io
import zipfile
from unittest.mock import Mock, patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from core_ai.views.folder_upload import FolderUploadView


@pytest.mark.parametrize("path,keep", [
    ("requirements.txt", True), ("requirements-dev.txt", True), ("requirements/base.txt", True),
    ("pyproject.toml", True), ("setup.cfg", True), ("pytest.ini", True), ("conftest.py", True),
    ("notes.txt", False), ("config.toml", False), ("tox.ini", False), ("other.cfg", False),
    ("docs/requirements.md", False)])
def test_zip_and_loose_support_file_filter(path, keep):
    view = FolderUploadView()
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr(path, "data")
    data.seek(0)
    loose = SimpleUploadedFile(path.split("/")[-1], b"data")
    expected = [(path, "data")] if keep else []
    assert view._extract_from_zip(data) == expected
    assert view._extract_from_files([loose], "demo", {id(loose): path}) == expected


def test_saved_support_file_never_schedules_analysis():
    collection = Mock()
    collection.find_one.return_value = None
    with patch("core_ai.views.folder_upload.save_to_gridfs", return_value="abc"), patch(
        "core_ai.views.folder_upload.analyze_code_file_task.delay") as enqueue:
        FolderUploadView()._save_single_file(collection, None, "demo/conftest.py", "# config", "p",
                                              "demo", 1, "demo@example.com", "demo")
    doc = collection.insert_one.call_args.args[0]
    assert doc["file_type"] == "support" and doc["analysis_status"] == "NOT_ANALYSED"
    enqueue.assert_not_called()
