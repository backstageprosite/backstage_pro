import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import PaymentWebhookEvent
from core.services.payments.asaas.webhooks import process_webhook_event

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Processa eventos pendentes de Webhooks do Asaas persistidos na base de dados.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Numero maximo de eventos a serem processados nesta execucao.'
        )
        parser.add_argument(
            '--event-id',
            type=str,
            help='Processa exclusivamente um evento especifico pelo gateway_event_id.'
        )

    def handle(self, *args, **options):
        event_id = options.get('event_id')
        limit = options.get('limit')

        qs = PaymentWebhookEvent.objects.filter(provider='ASAAS', processed=False)
        if event_id:
            qs = qs.filter(gateway_event_id=event_id)

        pending_events = list(qs.order_by('created_at')[:limit])
        total = len(pending_events)

        if total == 0:
            self.stdout.write(self.style.SUCCESS('Nenhum evento Asaas pendente de processamento.'))
            return

        self.stdout.write(f'Iniciando processamento de {total} evento(s) Asaas pendente(s)...')

        success_count = 0
        error_count = 0

        for event in pending_events:
            self.stdout.write(f'-> Processando evento {event.gateway_event_id} ({event.event_type})...')
            success, msg = process_webhook_event(event)
            if success:
                success_count += 1
                self.stdout.write(self.style.SUCCESS(f'   [OK] {event.gateway_event_id}: {msg}'))
            else:
                error_count += 1
                self.stdout.write(self.style.ERROR(f'   [ERRO] {event.gateway_event_id}: {msg}'))

        self.stdout.write(
            self.style.SUCCESS(
                f'Processamento concluido: {success_count} sucesso(s), {error_count} erro(s) de {total} total.'
            )
        )
