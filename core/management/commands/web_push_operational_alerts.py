import json
from django.core.management.base import BaseCommand, CommandError
from core.models import Band
from core.services.web_push_alerts import plan_web_push_operational_alerts, apply_web_push_operational_alert_plan

class Command(BaseCommand):
    help = 'Executa o motor persistente de alertas operacionais do Web Push.'

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--global', action='store_true', dest='is_global', help='Processa somente visão global')
        group.add_argument('--band-slug', type=str, help='Processa somente a banda especificada')
        group.add_argument('--all-bands', action='store_true', help='Processa todas as bandas existentes separadamente')

        parser.add_argument('--hours', type=int, default=24, help='Janela de análise em horas (1 a 720)')
        parser.add_argument('--stale-pending-minutes', type=int, default=10, help='Tolerância para PENDING (5 a 10080)')
        parser.add_argument('--stale-sending-minutes', type=int, default=15, help='Tolerância para SENDING (5 a 10080)')
        
        parser.add_argument('--execute', action='store_true', help='Persiste as alterações no banco de dados (DRY-RUN por padrão)')
        parser.add_argument('--json', action='store_true', help='Retorna saída estruturada em JSON')

    def handle(self, *args, **options):
        is_global = options['is_global']
        band_slug = options['band_slug']
        all_bands = options['all_bands']
        hours = options['hours']
        stale_pending = options['stale_pending_minutes']
        stale_sending = options['stale_sending_minutes']
        execute = options['execute']
        as_json = options['json']

        if not (1 <= hours <= 720):
            raise CommandError('hours deve estar entre 1 e 720')
        if not (5 <= stale_pending <= 10080):
            raise CommandError('stale-pending-minutes deve estar entre 5 e 10080')
        if not (5 <= stale_sending <= 10080):
            raise CommandError('stale-sending-minutes deve estar entre 5 e 10080')

        scopes = []
        if is_global:
            scopes.append(None)
        elif band_slug:
            if not Band.objects.filter(slug=band_slug).exists():
                raise CommandError(f'Banda com slug {band_slug} não encontrada.')
            scopes.append(band_slug)
        elif all_bands:
            for b in Band.objects.all():
                scopes.append(b.slug)

        total_opened = 0
        total_updated = 0
        total_resolved = 0
        total_unchanged = 0
        total_errors = 0
        
        results_list = []

        for scope in scopes:
            try:
                plan = plan_web_push_operational_alerts(
                    band_slug=scope,
                    window_hours=hours,
                    stale_pending_minutes=stale_pending,
                    stale_sending_minutes=stale_sending
                )
                
                result = apply_web_push_operational_alert_plan(plan, execute=execute)
                
                total_opened += result['opened']
                total_updated += result['updated']
                total_resolved += result['resolved']
                total_unchanged += result['unchanged']
                total_errors += result['errors']
                
                if as_json:
                    results_list.extend(result['results'])
                else:
                    scope_name = f'Banda {scope}' if scope else 'Global'
                    self.stdout.write(f'=== WEB PUSH OPERATIONAL ALERTS — {"EXECUTE" if execute else "DRY-RUN"} ===')
                    self.stdout.write(f'Escopo: {scope_name}')
                    self.stdout.write(f'Janela: {hours} horas')
                    self.stdout.write(f'PENDING stale: {stale_pending} minutos')
                    self.stdout.write(f'SENDING stale: {stale_sending} minutos\n')
                    self.stdout.write(f'Novos incidentes: {result["opened"]}')
                    self.stdout.write(f'Atualizações: {result["updated"]}')
                    self.stdout.write(f'Resoluções: {result["resolved"]}')
                    self.stdout.write(f'Sem alteração: {result["unchanged"]}\n')
                    
                    if execute:
                        self.stdout.write('Alterações foram aplicadas ao banco.\n')
                    else:
                        self.stdout.write('Nenhuma alteração foi realizada.\n')

            except Exception:
                total_errors += 1
                if as_json:
                    results_list.append({'scope': scope, 'error_code': 'scope_processing_failed'})
                else:
                    self.stderr.write(f'Erro ao processar o escopo {scope}.')

        if as_json:
            out = {
                'mode': 'EXECUTE' if execute else 'DRY_RUN',
                'scopes_processed': len(scopes),
                'opened': total_opened,
                'updated': total_updated,
                'resolved': total_resolved,
                'unchanged': total_unchanged,
                'errors': total_errors,
                'results': results_list
            }
            self.stdout.write(json.dumps(out))
