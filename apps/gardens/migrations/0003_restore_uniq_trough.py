from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gardens", "0002_drop_uniq_trough"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="trough",
            constraint=models.UniqueConstraint(
                fields=("garden", "troughCode"),
                name="uniq_trough_code_per_garden",
            ),
        ),
    ]
