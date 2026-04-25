from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('testseries', '0013_remove_section_testseries__test_id_b6db3d_idx_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='testseries',
            name='price',
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text='Price in INR. Set to 0 for a free series.',
                max_digits=8,
            ),
        ),
    ]
