from django.apps import AppConfig
import sys
from django.conf import settings


class AttemptsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'attempts'

    def ready(self):
        from . import sqlite_tuning  # noqa: F401
        if getattr(settings, 'EVALUATION_QUEUE_BACKEND', 'local').lower() != 'local':
            return
        skip_commands = {'migrate', 'makemigrations', 'collectstatic', 'shell', 'dbshell', 'test'}
        if any(cmd in sys.argv for cmd in skip_commands):
            return
        from .evaluation_queue import start_local_evaluation_worker
        start_local_evaluation_worker()
