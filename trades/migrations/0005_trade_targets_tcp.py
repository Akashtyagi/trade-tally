from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("trades", "0004_tradebook_fill"),
    ]

    operations = [
        migrations.AddField(
            model_name="tradeidea",
            name="target_2",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="tradeidea",
            name="target_3",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="tradeidea",
            name="tcp_percent",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True),
        ),
    ]
