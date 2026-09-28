from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0120_billingrecord_net_amount_and_more'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SubscriptionCancellationFeedback',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('band_name', models.CharField(max_length=100)),
                ('gateway_subscription_id', models.CharField(blank=True, max_length=100)),
                ('reason', models.TextField(max_length=1000)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('band', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='subscription_cancellation_feedback', to='core.band')),
                ('requested_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='subscription_cancellation_feedback', to=settings.AUTH_USER_MODEL)),
                ('subscription', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='cancellation_feedback', to='core.bandsubscription')),
            ],
            options={
                'verbose_name': 'Feedback de cancelamento',
                'verbose_name_plural': 'Feedbacks de cancelamento',
                'ordering': ['-created_at'],
            },
        ),
    ]
