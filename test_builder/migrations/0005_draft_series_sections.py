import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('test_builder', '0004_add_draft_locking'),
        ('testseries', '0003_series_sections_and_test_links'),
    ]

    operations = [
        migrations.AddField(
            model_name='testdraft',
            name='series_section',
            field=models.ForeignKey(blank=True, help_text='Section within the test series', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='drafts', to='testseries.seriessection'),
        ),
        migrations.AddField(
            model_name='testdraft',
            name='series_subsection',
            field=models.ForeignKey(blank=True, help_text='Subsection within the test series section', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='drafts', to='testseries.seriessubsection'),
        ),
    ]