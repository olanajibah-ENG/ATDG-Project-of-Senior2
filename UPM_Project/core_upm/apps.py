from django.apps import AppConfig


class CoreUpmConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core_upm'

    def ready(self):
        # note every task UPM sends, so the status route can tell "waiting" from "unknown / expired"
        from celery.signals import after_task_publish

        from core_upm import task_registry

        after_task_publish.connect(task_registry.on_after_publish, weak=False,
                                   dispatch_uid="upm_task_registry")
