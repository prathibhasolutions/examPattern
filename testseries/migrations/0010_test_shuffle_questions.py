from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testseries', '0009_rename_testseries_series_i_9a5a3f_idx_testseries__series__2f22e5_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='test',
            name='shuffle_questions',
            field=models.BooleanField(
                default=False,
                help_text='If True, questions and options are shuffled into a unique random order per student',
            ),
        ),
    ]
