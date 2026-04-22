from django.db import migrations, models
import django.db.models.deletion


def backfill_evaluation_state(apps, schema_editor):
    TestAttempt = apps.get_model('attempts', 'TestAttempt')
    EvaluationResult = apps.get_model('evaluation', 'EvaluationResult')

    submitted_attempts = TestAttempt.objects.filter(status='submitted')
    evaluated_ids = set(EvaluationResult.objects.values_list('attempt_id', flat=True))

    TestAttempt.objects.filter(
        id__in=evaluated_ids,
        status='submitted',
    ).update(evaluation_state='success')

    TestAttempt.objects.filter(
        status='submitted',
    ).exclude(id__in=evaluated_ids).update(evaluation_state='pending')


class Migration(migrations.Migration):

    dependencies = [
        ('attempts', '0005_alter_testattempt_option_order_and_more'),
        ('evaluation', '0001_initial'),
        ('testseries', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='testattempt',
            name='evaluation_error',
            field=models.TextField(blank=True, default=''),
        ),
        migrations.AddField(
            model_name='testattempt',
            name='evaluation_finished_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='testattempt',
            name='evaluation_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='testattempt',
            name='evaluation_state',
            field=models.CharField(
                choices=[
                    ('not_started', 'Not Started'),
                    ('pending', 'Pending'),
                    ('running', 'Running'),
                    ('success', 'Success'),
                    ('failed', 'Failed'),
                ],
                default='not_started',
                max_length=20,
            ),
        ),
        migrations.AddIndex(
            model_name='testattempt',
            index=models.Index(fields=['test', 'status', 'attempt_number', 'score'], name='attempts_tes_test_id_047d5b_idx'),
        ),
        migrations.AddIndex(
            model_name='testattempt',
            index=models.Index(fields=['status', 'submitted_at'], name='attempts_tes_status_a9eebf_idx'),
        ),
        migrations.AddIndex(
            model_name='testattempt',
            index=models.Index(fields=['evaluation_state', 'submitted_at'], name='attempts_tes_evaluat_a20d2f_idx'),
        ),
        migrations.CreateModel(
            name='AttemptSectionTiming',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('time_spent_seconds', models.PositiveIntegerField(default=0)),
                ('attempt', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='section_timing_rows', to='attempts.testattempt')),
                ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attempt_timing_rows', to='testseries.section')),
            ],
        ),
        migrations.AddIndex(
            model_name='attemptsectiontiming',
            index=models.Index(fields=['attempt'], name='attempts_att_attempt_970021_idx'),
        ),
        migrations.AddIndex(
            model_name='attemptsectiontiming',
            index=models.Index(fields=['section'], name='attempts_att_section_ab6b6a_idx'),
        ),
        migrations.AddConstraint(
            model_name='attemptsectiontiming',
            constraint=models.UniqueConstraint(fields=('attempt', 'section'), name='uq_attempt_section_timing'),
        ),
        migrations.RunPython(backfill_evaluation_state, migrations.RunPython.noop),
    ]
