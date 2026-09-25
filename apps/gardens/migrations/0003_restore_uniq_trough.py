from django.db import migrations, models


def dedupe_trough_codes(apps, schema_editor):
    """约束被摘除期间可能已产生同园同号的重复行，加约束前先清理。

    每组 (garden, troughCode) 保留最早创建的一条（id 最小），其余删除；
    关联的萎凋批次由外键级联删除。
    """
    Trough = apps.get_model("gardens", "Trough")
    dup_ids = []
    seen = set()
    for pk, garden_id, code in Trough.objects.order_by("id").values_list(
        "id", "garden_id", "troughCode"
    ):
        key = (garden_id, code)
        if key in seen:
            dup_ids.append(pk)
        else:
            seen.add(key)
    if dup_ids:
        Trough.objects.filter(id__in=dup_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("gardens", "0002_drop_uniq_trough"),
    ]

    operations = [
        migrations.RunPython(dedupe_trough_codes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="trough",
            constraint=models.UniqueConstraint(
                fields=("garden", "troughCode"),
                name="uniq_trough_code_per_garden",
                violation_error_code="unique_together",
                violation_error_message="该茶园已存在相同槽位编号，请更换编号。",
            ),
        ),
    ]
