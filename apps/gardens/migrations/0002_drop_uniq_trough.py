from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("gardens", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="trough",
            name="uniq_trough_code_per_garden",
        ),
    ]
