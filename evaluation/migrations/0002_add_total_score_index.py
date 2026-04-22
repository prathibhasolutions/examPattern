from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('evaluation', '0001_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='evaluationresult',
            index=models.Index(fields=['total_score'], name='evaluation__total_s_7b7f7b_idx'),
        ),
    ]
