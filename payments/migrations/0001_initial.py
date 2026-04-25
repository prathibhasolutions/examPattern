import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('accounts', '0008_customuser_has_legacy_access'),
        ('testseries', '0014_testseries_price'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SeriesAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('access_type', models.CharField(
                    choices=[('paid', 'Paid'), ('admin_granted', 'Admin Granted')],
                    default='paid',
                    max_length=20,
                )),
                ('is_active', models.BooleanField(default=True)),
                ('granted_at', models.DateTimeField(auto_now_add=True)),
                ('razorpay_payment_id', models.CharField(blank=True, max_length=100)),
                ('amount_paid', models.DecimalField(
                    blank=True, decimal_places=2, max_digits=8, null=True,
                    help_text='Amount paid in INR at the time of purchase.',
                )),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='series_accesses',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('series', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='user_accesses',
                    to='testseries.testseries',
                )),
                ('granted_by', models.ForeignKey(
                    blank=True,
                    help_text='Admin who manually granted this access (null for payments)',
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='granted_series_accesses',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={
                'ordering': ['-granted_at'],
            },
        ),
        migrations.CreateModel(
            name='RazorpayOrder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('razorpay_order_id', models.CharField(max_length=100, unique=True)),
                ('amount_paise', models.PositiveIntegerField(help_text='Amount in paise (INR × 100).')),
                ('status', models.CharField(
                    choices=[('created', 'Created'), ('paid', 'Paid'), ('failed', 'Failed')],
                    default='created',
                    max_length=20,
                )),
                ('razorpay_payment_id', models.CharField(blank=True, max_length=100)),
                ('razorpay_signature', models.CharField(blank=True, max_length=256)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('user', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='razorpay_orders',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('series', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='razorpay_orders',
                    to='testseries.testseries',
                )),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='seriesaccess',
            constraint=models.UniqueConstraint(
                fields=['user', 'series'],
                name='uq_series_access_user_series',
            ),
        ),
        migrations.AddIndex(
            model_name='seriesaccess',
            index=models.Index(fields=['user', 'series', 'is_active'], name='payments_se_user_id_series_active_idx'),
        ),
        migrations.AddIndex(
            model_name='seriesaccess',
            index=models.Index(fields=['series', 'is_active'], name='payments_se_series_active_idx'),
        ),
        migrations.AddIndex(
            model_name='razorpayorder',
            index=models.Index(fields=['user', 'series', 'status'], name='payments_rz_user_series_status_idx'),
        ),
        migrations.AddIndex(
            model_name='razorpayorder',
            index=models.Index(fields=['razorpay_order_id'], name='payments_rz_order_id_idx'),
        ),
    ]
