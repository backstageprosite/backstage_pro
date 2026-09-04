import logging
from django.core.management.base import BaseCommand
from core.models import PaymentWebhookEvent
from core.services.payments.base import extract_asaas_id

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Inspeciona eventos de Webhooks do Asaas persistidos na base de dados de forma sanitizada e segura.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Numero maximo de eventos a serem listados (padrao: 50).'
        )

    def handle(self, *args, **options):
        limit = options.get('limit', 50)
        events = PaymentWebhookEvent.objects.filter(provider='ASAAS').order_by('-created_at')[:limit]

        total = events.count()
        if total == 0:
            self.stdout.write(self.style.NOTICE('Nenhum evento Asaas encontrado na base de dados.'))
            return

        self.stdout.write(self.style.SUCCESS(f'Exibindo {total} evento(s) Asaas mais recente(s):'))
        self.stdout.write('--------------------------------------------------------------------------------')

        for evt in events:
            payload = evt.payload if isinstance(evt.payload, dict) else {}
            
            # Extração segura de identificadores sem expor dados sensíveis
            chk_data = payload.get('checkout') if isinstance(payload.get('checkout'), dict) else {}
            sub_data = payload.get('subscription') if isinstance(payload.get('subscription'), dict) else {}
            pay_data = payload.get('payment') if isinstance(payload.get('payment'), dict) else {}

            checkout_id = extract_asaas_id(chk_data.get('id') or payload.get('checkoutId') or (payload.get('id') if evt.event_type.startswith('CHECKOUT_') else None))
            sub_id = extract_asaas_id(sub_data.get('id') or payload.get('subscriptionId') or payload.get('subscription') or (pay_data.get('subscription') if isinstance(pay_data, dict) else None), expected_prefix='sub_')
            pay_id = extract_asaas_id(pay_data.get('id') or payload.get('paymentId') or (payload.get('id') if evt.event_type.startswith('PAYMENT_') else None), expected_prefix='pay_')
            ext_ref = chk_data.get('externalReference') or sub_data.get('externalReference') or pay_data.get('externalReference') or payload.get('externalReference')

            created_str = evt.created_at.strftime('%Y-%m-%d %H:%M:%S') if evt.created_at else 'N/A'
            status_style = self.style.SUCCESS('SIM') if evt.processed else self.style.WARNING('NAO')

            self.stdout.write(f'ID do Evento:     {evt.gateway_event_id}')
            self.stdout.write(f'Tipo de Evento:   {evt.event_type}')
            self.stdout.write(f'Processado:       {status_style}')
            self.stdout.write(f'Recebido em:      {created_str}')
            if checkout_id:
                self.stdout.write(f'checkout.id:      {checkout_id}')
            if sub_id:
                self.stdout.write(f'subscription.id:  {sub_id}')
            if pay_id:
                self.stdout.write(f'payment.id:       {pay_id}')
            if ext_ref:
                self.stdout.write(f'externalRef:      {ext_ref}')
            if evt.error_message:
                self.stdout.write(self.style.ERROR(f'Erro:             {evt.error_message}'))
            self.stdout.write('--------------------------------------------------------------------------------')
