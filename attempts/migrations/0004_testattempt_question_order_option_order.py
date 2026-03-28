from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('attempts', '0003_add_time_remaining_seconds'),
    ]

    operations = [
        migrations.AddField(
            model_name='testattempt',
            name='question_order',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Shuffled question order per section: {"<section_id>": [q_id, ...]}',
            ),
        ),
        migrations.AddField(
            model_name='testattempt',
            name='option_order',
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text='Shuffled option order per question: {"<question_id>": [opt_id, ...]}',
            ),
        ),
    ]
