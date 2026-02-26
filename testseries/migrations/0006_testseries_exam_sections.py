from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("testseries", "0005_test_use_sectional_timing"),
    ]

    operations = [
        migrations.AddField(
            model_name="testseries",
            name="exam_cover",
            field=models.ImageField(blank=True, null=True, upload_to="series_exam_covers/"),
        ),
        migrations.CreateModel(
            name="TestSeriesExamSection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("body", models.TextField(blank=True)),
                ("image", models.ImageField(blank=True, null=True, upload_to="series_exam_sections/")),
                ("order", models.PositiveSmallIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "series",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="exam_sections", to="testseries.testseries"),
                ),
            ],
            options={
                "ordering": ["order", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="testseriesexamsection",
            index=models.Index(fields=["series"], name="testseries_series_i_8b5a7f_idx"),
        ),
    ]
