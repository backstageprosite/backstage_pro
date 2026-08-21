from django.apps import AppConfig


import threading
import datetime


def _run_daily_billing_check():
    """Executa check_subscription_due_dates no inicio do dia e depois a cada 24h."""
    import time
    while True:
        try:
            from django.core.management import call_command
            call_command("check_subscription_due_dates")
        except Exception as e:
            import logging
            logging.getLogger("core.scheduler").error(f"Erro no scheduler: {e}")
        time.sleep(86400)  # 24 horas


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Sistema Backstage Pro'

    def ready(self):
        import core.signals
        # Scheduler diario de varredura de vencimentos
        import os
        if os.environ.get("RUN_MAIN") != "true":  # evita duplicar no reload do dev
            t = threading.Thread(target=_run_daily_billing_check, daemon=True)
            t.start()
