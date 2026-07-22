import json
import uuid
from django.core.management.base import BaseCommand, CommandError
from core.services.web_push_alerts import plan_web_push_operational_alerts, apply_web_push_operational_alert_plan
from core.services.web_push_alert_email import (
    acquire_web_push_operational_alert_cycle_lease,
    release_web_push_operational_alert_cycle_lease,
    plan_web_push_operational_alert_email_deliveries,
    queue_web_push_operational_alert_email_deliveries,
    process_due_web_push_operational_alert_email_deliveries,
    get_web_push_alert_email_config
)
from core.models import Band

class Command(BaseCommand):
    help = 'Executa o ciclo operacional do Web Push (Avaliação, Planejamento, Alertas, E-mail)'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true', help='Executa (default: DRY_RUN)')
        parser.add_argument('--notify-email', action='store_true', help='Planeja e agenda os e-mails (requer --execute)')
        parser.add_argument('--json', action='store_true', help='Saída em JSON estruturado')
        parser.add_argument('--trigger', type=str, default='manual')
        parser.add_argument('--hours', type=int, default=24)
        parser.add_argument('--stale-pending-minutes', type=int, default=10)
        parser.add_argument('--stale-sending-minutes', type=int, default=15)

    def handle(self, *args, **options):
        execute = options['execute']
        notify_email = options['notify_email']
        as_json = options['json']
        trigger = options['trigger'] if options['trigger'] in ['manual', 'scheduled'] else 'manual'
        hours = options['hours']
        stale_pending_minutes = options['stale_pending_minutes']
        stale_sending_minutes = options['stale_sending_minutes']

        if not (1 <= hours <= 720):
            raise CommandError('hours deve estar entre 1 e 720')
        if not (5 <= stale_pending_minutes <= 10080):
            raise CommandError('stale-pending-minutes deve estar entre 5 e 10080')
        if not (5 <= stale_sending_minutes <= 10080):
            raise CommandError('stale-sending-minutes deve estar entre 5 e 10080')

        results = {
            "mode": "EXECUTE" if execute else "DRY_RUN",
            "trigger": trigger,
            "parameters": {
                "hours": hours,
                "stale_pending_minutes": stale_pending_minutes,
                "stale_sending_minutes": stale_sending_minutes
            },
            "notify_email_requested": notify_email,
            "lease_acquired": False,
            "global": None,
            "bands": [],
            "email_planning": None,
            "email_delivery_processing": None,
            "errors": []
        }

        if notify_email and not execute:
            results['errors'].append("notify_email requires execute")
            if as_json: self.stdout.write(json.dumps(results))
            else: self.stderr.write("Erro: --notify-email exige --execute")
            return

        if notify_email:
            try:
                config = get_web_push_alert_email_config()
                if not config['enabled']:
                    results['errors'].append("email channel disabled")
                    if as_json: self.stdout.write(json.dumps(results))
                    else: self.stderr.write("Erro: Canal desabilitado.")
                    return
            except ValueError:
                results['errors'].append("email configuration invalid")
                if as_json: self.stdout.write(json.dumps(results))
                else: self.stderr.write("Erro: Configuração do canal inválida.")
                return

        owner_token = str(uuid.uuid4())
        has_lease = False

        if execute and notify_email:
            has_lease = acquire_web_push_operational_alert_cycle_lease(owner_token)
            results["lease_acquired"] = has_lease
            if not has_lease:
                results['errors'].append("could not acquire lease")
                if as_json: self.stdout.write(json.dumps(results))
                else: self.stderr.write("Alerta: Lease em andamento.")
                return

        try:
            all_transition_events = []

            try:
                g_plan = plan_web_push_operational_alerts(band_slug=None, window_hours=hours, stale_pending_minutes=stale_pending_minutes, stale_sending_minutes=stale_sending_minutes)
                g_res = apply_web_push_operational_alert_plan(g_plan, execute=execute)
                results["global"] = g_res
                if execute: all_transition_events.extend(g_res.get('transition_events', []))
            except Exception:
                results["errors"].append({"scope": "GLOBAL", "error": "unexpected_error"})

            for band in Band.objects.all():
                slug = (band.slug or "").strip()
                if not slug:
                    results["errors"].append({"scope": "BAND", "error": "invalid_band_slug"})
                    continue
                try:
                    b_plan = plan_web_push_operational_alerts(band_slug=slug, window_hours=hours, stale_pending_minutes=stale_pending_minutes, stale_sending_minutes=stale_sending_minutes)
                    b_res = apply_web_push_operational_alert_plan(b_plan, execute=execute)
                    results["bands"].append({"band_slug": slug, "result": b_res})
                    if execute: all_transition_events.extend(b_res.get('transition_events', []))
                except Exception:
                    results["errors"].append({"scope": f"BAND:{slug}", "error": "unexpected_error"})

            if execute and notify_email and all_transition_events:
                try:
                    e_plan = plan_web_push_operational_alert_email_deliveries(all_transition_events)
                    e_queue = queue_web_push_operational_alert_email_deliveries(e_plan, execute=execute)
                    results["email_planning"] = {"plan": e_plan['summary'], "queue": e_queue}
                except Exception:
                    results["errors"].append({"scope": "EMAIL_QUEUEING", "error": "unexpected_error"})

            if execute and notify_email:
                try:
                    p_res = process_due_web_push_operational_alert_email_deliveries(limit=50, execute=True)
                    results["email_delivery_processing"] = p_res
                except Exception:
                    results["errors"].append({"scope": "EMAIL_PROCESSING", "error": "unexpected_error"})

            if as_json: self.stdout.write(json.dumps(results))
            else:
                self.stdout.write(f"Ciclo concluído em modo {results['mode']}.")
                self.stdout.write(f"Janela: {hours} horas.")
                self.stdout.write(f"PENDING stale: {stale_pending_minutes} minutos.")
                self.stdout.write(f"SENDING stale: {stale_sending_minutes} minutos.")

        finally:
            if has_lease:
                release_web_push_operational_alert_cycle_lease(owner_token)
