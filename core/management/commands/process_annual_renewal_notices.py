import datetime
import logging
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.conf import settings
from django.core.mail import send_mail

from core.models import BandSubscription, AnnualPlanPurchase, AnnualRenewalNotice, SystemSettings

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Processa e envia os avisos pré-renovação de 30 dias para contratos anuais (D-30).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Avalia elegibilidade e exibe o que seria enviado sem persistir ou enviar e-mails.',
        )
        parser.add_argument(
            '--subscription-id',
            type=int,
            help='Processa especificamente a assinatura informada pelo ID.',
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Data de referência no formato YYYY-MM-DD (padrão: hoje). Permitido apenas em sandbox/homologação.',
        )

    def get_recipient_email(self, sub: BandSubscription) -> str:
        """
        Obtém o e-mail canônico de cobrança/responsável da banda.
        Prioriza sub.billing_email -> e-mail do produtor da banda -> e-mail do primeiro usuário da banda.
        """
        if sub.billing_email and sub.billing_email.strip():
            return sub.billing_email.strip()

        produtor = sub.band.users.filter(role__in=['PRODUTOR', 'EMPRESARIO']).exclude(email='').first()
        if produtor and produtor.email and produtor.email.strip():
            return produtor.email.strip()

        any_user = sub.band.users.exclude(email='').first()
        if any_user and any_user.email and any_user.email.strip():
            return any_user.email.strip()

        return ''

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        sub_id = options.get('subscription_id')
        date_str = options.get('date')

        target_date = timezone.localdate()
        if date_str:
            import os
            # PROTEÇÃO HARD BLOCK: O parâmetro --date é estritamente proibido em produção.
            raw_asaas_env = getattr(settings, 'ASAAS_ENVIRONMENT', os.getenv('ASAAS_ENVIRONMENT', 'sandbox')).strip().lower()
            django_env = getattr(settings, 'DJANGO_ENV', os.getenv('DJANGO_ENV', 'development')).strip().lower()
            if raw_asaas_env == 'production' or django_env == 'production':
                self.stderr.write(self.style.ERROR(
                    "BLOQUEIO DE SEGURANÇA: O parâmetro --date é estritamente proibido em ambiente de PRODUÇÃO. Operação abortada."
                ))
                return

            try:
                target_date = datetime.date.fromisoformat(date_str)
            except ValueError:
                self.stderr.write(self.style.ERROR(f"Data inválida: {date_str}. Use YYYY-MM-DD."))
                return

        self.stdout.write(f"Iniciando processamento de avisos pré-renovação de 30 dias para a data: {target_date}")
        if dry_run:
            self.stdout.write(self.style.WARNING("MODO DRY-RUN ATIVADO: Nenhum e-mail será enviado e nenhum registro será criado."))

        qs = BandSubscription.objects.filter(
            billing_cycle='ANUAL',
            status='ATIVO',
            auto_renew=True,
            cancel_at_period_end=False,
            is_deleted=False
        )
        if sub_id:
            qs = qs.filter(id=sub_id)

        processed_count = 0
        sent_count = 0
        failed_count = 0
        skipped_count = 0

        for sub in qs:
            if not sub.next_due_date:
                skipped_count += 1
                continue

            # Janela de aviso: exatamente 30 dias corridos antes do vencimento
            diff_days = (sub.next_due_date - target_date).days
            if diff_days != 30:
                # Fora da janela de 30 dias
                skipped_count += 1
                continue

            # Verificar se já existe aviso criado para esta assinatura e data de renovação (idempotência nível banco)
            existing_notice = AnnualRenewalNotice.objects.filter(
                band_subscription=sub,
                renewal_date=sub.next_due_date
            ).first()

            if existing_notice and existing_notice.status == AnnualRenewalNotice.Status.SENT:
                self.stdout.write(f"Sub {sub.id} ({sub.band.name}): Aviso já enviado anteriormente para {sub.next_due_date}. Pulando.")
                skipped_count += 1
                continue

            # Obter quantidade de parcelas da última compra
            last_confirmed = AnnualPlanPurchase.objects.filter(
                band_subscription=sub,
                status=AnnualPlanPurchase.Status.CONFIRMED
            ).order_by('-coverage_start').first()
            inst_count = last_confirmed.installment_count if last_confirmed else 1

            current_price = sub.contracted_value or Decimal('199.90')
            public_price = SystemSettings.get_canonical_plan_price(sub.plan_name, 'ANUAL')

            # Preço notificado congela o valor máximo
            notified_price = public_price
            price_changed = (notified_price != current_price)
            notice_type = AnnualRenewalNotice.NoticeType.PRICE_CHANGE if price_changed else AnnualRenewalNotice.NoticeType.STANDARD

            recipient_email = self.get_recipient_email(sub)
            has_recipient = bool(recipient_email)
            would_send = has_recipient

            self.stdout.write(
                f"Sub {sub.id} ({sub.band.name}): renewal_date={sub.next_due_date}, "
                f"current_price=R$ {current_price}, public_price=R$ {public_price}, "
                f"notified_price=R$ {notified_price}, installments={inst_count}x, "
                f"recipient_found={'SIM' if has_recipient else 'NAO'}, would_send={'SIM' if would_send else 'NAO'}"
            )

            if dry_run:
                continue

            # Criar ou recuperar notice PENDING
            notice, created = AnnualRenewalNotice.objects.get_or_create(
                band_subscription=sub,
                renewal_date=sub.next_due_date,
                defaults={
                    'plan_name': sub.plan_name,
                    'billing_cycle': 'ANUAL',
                    'current_contracted_value': current_price,
                    'notified_renewal_price': notified_price,
                    'installment_count': inst_count,
                    'notice_type': notice_type,
                    'email_recipient': recipient_email or None,
                    'scheduled_for': target_date,
                    'status': AnnualRenewalNotice.Status.PENDING,
                }
            )

            if not has_recipient:
                notice.status = AnnualRenewalNotice.Status.FAILED
                notice.error_message = "DESTINATARIO_NAO_ENCONTRADO: Nenhum e-mail financeiro ou produtor cadastrado para a banda."
                notice.save(update_fields=['status', 'error_message', 'updated_at'])
                self.stdout.write(self.style.ERROR(f"  Sub {sub.id}: Falha no envio: Destinatário não encontrado."))
                failed_count += 1
                continue

            # Compor e-mail
            if price_changed:
                subject = "Atualização de valor da sua renovação — Backstage Pro"
                body = (
                    f"Olá, {sub.financial_responsible_name or sub.band.name}!\n\n"
                    f"Sua assinatura do plano {sub.plan_name} Anual está próxima da renovação.\n\n"
                    f"• Data prevista da renovação: {sub.next_due_date.strftime('%d/%m/%Y')}\n"
                    f"• Valor atual contratado: R$ {current_price:.2f}\n"
                    f"• Novo valor da renovação: R$ {notified_price:.2f}\n"
                    f"• Parcelamento: em até {inst_count}x no cartão de crédito\n\n"
                    f"Seu acesso atual permanece totalmente ativo até o fim do período vigente. "
                    f"Caso não deseje renovar sua assinatura, você poderá cancelar a renovação "
                    f"a qualquer momento antes da data prevista diretamente no painel do Backstage Pro.\n\n"
                    f"Atenciosamente,\nEquipe Backstage Pro"
                )
            else:
                subject = "Renovação do Backstage Pro em 30 dias"
                body = (
                    f"Olá, {sub.financial_responsible_name or sub.band.name}!\n\n"
                    f"Sua assinatura do plano {sub.plan_name} Anual será renovada em {sub.next_due_date.strftime('%d/%m/%Y')} "
                    f"no valor de R$ {notified_price:.2f}, mantendo o parcelamento em até {inst_count}x no cartão de crédito.\n\n"
                    f"Seu acesso atual permanece totalmente ativo até o fim do período vigente. "
                    f"Caso não deseje renovar sua assinatura, você poderá cancelar a renovação "
                    f"a qualquer momento antes da data prevista diretamente no painel do Backstage Pro.\n\n"
                    f"Atenciosamente,\nEquipe Backstage Pro"
                )

            from_address = getattr(settings, 'EMAIL_HOST_USER', 'no-reply@backstagepro.site')
            from_email_formatted = f'Backstage Pro <{from_address}>'

            try:
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=from_email_formatted,
                    recipient_list=[recipient_email],
                    fail_silently=False
                )
                notice.status = AnnualRenewalNotice.Status.SENT
                notice.sent_at = timezone.now()
                notice.error_message = None
                notice.save(update_fields=['status', 'sent_at', 'error_message', 'updated_at'])
                self.stdout.write(self.style.SUCCESS(f"  Sub {sub.id}: Aviso de 30 dias enviado com sucesso para {recipient_email}!"))
                sent_count += 1
            except Exception as e:
                # Sanitiza erro sem expor dados sensíveis
                clean_err = str(e).replace('\n', ' ')[:200]
                notice.status = AnnualRenewalNotice.Status.FAILED
                notice.error_message = f"FALHA_ENVIO_EMAIL: {clean_err}"
                notice.save(update_fields=['status', 'error_message', 'updated_at'])
                self.stdout.write(self.style.ERROR(f"  Sub {sub.id}: Falha no envio do e-mail: {clean_err}"))
                failed_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Processamento de avisos concluído. Enviados: {sent_count}, Falhas: {failed_count}, Ignorados: {skipped_count}"
        ))
