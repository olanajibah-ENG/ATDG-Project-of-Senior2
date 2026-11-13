from django.apps import AppConfig


class CoreTestingConfig(AppConfig):
    """Feature 1 — Generate Trusted Tests. Lives beside core_ai inside the AI service."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "core_testing"
