"""
views/task_status_view.py  ← جديد كلياً
=========================
ليش هاد الملف موجود؟
    بعد ما الفرونت يرسل ملفات ويستقبل task_id،
    محتاج يعرف: هل خلص؟ هل فشل؟ شو النتيجة؟
    هاد الـ endpoint يجاوبه.

الفرونت يعمل polling:
    كل 3 ثواني يسأل عن الحالة حتى يشوف "completed" أو "failed"
"""

import logging
import time

from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from celery.result import AsyncResult

from core_upm import task_registry

# Celery keeps a task's result this long (its default: one day). After that the id reads as PENDING.
RESULT_KEEP_SECONDS = 24 * 3600

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class TaskStatusView(APIView):
    """
    GET /api/upm/tasks/<task_id>/

    يرجع حالة الـ Celery task.

    Response:
    لو شغال:
        {"task_id": "...", "status": "processing"}

    لو خلص:
        {
            "task_id"       : "...",
            "status"        : "completed",
            "version_number": 2,
            "file_count"    : 15,
            "mysql_saved"   : {"version": 2, "folders": 3, "artifacts": 15}
        }

    لو فشل:
        {"task_id": "...", "status": "failed", "error": "..."}
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, task_id):
        result = AsyncResult(task_id)

        if result.state == 'PENDING':
            # Celery says PENDING for a task still in the queue, for an id it never saw, and for a
            # task whose result has expired. UPM's own note of sent tasks tells them apart.
            asked, sent = task_registry.sent_at(task_id)
            if asked and sent is None:
                return Response({
                    "task_id": task_id,
                    "status":  "unknown",
                    "message": "No task with this id was sent, or it was sent before tasks were "
                               "recorded and its result has expired (results are kept for one day).",
                }, status=status.HTTP_404_NOT_FOUND)
            if asked and time.time() - sent > RESULT_KEEP_SECONDS:
                return Response({
                    "task_id": task_id,
                    "status":  "expired",
                    "message": "The task ran, but its result is no longer kept (results are kept for one day). "
                               "Check the project's versions instead.",
                }, status=status.HTTP_410_GONE)
            # الرسالة في Redis لسا ما أخذها أي worker
            return Response({
                "task_id": task_id,
                "status":  "pending",
                "message": "Task is waiting to be processed",
            })

        elif result.state == 'STARTED' or result.state == 'RETRY':
            # Worker أخذ الرسالة وبدأ يشتغل
            return Response({
                "task_id": task_id,
                "status":  "processing",
                "message": "Task is being processed",
            })

        elif result.state == 'SUCCESS':
            # خلص بنجاح
            task_result = result.result or {}
            if isinstance(task_result, dict) and task_result.get('status') == 'rejected':
                # the task ran, but the AI service refused the upload on purpose: nothing was saved
                return Response({
                    "task_id":      task_id,
                    "status":       "rejected",
                    "error":        task_result.get('reason'),
                    "code":         task_result.get('code'),
                    "would_delete": task_result.get('would_delete', []),
                    "top_folder":   task_result.get('top_folder'),
                }, status=status.HTTP_409_CONFLICT)
            return Response({
                "task_id":        task_id,
                "status":         "completed",
                "version_number": task_result.get('version_number'),
                "file_count":     task_result.get('file_count', 0),
                "mysql_saved":    task_result.get('mysql_saved', {}),
            })

        elif result.state == 'FAILURE':
            # فشل بعد كل المحاولات
            return Response({
                "task_id": task_id,
                "status":  "failed",
                "error":   str(result.result),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        else:
            return Response({
                "task_id": task_id,
                "status":  result.state.lower(),
            })