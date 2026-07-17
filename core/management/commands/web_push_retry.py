import json
from django.core.management.base import BaseCommand, CommandError
from core.services.web_push_operations import retry_web_push_deliveries

class Command(BaseCommand):
    help = 'Recupera manual e controladamente envios Web Push pendentes ou falhos temporariamente.'

    def add_arguments(self, parser):
        parser.add_argument('--band-slug', type=str, required=True, help='Banda selecionada (obrigatório)')
        parser.add_argument('--status', type=str, default='both', choices=['pending', 'temporary-failure', 'both'], help='Status das deliveries para recuperar (default: both)')
        parser.add_argument('--retry-after-minutes', type=int, default=15, help='Intervalo mínimo em minutos (default: 15)')
        parser.add_argument('--max-attempts', type=int, default=3, help='Limite máximo de tentativas (default: 3)')
        parser.add_argument('--limit', type=int, default=50, help='Limite máximo de atualizações no lote (default: 50)')
        parser.add_argument('--execute', action='store_true', help='Realiza as atualizações. Sem essa flag, roda em DRY-RUN.')
        parser.add_argument('--json', action='store_true', help='Retornar saída estruturada em JSON (silencia stdout amigável).')

    def handle(self, *args, **options):
        band_slug = options['band_slug']
        status_filter = options['status']
        retry_after_minutes = options['retry_after_minutes']
        max_attempts = options['max_attempts']
        limit = options['limit']
        execute = options['execute']
        use_json = options['json']
        
        try:
            result = retry_web_push_deliveries(
                band_slug=band_slug,
                status_filter=status_filter,
                retry_after_minutes=retry_after_minutes,
                max_attempts=max_attempts,
                limit=limit,
                execute=execute
            )
        except ValueError as e:
            raise CommandError(str(e))
            
        if use_json:
            self.stdout.write(json.dumps(result, ensure_ascii=False))
            return
            
        summary = result["summary"]
        
        if summary["mode"] == "DRY-RUN":
            self.stdout.write("=== MODO DRY-RUN ===")
            self.stdout.write("Nenhum envio foi realizado.")
            self.stdout.write("Nenhuma alteração foi feita.")
        else:
            self.stdout.write("=== EXECUÇÃO REAL ===")
            
        self.stdout.write(f"Banda: {band_slug}")
        self.stdout.write(f"Status selecionado: {status_filter}")
        self.stdout.write(f"Intervalo mínimo: {retry_after_minutes} minutos")
        self.stdout.write(f"Máximo de tentativas: {max_attempts}")
        self.stdout.write(f"Limite: {limit}")
        self.stdout.write("---")
        self.stdout.write(f"Candidatas encontradas: {summary['candidates']}")
        self.stdout.write(f"Tentadas: {summary['attempted']}")
        self.stdout.write(f"Enviadas: {summary['sent']}")
        self.stdout.write(f"Falhas temporárias: {summary['temporary_failure']}")
        self.stdout.write(f"Falhas permanentes: {summary['permanent_failure']}")
        self.stdout.write(f"Ignoradas (claim normal): {summary['skipped']}")
        self.stdout.write(f"Concorrência / Inativas (skipped_concurrent): {summary['skipped_concurrent']}")
        self.stdout.write(f"Erros inesperados: {summary['unexpected_error']}")
        
        if summary["processed_ids"]:
            self.stdout.write("---")
            self.stdout.write(f"IDs envolvidos: {summary['processed_ids']}")
