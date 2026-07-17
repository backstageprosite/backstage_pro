from django.core.management.base import BaseCommand, CommandError
from core.services.web_push_operations import reconcile_stale_sending_deliveries

class Command(BaseCommand):
    help = 'Reconcilia envios Web Push parados no status SENDING de forma segura.'

    def add_arguments(self, parser):
        parser.add_argument('--stale-minutes', type=int, default=15, help='Minutos para considerar SENDING abandonada (default: 15)')
        parser.add_argument('--limit', type=int, default=100, help='Limite máximo de atualizações no lote (default: 100)')
        parser.add_argument('--execute', action='store_true', help='Realiza as atualizações. Sem essa flag, roda em DRY-RUN.')
        parser.add_argument('--band-slug', type=str, help='Filtrar candidatas por banda específica')

    def handle(self, *args, **options):
        stale_minutes = options['stale_minutes']
        limit = options['limit']
        execute = options['execute']
        band_slug = options['band_slug']
        
        try:
            result = reconcile_stale_sending_deliveries(
                stale_minutes=stale_minutes,
                limit=limit,
                execute=execute,
                band_slug=band_slug
            )
        except ValueError as e:
            raise CommandError(str(e))
            
        if result['dry_run']:
            self.stdout.write("=== MODO DRY-RUN ===")
            self.stdout.write("Nenhuma alteração realizada no banco de dados.")
        else:
            self.stdout.write("=== EXECUÇÃO REAL ===")
            
        self.stdout.write(f"Quantidade de candidatas encontradas: {result['found_count']}")
        
        if result['dry_run']:
            self.stdout.write(f"Quantidade que seria reconciliada: {result['found_count']} (limitado a {limit})")
        else:
            self.stdout.write(f"Quantidade reconciliada com sucesso: {result['reconciled_count']}")
            
        self.stdout.write(f"IDs envolvidos: {result['ids']}")
