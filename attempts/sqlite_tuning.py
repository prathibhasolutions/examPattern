from django.conf import settings
from django.db.backends.signals import connection_created
from django.dispatch import receiver


@receiver(connection_created)
def apply_sqlite_pragmas(sender, connection, **kwargs):
    if connection.vendor != 'sqlite':
        return

    journal_mode = getattr(settings, 'SQLITE_JOURNAL_MODE', 'WAL')
    synchronous = getattr(settings, 'SQLITE_SYNCHRONOUS', 'NORMAL')

    with connection.cursor() as cursor:
        cursor.execute(f"PRAGMA journal_mode={journal_mode};")
        cursor.execute(f"PRAGMA synchronous={synchronous};")
