from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import BandNotice
from core.services.notification_services import send_push_notification_to_band
from django.db import transaction

class Command(BaseCommand):
    help = 'Processa os avisos agendados e envia as notificações pendentes.'

    def handle(self, *args, **options):
        now = timezone.now()
        
        # Encontra avisos que já passaram do horário programado e ainda não foram enviados
        notices_to_process = BandNotice.objects.filter(
            scheduled_at__lte=now,
            sent_at__isnull=True
        ).select_for_update(skip_locked=True)
        
        count = 0
        
        with transaction.atomic():
            for notice in notices_to_process:
                # Verificação final de sanidade para idempotência
                if notice.sent_at is not None:
                    continue
                    
                # Dispara a push notification
                # Reutilizando o serviço existente do projeto (ignorando a notificação interna se já for coberta lá, 
                # ou enviando push conforme requisitado)
                try:
                    send_push_notification_to_band(
                        band=notice.band,
                        title='Aviso da Produção',
                        message=notice.message,
                        exclude_user=notice.created_by, # Quem criou o aviso também recebe? Em geral sim, mas usando o padrão do projeto
                        url=f'/dannielvieira/painel/'
                    )
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'Erro ao enviar push para o aviso {notice.id}: {str(e)}'))
                    # Não interrompe o fluxo de outros avisos
                
                # Marca como enviado
                notice.sent_at = timezone.now()
                notice.save(update_fields=['sent_at'])
                count += 1
                
        self.stdout.write(self.style.SUCCESS(f'Foram processados {count} avisos pendentes.'))
