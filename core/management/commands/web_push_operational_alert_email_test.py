import json
from django.core.management.base import BaseCommand
from core.services.web_push_alert_email import get_web_push_alert_email_config
from django.core.mail import EmailMultiAlternatives

class Command(BaseCommand):
    help = 'Test command for operational alert emails'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true', help='Execute the process')

    def handle(self, *args, **options):
        execute = options['execute']
        
        try:
            config = get_web_push_alert_email_config()
        except ValueError:
            self.stdout.write(json.dumps({"status": "invalid_configuration", "recipient_count": 0}))
            return
            
        if execute:
            subject = "[TEST] Teste de Alerta Web Push"
            text_content = "Este é um email de teste."
            msg = EmailMultiAlternatives(subject, text_content, config['from_email'], config['recipients'])
            try:
                msg.send(fail_silently=False)
                status = "sent"
            except Exception:
                status = "error"
        else:
            status = "dry-run"
            
        result = {
            "status": status,
            "recipient_count": config['recipient_count']
        }
        
        self.stdout.write(json.dumps(result))

