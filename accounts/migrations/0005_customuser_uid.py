import random
import string

from django.db import migrations, models


def _gen_uid(year):
    chars = string.ascii_uppercase + string.digits
    return 'EXP' + str(year) + ''.join(random.choices(chars, k=4))


def populate_uids(apps, schema_editor):
    """Back-fill UIDs for every existing user using their account-creation year."""
    CustomUser = apps.get_model('accounts', 'CustomUser')
    used = set()
    for user in CustomUser.objects.all().order_by('id'):
        year = user.created_at.year if user.created_at else 2026
        for _ in range(100):
            uid = _gen_uid(year)
            if uid not in used:
                used.add(uid)
                user.uid = uid
                user.save(update_fields=['uid'])
                break


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_alter_customuser_mobile'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='uid',
            field=models.CharField(
                blank=True, db_index=True, max_length=11, null=True, unique=True,
                help_text='Unique user ID in format EXP{YEAR}{4 chars}, e.g. EXP2026A3F9',
            ),
        ),
        migrations.RunPython(populate_uids, noop),
    ]
