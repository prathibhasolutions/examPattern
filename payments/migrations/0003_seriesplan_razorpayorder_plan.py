import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0002_seriesaccess_expires_at'),
        ('testseries', '__first__'),
    ]

    operations = [
        migrations.CreateModel(
            name='SeriesPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(
                    max_length=100,
                    help_text='Display name, e.g. "3 Months", "Half Year", "1 Year"',
                )),
                ('duration_days', models.PositiveIntegerField(
                    help_text='Access duration in days (e.g. 90, 180, 365)',
                )),
                ('price', models.DecimalField(
                    max_digits=8, decimal_places=2,
                    help_text='Price in INR',
                )),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('series', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='plans',
                    to='testseries.testseries',
                )),
            ],
            options={
                'ordering': ['price'],
                'unique_together': {('series', 'name')},
            },
        ),
        migrations.AddField(
            model_name='razorpayorder',
            name='plan',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='orders',
                to='payments.seriesplan',
                help_text='The plan selected by the user (null for legacy single-price orders)',
            ),
        ),
    ]
