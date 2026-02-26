import django.db.models.deletion
from django.db import migrations, models


def add_default_sections(apps, schema_editor):
    TestSeries = apps.get_model('testseries', 'TestSeries')
    SeriesSection = apps.get_model('testseries', 'SeriesSection')
    Test = apps.get_model('testseries', 'Test')

    for series in TestSeries.objects.all():
        section, _ = SeriesSection.objects.get_or_create(
            series=series,
            name='All Tests',
            defaults={
                'slug': 'all-tests',
                'order': 1,
                'is_active': True,
            },
        )
        Test.objects.filter(series=series, series_section__isnull=True).update(
            series_section=section
        )


def remove_default_sections(apps, schema_editor):
    SeriesSection = apps.get_model('testseries', 'SeriesSection')
    SeriesSection.objects.filter(name='All Tests').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('testseries', '0002_alter_testseries_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='SeriesSection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('slug', models.SlugField(max_length=170)),
                ('order', models.PositiveSmallIntegerField(default=1)),
                ('is_active', models.BooleanField(default=True)),
                ('series', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sections', to='testseries.testseries')),
            ],
            options={
                'ordering': ['series', 'order', 'name'],
            },
        ),
        migrations.CreateModel(
            name='SeriesSubsection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150)),
                ('slug', models.SlugField(max_length=170)),
                ('order', models.PositiveSmallIntegerField(default=1)),
                ('is_active', models.BooleanField(default=True)),
                ('section', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='subsections', to='testseries.seriessection')),
            ],
            options={
                'ordering': ['section', 'order', 'name'],
            },
        ),
        migrations.AddField(
            model_name='test',
            name='series_section',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tests', to='testseries.seriessection'),
        ),
        migrations.AddField(
            model_name='test',
            name='series_subsection',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='tests', to='testseries.seriessubsection'),
        ),
        migrations.AddConstraint(
            model_name='seriessection',
            constraint=models.UniqueConstraint(fields=('series', 'slug'), name='uq_series_section_slug'),
        ),
        migrations.AddConstraint(
            model_name='seriessection',
            constraint=models.UniqueConstraint(fields=('series', 'name'), name='uq_series_section_name'),
        ),
        migrations.AddConstraint(
            model_name='seriessubsection',
            constraint=models.UniqueConstraint(fields=('section', 'slug'), name='uq_series_subsection_slug'),
        ),
        migrations.AddConstraint(
            model_name='seriessubsection',
            constraint=models.UniqueConstraint(fields=('section', 'name'), name='uq_series_subsection_name'),
        ),
        migrations.RunPython(add_default_sections, remove_default_sections),
    ]