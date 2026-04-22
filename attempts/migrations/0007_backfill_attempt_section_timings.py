from django.db import migrations


def backfill_attempt_section_timings(apps, schema_editor):
    TestAttempt = apps.get_model('attempts', 'TestAttempt')
    AttemptSectionTiming = apps.get_model('attempts', 'AttemptSectionTiming')
    Section = apps.get_model('testseries', 'Section')

    rows_to_create = []
    existing_pairs = set(
        AttemptSectionTiming.objects.values_list('attempt_id', 'section_id')
    )
    valid_section_ids = set(Section.objects.values_list('id', flat=True))

    for attempt in TestAttempt.objects.exclude(section_timings={}):
        section_timings = attempt.section_timings or {}
        for section_id, seconds in section_timings.items():
            try:
                section_id_int = int(section_id)
                seconds_int = int(seconds or 0)
            except (TypeError, ValueError):
                continue

            if seconds_int <= 0:
                continue
            if section_id_int not in valid_section_ids:
                continue

            pair = (attempt.id, section_id_int)
            if pair in existing_pairs:
                continue

            rows_to_create.append(
                AttemptSectionTiming(
                    attempt_id=attempt.id,
                    section_id=section_id_int,
                    time_spent_seconds=seconds_int,
                )
            )
            existing_pairs.add(pair)

    if rows_to_create:
        AttemptSectionTiming.objects.bulk_create(rows_to_create, batch_size=500)


class Migration(migrations.Migration):

    dependencies = [
        ('attempts', '0006_attemptsectiontiming_and_evaluation_state'),
        ('testseries', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(backfill_attempt_section_timings, migrations.RunPython.noop),
    ]