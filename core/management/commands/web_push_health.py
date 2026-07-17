import json
from django.core.management.base import BaseCommand, CommandError
from core.services.web_push_operations import build_web_push_health_snapshot

class Command(BaseCommand):
    help = 'Retorna o diagnóstico operacional (read-only) do Web Push.'

    def add_arguments(self, parser):
        parser.add_argument('--hours', type=int, default=24, help='Janela recente em horas (default: 24)')
        parser.add_argument('--stale-pending-minutes', type=int, default=10, help='Minutos para considerar PENDING antiga (default: 10)')
        parser.add_argument('--stale-sending-minutes', type=int, default=15, help='Minutos para considerar SENDING antiga (default: 15)')
        parser.add_argument('--band-slug', type=str, help='Filtrar por banda específica')
        parser.add_argument('--json', action='store_true', help='Retornar em formato JSON')

    def handle(self, *args, **options):
        hours = options['hours']
        stale_pending = options['stale_pending_minutes']
        stale_sending = options['stale_sending_minutes']
        band_slug = options['band_slug']
        out_json = options['json']
        
        try:
            snapshot = build_web_push_health_snapshot(
                window_hours=hours,
                stale_pending_minutes=stale_pending,
                stale_sending_minutes=stale_sending,
                band_slug=band_slug,
            )
        except ValueError as e:
            raise CommandError(str(e))
            
        if out_json:
            self.stdout.write(json.dumps(snapshot, ensure_ascii=False, indent=2))
        else:
            self.stdout.write("=== Diagnóstico Operacional Web Push ===")
            if band_slug:
                self.stdout.write(f"Filtro de banda: {band_slug}")
            self.stdout.write("")
            self.stdout.write("--- Entregas (Total) ---")
            for k, v in snapshot['deliveries']['total'].items():
                self.stdout.write(f"  {k}: {v}")
                
            self.stdout.write("")
            self.stdout.write(f"--- Entregas (Últimas {hours}h) ---")
            for k, v in snapshot['deliveries']['recent_window'].items():
                self.stdout.write(f"  {k}: {v}")
                
            self.stdout.write("")
            self.stdout.write("--- Taxas ---")
            for k, v in snapshot['deliveries']['rates'].items():
                self.stdout.write(f"  {k}: {v}")
                
            self.stdout.write("")
            self.stdout.write("--- Anomalias ---")
            for k, v in snapshot['anomalies'].items():
                self.stdout.write(f"  {k}: {v}")
                
            self.stdout.write("")
            self.stdout.write("--- Inscrições ---")
            for k, v in snapshot['subscriptions'].items():
                self.stdout.write(f"  {k}: {v}")
                
            self.stdout.write("")
            self.stdout.write("--- Antiguidade (Datas mais antigas e mais recentes) ---")
            for k, v in snapshot['antiquity'].items():
                self.stdout.write(f"  {k}: {v}")
