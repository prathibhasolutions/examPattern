from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('test_builder', '0008_pdfimportjob'),
    ]

    operations = [
        migrations.AddField(
            model_name='testdraft',
            name='shuffle_questions',
            field=models.BooleanField(
                default=False,
                help_text='If True, questions and options are shuffled into a unique random order per student',
            ),
        ),
    ]
