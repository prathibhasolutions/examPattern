from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='seriesaccess',
            name='expires_at',
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text='Access expiry datetime. Null = never expires (legacy). '
                          'Paid and admin-granted access expires 3 months from grant.',
            ),
        ),
    ]
