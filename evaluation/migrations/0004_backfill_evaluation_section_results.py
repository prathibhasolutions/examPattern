from decimal import Decimal

from django.db import migrations


def backfill_section_results(apps, schema_editor):
    EvaluationResult = apps.get_model('evaluation', 'EvaluationResult')
    EvaluationSectionResult = apps.get_model('evaluation', 'EvaluationSectionResult')
    Section = apps.get_model('testseries', 'Section')
    valid_section_ids = set(Section.objects.values_list('id', flat=True))

    rows = []
    for result in EvaluationResult.objects.all().iterator():
        section_scores = result.section_scores or {}
        for payload in section_scores.values():
            section_id = payload.get('section_id')
            if not section_id:
                continue
            try:
                section_id = int(section_id)
            except Exception:
                continue
            if section_id not in valid_section_ids:
                continue
            try:
                score = Decimal(str(payload.get('score', '0')))
            except Exception:
                score = Decimal('0')

            rows.append(
                EvaluationSectionResult(
                    evaluation_result_id=result.id,
                    section_id=section_id,
                    score=score,
                    correct_count=int(payload.get('correct', 0) or 0),
                    incorrect_count=int(payload.get('incorrect', 0) or 0),
                    unanswered_count=int(payload.get('unanswered', 0) or 0),
                    subjective_count=int(payload.get('subjective', 0) or 0),
                    bonus_count=int(payload.get('bonus', 0) or 0),
                    total_questions=int(payload.get('total_questions', 0) or 0),
                )
            )

    if rows:
        EvaluationSectionResult.objects.bulk_create(rows, batch_size=500, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('evaluation', '0003_evaluationjob_evaluationsectionresult_and_more'),
        ('testseries', '0013_remove_section_testseries__test_id_b6db3d_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_section_results, migrations.RunPython.noop),
    ]
