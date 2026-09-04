import logging
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from core.models import SignupOrder, Band, BandSubscription, BillingRecord, BandActivationToken
from core.services.payments.base import AsaasConfig, extract_asaas_id
from core.services.payments.asaas.client import AsaasClient

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Repara de forma segura e controlada o gateway_subscription_id do SignupOrder e da BandSubscription na homologacao.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--order-id',
            type=int,
            default=1,
            help='ID do SignupOrder na homologacao a ser inspecionado/reparado (padrao: 1).'
        )

    def handle(self, *args, **options):
        # 1. Trava estrita de seguranca: Executar exclusivamente em staging + sandbox
        django_env = getattr(settings, 'DJANGO_ENV', '').strip().lower()
        config = AsaasConfig.from_settings()

        if django_env != 'staging' or config.environment != 'sandbox':
            raise CommandError(
                'Este comando so pode ser executado no ambiente de homologacao com Asaas Sandbox.'
            )

        if not config.is_configured():
            raise CommandError('ASAAS_API_KEY nao configurada no ambiente de homologacao.')

        order_id = options.get('order_id', 1)
        order = SignupOrder.objects.filter(pk=order_id).first()
        if not order:
            raise CommandError(f'SignupOrder ID {order_id} nao encontrado.')

        checkout_id = order.gateway_checkout_id
        if not checkout_id:
            raise CommandError(f'SignupOrder ID {order_id} nao possui gateway_checkout_id.')

        # 2. Consultar cobranças do checkout via Asaas
        client = AsaasClient(config=config)
        payments_found = client.get_payments_by_checkout(checkout_id)
        if not payments_found:
            raise CommandError(f'Nenhum pagamento retornado pelo Asaas para checkoutSessionId={checkout_id}')

        if len(payments_found) > 1:
            raise CommandError(f'Multiplos pagamentos encontrados para checkoutSessionId={checkout_id}. Abortando por ambiguidade.')

        payment_data = payments_found[0]
        real_payment_id = extract_asaas_id(payment_data.get('id'), expected_prefix='pay_')
        real_subscription_id = extract_asaas_id(payment_data.get('subscription'), expected_prefix='sub_')
        real_customer_id = extract_asaas_id(payment_data.get('customer'), expected_prefix='cus_')

        if not real_subscription_id:
            raise CommandError('Asaas nao retornou subscription.id escalar valido para a cobranca do checkout.')

        self.stdout.write(self.style.NOTICE(f'Validado no Asaas Sandbox: checkout={checkout_id} -> payment={real_payment_id} -> subscription={real_subscription_id}'))

        # 3. Validar Band e BandSubscription vinculadas
        band = order.band
        if not band:
            raise CommandError(f'SignupOrder ID {order_id} nao possui Band vinculada.')

        subs = BandSubscription.objects.filter(band=band)
        if subs.count() != 1:
            raise CommandError(f'Esperada exatamente 1 BandSubscription para a Band {band.id}, encontradas: {subs.count()}')

        sub = subs.first()

        # 4. Validar BillingRecord
        billings = BillingRecord.objects.filter(subscription=sub)
        if billings.count() != 1:
            raise CommandError(f'Esperado exatamente 1 BillingRecord para a Subscription {sub.id}, encontrados: {billings.count()}')

        billing = billings.first()

        # 5. Executar reparo seguro apenas das referencias incorretas
        old_order_sub_id = order.gateway_subscription_id
        old_band_sub_id = sub.gateway_subscription_id

        order.gateway_subscription_id = real_subscription_id
        order.save(update_fields=['gateway_subscription_id'])

        sub.gateway_subscription_id = real_subscription_id
        if real_customer_id and not sub.gateway_customer_id:
            sub.gateway_customer_id = real_customer_id
        sub.save(update_fields=['gateway_subscription_id', 'gateway_customer_id'] if real_customer_id else ['gateway_subscription_id'])

        if real_payment_id and billing.gateway_payment_id != real_payment_id:
            billing.gateway_payment_id = real_payment_id
            billing.save(update_fields=['gateway_payment_id'])

        # 6. Saída sanitizada
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=================================================='))
        self.stdout.write(self.style.SUCCESS('REPARO ASAAS SANDBOX EXECUTADO COM SUCESSO'))
        self.stdout.write(self.style.SUCCESS('=================================================='))
        self.stdout.write(f'SignupOrder ID:                  {order.id}')
        self.stdout.write(f'SignupOrder status:              {order.status}')
        self.stdout.write(f'Band ID / Slug:                  {band.id} / {band.slug}')
        self.stdout.write(f'BandSubscription ID:             {sub.id}')
        self.stdout.write(f'gateway_subscription_id antigo:  {old_band_sub_id}')
        self.stdout.write(f'gateway_subscription_id novo:    {sub.gateway_subscription_id}')
        self.stdout.write(f'BillingRecord ID:                {billing.id}')
        self.stdout.write(f'BillingRecord gateway_payment_id:{billing.gateway_payment_id}')
        self.stdout.write(f'BillingRecord status:            {billing.status}')
        self.stdout.write(self.style.SUCCESS('=================================================='))
