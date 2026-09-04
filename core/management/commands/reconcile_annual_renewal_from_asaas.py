import datetime
import logging
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.conf import settings
from django.utils import timezone

from core.models import BandSubscription, AnnualPlanPurchase, BillingRecord, AnnualRenewalNotice, SystemSettings
from core.services.payments.asaas.client import AsaasClient
from core.services.payments.base import extract_asaas_id

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Reconcilia no banco canônico (PostgreSQL) uma renovação anual já existente e aprovada no Asaas Sandbox, sem criar cobrança.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--subscription-id',
            type=int,
            required=True,
            help='ID da BandSubscription local a ser reconciliada.',
        )
        parser.add_argument(
            '--installment-id',
            type=str,
            required=True,
            help='ID do parcelamento (installment) já criado no Asaas.',
        )
        parser.add_argument(
            '--renewal-date',
            type=str,
            default='2027-09-04',
            help='Data da renovação no formato YYYY-MM-DD (padrão: 2027-09-04).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Apenas consulta e exibe o plano de reconciliação sem aplicar alterações.',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Aplica efetivamente a reconciliação no banco de dados.',
        )

    def handle(self, *args, **options):
        sub_id = options.get('subscription_id')
        installment_id = options.get('installment_id').strip()
        renewal_date_str = options.get('renewal_date')
        dry_run = options.get('dry_run', False)
        apply_changes = options.get('apply', False)

        if not dry_run and not apply_changes:
            self.stderr.write(self.style.ERROR("Você deve especificar --dry-run ou --apply."))
            return

        # 1. BLOQUEIO DE AMBIENTE: Apenas sandbox e homologação/staging/development
        asaas_env = getattr(settings, 'ASAAS_ENVIRONMENT', 'sandbox').strip().lower()
        django_env = getattr(settings, 'DJANGO_ENV', 'development').strip().lower()

        if asaas_env == 'production' or django_env == 'production':
            self.stderr.write(self.style.ERROR(
                "BLOQUEIO DE SEGURANÇA: Este comando de reconciliação manual de homologação é proibido em PRODUÇÃO."
            ))
            return

        # 2. PROVAR DATABASE ANTES DE ESCREVER (Exigir PostgreSQL se --apply)
        vendor = connection.vendor
        if apply_changes and vendor != 'postgresql':
            self.stderr.write(self.style.ERROR(
                f"BLOQUEIO DE ARQUITETURA: Reconciliação financeira integrada não pode utilizar SQLite (engine detectado: {vendor}). "
                "Utilize o PostgreSQL canônico do ambiente de homologação."
            ))
            return

        self.stdout.write(f"=== INICIANDO RECONCILIAÇÃO DA RENOVAÇÃO ANUAL ===")
        self.stdout.write(f"Database Engine: {vendor}")
        self.stdout.write(f"Asaas Environment: {asaas_env}")
        self.stdout.write(f"Subscription ID: {sub_id}")
        self.stdout.write(f"Installment ID: {installment_id}")

        # 3. Consultar Assinatura Local
        try:
            sub = BandSubscription.objects.get(id=sub_id)
        except BandSubscription.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"BandSubscription com ID {sub_id} não encontrada no banco."))
            return

        # 4. Consultar Asaas Remotamente
        client = AsaasClient()
        installment_data = client.get_installment(installment_id)
        if not installment_data or not isinstance(installment_data, dict) or installment_data.get('deleted'):
            self.stderr.write(self.style.ERROR(f"Installment {installment_id} não encontrado ou excluído no Asaas."))
            return

        # Validar Customer
        remote_customer = installment_data.get('customer')
        local_customer = sub.gateway_customer_id
        if local_customer and remote_customer != local_customer:
            self.stderr.write(self.style.ERROR(
                f"DIVERGÊNCIA DE CUSTOMER: Sub local possui customer {local_customer}, mas Installment pertence a {remote_customer}."
            ))
            return

        # Validar Quantidade de Parcelas
        remote_inst_count = installment_data.get('installmentCount', 0)
        if remote_inst_count != 5:
            self.stderr.write(self.style.ERROR(
                f"DIVERGÊNCIA DE PARCELAS: Esperado 5x, gateway retornou {remote_inst_count}x."
            ))
            return

        # Consultar Payments Remotos
        payments = client.get_payments_by_installment(installment_id)
        if not payments or len(payments) != 5:
            self.stderr.write(self.style.ERROR(
                f"DIVERGÊNCIA DE PAGAMENTOS: Esperado 5 payments, gateway retornou {len(payments)}."
            ))
            return

        # Validar que todos os 5 payments estão CONFIRMED ou RECEIVED
        confirmed_count = 0
        total_gross = Decimal('0.00')
        total_net = Decimal('0.00')
        sorted_payments = sorted(payments, key=lambda x: x.get('installmentNumber', 0))

        approved_statuses = {'CONFIRMED', 'RECEIVED'}
        earliest_payment_date = None

        for p in sorted_payments:
            p_val = Decimal(str(p.get('value', '0.00')))
            p_net = Decimal(str(p.get('netValue', '0.00'))) if p.get('netValue') is not None else None
            p_status = p.get('status')
            total_gross += p_val
            if p_net:
                total_net += p_net

            if p_status in approved_statuses:
                confirmed_count += 1

            p_date_str = p.get('confirmedDate') or p.get('clientPaymentDate') or p.get('paymentDate') or p.get('dateCreated')
            if p_date_str and not earliest_payment_date:
                try:
                    earliest_payment_date = datetime.date.fromisoformat(p_date_str)
                except ValueError:
                    pass

        self.stdout.write(f"\n--- AUDITORIA REMOTA (ASAAS SANDBOX) ---")
        self.stdout.write(f"Customer: {remote_customer}")
        self.stdout.write(f"Installment Count: {remote_inst_count}")
        self.stdout.write(f"Gross Total: R$ {total_gross:.2f}")
        self.stdout.write(f"Net Total: R$ {total_net:.2f}")
        self.stdout.write(f"Payments Aprovados: {confirmed_count}/5")

        if confirmed_count != 5:
            self.stderr.write(self.style.ERROR(
                f"BLOQUEIO: Apenas {confirmed_count}/5 pagamentos estão confirmados. Reconciliação cancelada."
            ))
            return

        if total_gross != Decimal('239.90'):
            self.stderr.write(self.style.ERROR(
                f"BLOQUEIO: Valor total bruto (R$ {total_gross:.2f}) diverge do esperado (R$ 239.90)."
            ))
            return

        # Datas de Vigência
        try:
            renewal_target_date = datetime.date.fromisoformat(renewal_date_str)
        except ValueError:
            self.stderr.write(self.style.ERROR(f"Data de renovação inválida: {renewal_date_str}"))
            return

        cov_start = renewal_target_date
        # Adicionar 1 ano
        try:
            cov_end = cov_start.replace(year=cov_start.year + 1)
        except ValueError:
            cov_end = cov_start + datetime.timedelta(days=365)

        ext_ref = f"bp-annual-renewal-{sub.id}-{renewal_target_date.strftime('%Y%m%d')}"

        self.stdout.write(f"\n--- PLANO DE RECONCILIAÇÃO ---")
        self.stdout.write(f"1. AnnualRenewalNotice: renewal_date={renewal_target_date}, notified_price=R$ {total_gross:.2f}, status=SKIPPED (Motivo: HOMOLOGACAO_CONSOLE_EMAIL_NAO_ENTREGUE)")
        self.stdout.write(f"2. AnnualPlanPurchase: type=RENEWAL, gross=R$ {total_gross:.2f}, net=R$ {total_net:.2f}, installments=5x, coverage={cov_start} -> {cov_end}, ext_ref={ext_ref}")
        self.stdout.write(f"3. BillingRecords: 5 parcelas de R$ 47.98 com status PAGO vinculadas à AnnualPlanPurchase RENEWAL")
        self.stdout.write(f"4. BandSubscription: next_due_date={cov_end}, contracted_value=R$ {total_gross:.2f}, auto_renew=True")
        self.stdout.write(f"5. SystemSettings: plan_basic_annual = R$ 239.90")

        if dry_run:
            self.stdout.write(self.style.SUCCESS("\n[DRY-RUN CONCLUÍDO] Nenhuma alteração foi gravada no banco de dados."))
            return

        # 5. APLICAR RECONCILIAÇÃO EM TRANSAÇÃO ATÔMICA
        self.stdout.write(self.style.WARNING("\nAplicando alterações no banco de dados..."))
        with transaction.atomic():
            # A) SystemSettings
            sys_settings = SystemSettings.get_settings()
            if sys_settings.plan_basic_annual != Decimal('239.90'):
                old_p = sys_settings.plan_basic_annual
                sys_settings.plan_basic_annual = Decimal('239.90')
                sys_settings.save()
                self.stdout.write(f"SystemSettings: plan_basic_annual atualizado de {old_p} para 239.90.")

            # B) AnnualRenewalNotice (Registrar histórico verdadeiro: SKIPPED)
            notice, n_created = AnnualRenewalNotice.objects.get_or_create(
                band_subscription=sub,
                renewal_date=renewal_target_date,
                defaults={
                    'plan_name': sub.plan_name,
                    'billing_cycle': 'ANUAL',
                    'current_contracted_value': Decimal('199.90'),
                    'notified_renewal_price': Decimal('239.90'),
                    'installment_count': 5,
                    'notice_type': AnnualRenewalNotice.NoticeType.PRICE_CHANGE,
                    'scheduled_for': renewal_target_date - datetime.timedelta(days=30),
                    'status': AnnualRenewalNotice.Status.SKIPPED,
                    'error_message': 'HOMOLOGACAO_CONSOLE_EMAIL_NAO_ENTREGUE',
                }
            )
            if not n_created and notice.status != AnnualRenewalNotice.Status.SKIPPED:
                notice.status = AnnualRenewalNotice.Status.SKIPPED
                notice.error_message = 'HOMOLOGACAO_CONSOLE_EMAIL_NAO_ENTREGUE'
                notice.save(update_fields=['status', 'error_message', 'updated_at'])
            self.stdout.write(f"AnnualRenewalNotice ID={notice.id} registrado com status={notice.status}.")

            # C) AnnualPlanPurchase (RENEWAL)
            approved_dt = timezone.now()
            if earliest_payment_date:
                approved_dt = timezone.make_aware(
                    datetime.datetime.combine(earliest_payment_date, datetime.time(12, 0, 0))
                )

            purchase, p_created = AnnualPlanPurchase.objects.get_or_create(
                band_subscription=sub,
                gateway_installment_id=installment_id,
                purchase_type=AnnualPlanPurchase.PurchaseType.RENEWAL,
                defaults={
                    'gateway_provider': 'ASAAS',
                    'gateway_external_reference': ext_ref,
                    'installment_count': 5,
                    'gross_amount': total_gross,
                    'net_amount': total_net,
                    'coverage_start': cov_start,
                    'coverage_end': cov_end,
                    'approved_at': approved_dt,
                    'status': AnnualPlanPurchase.Status.CONFIRMED,
                }
            )
            if not p_created:
                purchase.status = AnnualPlanPurchase.Status.CONFIRMED
                purchase.gross_amount = total_gross
                purchase.net_amount = total_net
                purchase.coverage_start = cov_start
                purchase.coverage_end = cov_end
                purchase.approved_at = approved_dt
                purchase.save()
            self.stdout.write(f"AnnualPlanPurchase ID={purchase.id} (RENEWAL) persistida com sucesso.")

            # D) BillingRecords (5 parcelas)
            month_names = {
                1: 'Janeiro', 2: 'Fevereiro', 3: 'Marco', 4: 'Abril',
                5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
                9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
            }

            created_records_count = 0
            for p in sorted_payments:
                p_id = p.get('id')
                p_num = p.get('installmentNumber')
                p_val = Decimal(str(p.get('value', '0.00')))
                p_due_str = p.get('dueDate')
                p_due = datetime.date.fromisoformat(p_due_str) if p_due_str else cov_start
                p_paid_str = p.get('confirmedDate') or p.get('clientPaymentDate') or p.get('paymentDate')
                p_paid = datetime.date.fromisoformat(p_paid_str) if p_paid_str else earliest_payment_date
                ref_period = f"{month_names[p_due.month]}/{p_due.year}"

                record, r_created = BillingRecord.objects.get_or_create(
                    gateway_provider='ASAAS',
                    gateway_payment_id=p_id,
                    defaults={
                        'subscription': sub,
                        'band': sub.band,
                        'annual_purchase': purchase,
                        'installment_number': p_num,
                        'reference_period': ref_period,
                        'plan_name': sub.plan_name,
                        'billing_cycle': 'ANUAL',
                        'amount': p_val,
                        'due_date': p_due,
                        'paid_date': p_paid,
                        'status': 'PAGO',
                        'payment_method': 'CARTAO',
                        'gateway_event_status': 'RECONCILIADO_MANUALMENTE',
                    }
                )
                if not r_created:
                    record.annual_purchase = purchase
                    record.installment_number = p_num
                    record.status = 'PAGO'
                    record.payment_method = 'CARTAO'
                    record.gateway_event_status = 'RECONCILIADO_MANUALMENTE'
                    record.save()
                created_records_count += 1
                self.stdout.write(f"  BillingRecord #{p_num} (Payment: {p_id}) reconciliado: R$ {p_val:.2f}, status=PAGO.")

            # E) BandSubscription
            sub.next_due_date = cov_end
            sub.contracted_value = total_gross
            sub.auto_renew = True
            sub.cancel_at_period_end = False
            sub.status = 'ATIVO'
            sub.save(update_fields=['next_due_date', 'contracted_value', 'auto_renew', 'cancel_at_period_end', 'status', 'updated_at'])
            self.stdout.write(f"BandSubscription ID={sub.id} atualizada com sucesso! Nova next_due_date: {sub.next_due_date}, contracted_value: {sub.contracted_value}")

        self.stdout.write(self.style.SUCCESS("\n[RECONCILIAÇÃO CONCLUÍDA COM SUCESSO]"))
