from django.db import migrations, models


def set_legacy_access_for_existing_users(apps, schema_editor):
    """All accounts created before the paywall gets legacy (unlimited) access."""
    CustomUser = apps.get_model('accounts', 'CustomUser')
    CustomUser.objects.all().update(has_legacy_access=True)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0007_forgotpasswordrequest_accounts_fo_status_4944b4_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='has_legacy_access',
            field=models.BooleanField(
                default=False,
                help_text=(
                    'If True, user has unlimited access to all test series without payment. '
                    'Set automatically for all accounts created before the paywall was introduced.'
                ),
            ),
        ),
        # Immediately grant legacy access to every pre-existing user.
        migrations.RunPython(
            set_legacy_access_for_existing_users,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
