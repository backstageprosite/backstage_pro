import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import BandSubscription, BillingRecord


class Command(BaseCommand):
    help = (
        "Varredura diaria de vencimentos de assinaturas. "
        "Cria faturas automaticamente para assinaturas que vencem em ate 7 dias "
        "e marca como Vencido as que passaram da data. "
        "Deve ser executado todo inicio do dia via cron/scheduler."
    )

    def handle(self, *args, **options):
        today = timezone.localdate()
        seven_days = today + datetime.timedelta(days=7)

        created = 0
        updated_vencido = 0
        updated_vencendo = 0

        subscriptions = BandSubscription.objects.filter(
            status__in=["ATIVO", "VENCENDO"],
            is_deleted=False
        )

        for sub in subscriptions:
            if not sub.next_due_date:
                continue

            # Apenas criar fatura automática se não existe ainda
            if sub.next_due_date <= seven_days:
                exists = BillingRecord.objects.filter(
                    subscription=sub,
                    due_date=sub.next_due_date
                ).exists()
                if not exists:
                    month_names = {
                        1: "Janeiro", 2: "Fevereiro", 3: "Marco", 4: "Abril",
                        5: "Maio", 6: "Junho", 7: "Julho", 8: "Agosto",
                        9: "Setembro", 10: "Outubro", 11: "Novembro", 12: "Dezembro"
                    }
                    month_name = month_names.get(sub.next_due_date.month, str(sub.next_due_date.month))
                    ref_period = f"{month_name}/{sub.next_due_date.year}"

                    BillingRecord.objects.create(
                        subscription=sub,
                        band=sub.band,
                        reference_period=ref_period,
                        amount=sub.contracted_value,
                        due_date=sub.next_due_date,
                        status="PENDENTE",
                        plan_name=getattr(sub, "plan_name", ""),
                        billing_cycle=sub.billing_cycle,
                    )
                    created += 1

        # Verificar assinaturas com suspensão financeira (>= 5 dias de atraso) para enfileirar e-mail transacional
        suspended_count = 0
        all_active_subs = BandSubscription.objects.filter(
            status="ATIVO",
            is_deleted=False,
            next_due_date__isnull=False
        )
        for sub in all_active_subs:
            if sub.is_financially_suspended:
                try:
                    from core.services.email_service import enqueue_email, resolve_subscription_recipient
                    recip_email, recip_name = resolve_subscription_recipient(sub)
                    if recip_email and sub.next_due_date and sub.band and sub.band.slug:
                        from django.urls import reverse
                        from core.services.email_service import get_canonical_base_url
                        base_url = get_canonical_base_url()
                        sub_path = reverse('minha_assinatura', kwargs={'band_slug': sub.band.slug})
                        subscription_url = f"{base_url}{sub_path}"

                        enqueue_email(
                            email_type='SUBSCRIPTION_SUSPENDED',
                            recipient_email=recip_email,
                            subject=f"Acesso Suspenso por Pendência — Backstage Pro ({sub.band.name})",
                            idempotency_key=f"sub-suspended-{sub.id}-{sub.next_due_date.isoformat()}",
                            template_name='emails/subscription_suspended',
                            context_data={
                                'user_name': recip_name,
                                'responsible_name': recip_name,
                                'band_name': sub.band.name,
                                'plan_name': sub.plan_name,
                                'contracted_value': f"{sub.contracted_value:.2f}",
                                'days_overdue': sub.days_overdue(),
                                'next_due_date': sub.next_due_date.strftime('%d/%m/%Y'),
                                'subscription_url': subscription_url,
                            },
                            related_object_type='BandSubscription',
                            related_object_id=str(sub.id)
                        )
                        suspended_count += 1
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Falha ao enfileirar e-mail de suspensão para sub {sub.id}: {e}"))

        self.stdout.write(self.style.SUCCESS(
            f"Varredura concluida: {created} faturas criadas, "
            f"{updated_vencendo} assinaturas marcadas como VENCENDO, "
            f"{updated_vencido} marcadas como VENCIDO, "
            f"{suspended_count} suspensões financeiras verificadas/notificadas."
        ))
