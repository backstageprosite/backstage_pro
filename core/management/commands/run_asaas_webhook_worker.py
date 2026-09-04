import logging
import signal
import sys
import time
from datetime import timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction, connection
from django.utils import timezone
from core.models import PaymentWebhookEvent
from core.services.payments.asaas.webhooks import process_webhook_event

logger = logging.getLogger('asaas_worker')


class Command(BaseCommand):
    help = 'Executa o worker daemon continuo para processamento de webhooks do Asaas na Railway.'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.running = True
        self.error_backoff = {}  # {event_id: next_retry_timestamp}

    def add_arguments(self, parser):
        parser.add_argument(
            '--poll-interval',
            type=float,
            default=2.0,
            help='Intervalo em segundos entre verificacoes de novos eventos (padrao: 2.0s).'
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=25,
            help='Quantidade maxima de eventos capturados por ciclo (padrao: 25).'
        )
        parser.add_argument(
            '--backoff-seconds',
            type=int,
            default=30,
            help='Tempo de cooldown para reprocessar eventos com erro (padrao: 30s).'
        )

    def signal_handler(self, signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        self.stdout.write(self.style.WARNING(f"\n[WORKER] Sinal {sig_name} recebido. Finalizando worker com seguranca..."))
        self.running = False

    def handle(self, *args, **options):
        # Registrar sinais de shutdown gracioso
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        poll_interval = options.get('poll_interval', 2.0)
        batch_size = options.get('batch_size', 25)
        backoff_seconds = options.get('backoff_seconds', 30)

        self.stdout.write(self.style.SUCCESS("=================================================="))
        self.stdout.write(self.style.SUCCESS("  BACKSTAGE PRO — ASAAS WEBHOOK WORKER INICIADO   "))
        self.stdout.write(self.style.SUCCESS("=================================================="))
        self.stdout.write(f"Intervalo de polling: {poll_interval}s | Batch size: {batch_size} | Backoff: {backoff_seconds}s")
        self.stdout.write("Aguardando eventos pendentes...\n")

        while self.running:
            try:
                processed_any = self._process_batch(batch_size, backoff_seconds)
                if not processed_any and self.running:
                    time.sleep(poll_interval)
            except Exception as e:
                logger.exception("[WORKER] Erro inesperado no loop principal: %s", str(e))
                self.stdout.write(self.style.ERROR(f"[WORKER] Erro inesperado no loop: {str(e)}"))
                if self.running:
                    time.sleep(poll_interval)

        self.stdout.write(self.style.SUCCESS("[WORKER] Encerrado com sucesso."))

    def _process_batch(self, batch_size: int, backoff_seconds: int) -> bool:
        now_ts = time.time()
        # Limpar entradas antigas de backoff
        self.error_backoff = {
            eid: retry_ts for eid, retry_ts in self.error_backoff.items()
            if retry_ts > now_ts
        }
        excluded_ids = list(self.error_backoff.keys())

        # Selecionar IDs de eventos candidatos (sem bloquear ainda a tabela inteira)
        qs = PaymentWebhookEvent.objects.filter(
            provider='ASAAS',
            processed=False
        )
        if excluded_ids:
            qs = qs.exclude(gateway_event_id__in=excluded_ids)

        candidate_ids = list(qs.order_by('created_at').values_list('id', flat=True)[:batch_size])
        if not candidate_ids:
            return False

        has_processed_anything = False

        # Processar cada evento em uma transacao atomica isolada com SKIP LOCKED
        for ev_id in candidate_ids:
            if not self.running:
                break

            with transaction.atomic():
                # Concorrência segura: select_for_update(skip_locked=True)
                # Se outro worker estiver processando, este evento sera ignorado por este worker
                locked_event = PaymentWebhookEvent.objects.select_for_update(skip_locked=True).filter(
                    id=ev_id,
                    processed=False
                ).first()

                if not locked_event:
                    continue

                event_id_str = locked_event.gateway_event_id
                event_type_str = locked_event.event_type

                self.stdout.write(f"[WORKER] Processando evento {event_id_str} ({event_type_str})...")

                try:
                    success, msg = process_webhook_event(locked_event)
                    has_processed_anything = True

                    if success:
                        self.stdout.write(self.style.SUCCESS(f"[WORKER] [OK] {event_id_str} ({event_type_str}): {msg}"))
                        if event_id_str in self.error_backoff:
                            del self.error_backoff[event_id_str]
                    else:
                        self.stdout.write(self.style.ERROR(f"[WORKER] [FALHA] {event_id_str} ({event_type_str}): {msg}"))
                        self.error_backoff[event_id_str] = time.time() + backoff_seconds
                except Exception as ex:
                    logger.exception("[WORKER] Excecao ao processar %s: %s", event_id_str, str(ex))
                    self.stdout.write(self.style.ERROR(f"[WORKER] [EXCECAO] {event_id_str}: {str(ex)}"))
                    self.error_backoff[event_id_str] = time.time() + backoff_seconds

        return has_processed_anything
