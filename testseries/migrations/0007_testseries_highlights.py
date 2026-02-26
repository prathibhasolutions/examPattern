from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("testseries", "0006_testseries_exam_sections"),
    ]

    operations = [
        migrations.CreateModel(
            name="TestSeriesHighlight",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=120)),
                ("value", models.CharField(blank=True, max_length=240)),
                ("order", models.PositiveSmallIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "series",
                    models.ForeignKey(on_delete=models.deletion.CASCADE, related_name="highlights", to="testseries.testseries"),
                ),
            ],
            options={
                "ordering": ["order", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="testserieshighlight",
            index=models.Index(fields=["series"], name="testseries_series_i_9a5a3f_idx"),
        ),
    ]
