"""Which task ids UPM really sent, and when.

Celery answers PENDING for any id it has no result for: a task still waiting in the queue, an id
that never existed, and a task whose result has expired (results are kept for one day) all look
the same. To tell them apart, UPM notes the id of every task it publishes, with the time, in the
same Redis as the results. The note lives longer than the result (30 days).

Nothing here may break publishing: if Redis is not reachable the note is skipped and the status
route falls back to the old answer.
"""
import logging
import time

from django.conf import settings

logger = logging.getLogger(__name__)

PREFIX = "upm:task-sent:"
KEEP_SECONDS = 30 * 24 * 3600

_client = None


def _redis():
    global _client
    if _client is None:
        import redis

        _client = redis.Redis.from_url(settings.CELERY_RESULT_BACKEND, socket_timeout=2)
    return _client


def record_sent(task_id, now=None):
    if not task_id:
        return
    try:
        _redis().set(PREFIX + str(task_id), str(now if now is not None else time.time()), ex=KEEP_SECONDS)
    except Exception as exc:                       # never stop a task from being sent
        logger.warning(f"[TASKS] could not note task {task_id}: {exc}")


def sent_at(task_id):
    """→ (known, seconds since epoch or None). known=False when Redis could not be asked."""
    try:
        value = _redis().get(PREFIX + str(task_id))
    except Exception as exc:
        logger.warning(f"[TASKS] could not read task note {task_id}: {exc}")
        return False, None
    return True, (float(value) if value is not None else None)


def on_after_publish(sender=None, headers=None, body=None, **kwargs):
    """Celery `after_task_publish` signal: note the id of the task just sent."""
    task_id = (headers or {}).get("id")
    if not task_id and isinstance(body, dict):     # message protocol 1
        task_id = body.get("id")
    record_sent(task_id)
