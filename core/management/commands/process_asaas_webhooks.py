import logging
from django.core.management.base import BaseCommand
from django.db import transaction
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

        for event_item in pending_events:
            with transaction.atomic():
                locked_event = PaymentWebhookEvent.objects.select_for_update(skip_locked=True).filter(
                    id=event_item.id,
                    processed=False
                ).first()

                if not locked_event:
                    self.stdout.write(self.style.WARNING(f'-> Evento {event_item.gateway_event_id} ja em processamento ou concluido por outro worker. Ignorando.'))
                    continue

                self.stdout.write(f'-> Processando evento {locked_event.gateway_event_id} ({locked_event.event_type})...')
                success, msg = process_webhook_event(locked_event)
                if success:
                    success_count += 1
                    self.stdout.write(self.style.SUCCESS(f'   [OK] {locked_event.gateway_event_id}: {msg}'))
                else:
                    error_count += 1
                    self.stdout.write(self.style.ERROR(f'   [ERRO] {locked_event.gateway_event_id}: {msg}'))

        self.stdout.write(
            self.style.SUCCESS(
                f'Processamento concluido: {success_count} sucesso(s), {error_count} erro(s) de {total} total.'
            )
        )
