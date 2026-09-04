import time
import logging
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from core.models import EmailDelivery, AnnualRenewalNotice
from core.services.email_service import render_and_send_email_delivery

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Worker dedicado para processamento e entrega de e-mails transacionais (EmailDelivery) via SMTP."

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Executa apenas um ciclo de processamento da fila e encerra.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=20,
            help='Número máximo de e-mails processados por lote (padrão: 20).',
        )
        parser.add_argument(
            '--poll-interval',
            type=int,
            default=2,
            help='Intervalo em segundos entre ciclos de polling quando a fila estiver ociosa (padrão: 2s).',
        )

    def handle(self, *args, **options):
        once = options.get('once', False)
        batch_size = options.get('batch_size', 20)
        poll_interval = options.get('poll_interval', 2)

        self.stdout.write(self.style.SUCCESS(
            f"Iniciando worker dedicado de e-mails (EmailDelivery) [batch_size={batch_size}, once={once}]..."
        ))

        while True:
            try:
                # 1. Recuperar itens em 'PROCESSING' há mais de 15 minutos (Stale Recovery)
                self._recover_stale_processing()

                # 2. Processar lote de entregas pendentes / retry
                processed_count = self._process_batch(batch_size)

                if once:
                    self.stdout.write(self.style.SUCCESS(f"Ciclo finalizado (--once). E-mails processados: {processed_count}."))
                    break

                if processed_count == 0:
                    time.sleep(poll_interval)

            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Worker de e-mails interrompido pelo usuário."))
                break
            except Exception as e:
                logger.exception("Erro inesperado no loop principal do worker de e-mails: %s", e)
                self.stdout.write(self.style.ERROR(f"Erro inesperado no loop do worker: {e}"))
                if once:
                    break
                time.sleep(poll_interval)

    def _recover_stale_processing(self):
        """Reclassifica e-mails travados em PROCESSING há mais de 15 minutos de volta para RETRY."""
        stale_threshold = timezone.now() - timedelta(minutes=15)
        stale_items = EmailDelivery.objects.filter(
            status=EmailDelivery.Status.PROCESSING,
            sending_started_at__lt=stale_threshold
        )
        for item in stale_items:
            logger.warning(
                "Recuperando item de e-mail travado (ID=%s, tipo=%s, iniciado_em=%s).",
                item.id, item.email_type, item.sending_started_at
            )
            item.status = EmailDelivery.Status.RETRY
            item.last_error_code = "STALE_PROCESSING_RECOVERED"
            item.last_error_message = f"STALE_PROCESSING_RECOVERED: Envio travado detectado após 15 minutos (iniciado em {item.sending_started_at})"
            item.next_attempt_at = timezone.now() + timedelta(minutes=1)
            item.save(update_fields=['status', 'last_error_code', 'last_error_message', 'next_attempt_at', 'updated_at'])

    def _process_batch(self, batch_size: int) -> int:
        """
        Reivindica atomicamente e-mails elegíveis para envio usando SELECT FOR UPDATE SKIP LOCKED,
        executa o envio SMTP fora da transação de reivindicação, e atualiza o status de cada item.
        """
        now = timezone.now()

        # Reivindicação atômica de IDs
        claimed_ids = []
        with transaction.atomic():
            eligible_qs = EmailDelivery.objects.select_for_update(skip_locked=True).filter(
                status__in=[EmailDelivery.Status.PENDING, EmailDelivery.Status.RETRY]
            ).filter(
                next_attempt_at__isnull=True
            ) | EmailDelivery.objects.select_for_update(skip_locked=True).filter(
                status__in=[EmailDelivery.Status.PENDING, EmailDelivery.Status.RETRY],
                next_attempt_at__lte=now
            )
            eligible_batch = list(eligible_qs.order_by('created_at')[:batch_size])

            for delivery in eligible_batch:
                delivery.status = EmailDelivery.Status.PROCESSING
                delivery.sending_started_at = now
                delivery.attempt_count += 1
                delivery.save(update_fields=['status', 'sending_started_at', 'attempt_count', 'updated_at'])
                claimed_ids.append(delivery.id)

        if not claimed_ids:
            return 0

        self.stdout.write(f"Worker reivindicou {len(claimed_ids)} e-mail(s) para entrega.")

        # Processamento fora da transação de banco de dados
        processed_count = 0
        for delivery_id in claimed_ids:
            try:
                delivery = EmailDelivery.objects.get(id=delivery_id)
            except EmailDelivery.DoesNotExist:
                continue

            success, err_code, err_msg = render_and_send_email_delivery(delivery)
            self._handle_delivery_result(delivery, success, err_code, err_msg)
            processed_count += 1

        return processed_count

    def _handle_delivery_result(self, delivery: EmailDelivery, success: bool, err_code: str, err_msg: str):
        """Atualiza o resultado final de entrega e reflete em objetos relacionados (ex: AnnualRenewalNotice)."""
        now = timezone.now()

        if success:
            delivery.status = EmailDelivery.Status.SENT
            delivery.sent_at = now
            delivery.last_error_code = ""
            delivery.last_error_message = ""
            delivery.save(update_fields=['status', 'sent_at', 'last_error_code', 'last_error_message', 'updated_at'])
            self.stdout.write(self.style.SUCCESS(
                f"  [SENT] ID={delivery.id} ({delivery.email_type}) -> {delivery.recipient_email} [MsgId: {delivery.message_id}]"
            ))

            # Atualizar AnnualRenewalNotice se vinculado
            if delivery.related_object_type == 'AnnualRenewalNotice' and delivery.related_object_id:
                try:
                    notice = AnnualRenewalNotice.objects.get(id=int(delivery.related_object_id))
                    notice.status = AnnualRenewalNotice.Status.SENT
                    notice.sent_at = now
                    notice.error_message = ""
                    notice.save(update_fields=['status', 'sent_at', 'error_message', 'updated_at'])
                except (AnnualRenewalNotice.DoesNotExist, ValueError):
                    pass

        else:
            # Avaliar retry vs failed
            max_attempts = delivery.max_attempts or 6
            clean_err = str(err_msg or '').replace('\n', ' ')[:500]
            clean_code = str(err_code or 'UNKNOWN')[:100]

            if delivery.attempt_count < max_attempts:
                backoff_delay = self._calculate_backoff(delivery.attempt_count)
                delivery.status = EmailDelivery.Status.RETRY
                delivery.last_error_code = clean_code
                delivery.last_error_message = clean_err
                delivery.next_attempt_at = now + backoff_delay
                delivery.save(update_fields=['status', 'last_error_code', 'last_error_message', 'next_attempt_at', 'updated_at'])
                self.stdout.write(self.style.WARNING(
                    f"  [RETRY {delivery.attempt_count}/{max_attempts}] ID={delivery.id} ({delivery.email_type}) -> {delivery.recipient_email}. Próxima tentativa em {backoff_delay}. Erro: {clean_err[:80]}"
                ))
            else:
                delivery.status = EmailDelivery.Status.FAILED
                delivery.last_error_code = clean_code
                delivery.last_error_message = f"MAX_ATTEMPTS_EXCEEDED ({max_attempts}): {clean_err}"
                delivery.save(update_fields=['status', 'last_error_code', 'last_error_message', 'updated_at'])
                self.stdout.write(self.style.ERROR(
                    f"  [FAILED] ID={delivery.id} ({delivery.email_type}) -> {delivery.recipient_email}. Tentativas esgotadas. Erro: {clean_err[:80]}"
                ))

                # Atualizar AnnualRenewalNotice se vinculado
                if delivery.related_object_type == 'AnnualRenewalNotice' and delivery.related_object_id:
                    try:
                        notice = AnnualRenewalNotice.objects.get(id=int(delivery.related_object_id))
                        notice.status = AnnualRenewalNotice.Status.FAILED
                        notice.error_message = f"FALHA_ENTREGA_EMAIL: {clean_err[:200]}"
                        notice.save(update_fields=['status', 'error_message', 'updated_at'])
                    except (AnnualRenewalNotice.DoesNotExist, ValueError):
                        pass

    @staticmethod
    def _calculate_backoff(attempt_count: int) -> timedelta:
        """
        Escala de backoff exponencial:
        Tentativa 1: +1 minuto
        Tentativa 2: +5 minutos
        Tentativa 3: +15 minutos
        Tentativa 4: +1 hora
        Tentativa 5: +6 horas
        """
        delays = {
            1: timedelta(minutes=1),
            2: timedelta(minutes=5),
            3: timedelta(minutes=15),
            4: timedelta(hours=1),
            5: timedelta(hours=6),
        }
        return delays.get(attempt_count, timedelta(hours=6))
