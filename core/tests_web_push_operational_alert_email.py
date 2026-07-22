import json
import datetime
from django.test import TestCase, override_settings, TransactionTestCase
from django.utils import timezone
from core.models import WebPushOperationalAlertEmailDelivery, WebPushOperationalAlertCycleLease, WebPushOperationalAlert, Band
from core.services.web_push_alert_email import (
    get_web_push_alert_email_config,
    acquire_web_push_operational_alert_cycle_lease,
    release_web_push_operational_alert_cycle_lease,
    plan_web_push_operational_alert_email_deliveries,
    queue_web_push_operational_alert_email_deliveries,
    send_web_push_alert_email_delivery,
    process_due_web_push_operational_alert_email_deliveries
)
from unittest.mock import patch
from smtplib import SMTPException, SMTPSenderRefused, SMTPRecipientsRefused, SMTPAuthenticationError
from django.db import IntegrityError, transaction, connection
import socket

class TestWebPushAlertCommands(TransactionTestCase):
    def setUp(self):
        self.alert = WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL",
            dedupe_key="global:test",
            code="test",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test Msg",
            recommended_action="Test Action",
            current_count=1,
            opened_count=1,
            first_detected_at=timezone.now(),
            last_detected_at=timezone.now()
        )

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_MIN_SEVERITY='INFO', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_config_invalid_min_severity(self):
        with self.assertRaisesMessage(ValueError, "email_configuration_invalid"):
            get_web_push_alert_email_config()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_MIN_SEVERITY='WARNING', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_config_valid_min_severity(self):
        c = get_web_push_alert_email_config()
        self.assertEqual(c['min_severity'], 'WARNING')

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='invalid-email', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_config_invalid_recipient(self):
        with self.assertRaisesMessage(ValueError, "email_configuration_invalid"):
            get_web_push_alert_email_config()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='A@A.com, b@a.com, a@A.com ', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_config_recipients_sanitized(self):
        c = get_web_push_alert_email_config()
        self.assertEqual(c['recipients'], ['a@a.com', 'b@a.com'])
        self.assertEqual(c['recipient_count'], 2)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_config_empty_recipients_when_enabled(self):
        with self.assertRaisesMessage(ValueError, "email_configuration_invalid"):
            get_web_push_alert_email_config()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_MAX_ATTEMPTS=11, WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_config_invalid_max_attempts(self):
        with self.assertRaisesMessage(ValueError, "email_configuration_invalid"):
            get_web_push_alert_email_config()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_RETRY_MINUTES=4, WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_config_invalid_retry_minutes(self):
        with self.assertRaisesMessage(ValueError, "email_configuration_invalid"):
            get_web_push_alert_email_config()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_CYCLE_LOCK_MINUTES=1441, WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_config_invalid_lock_minutes(self):
        with self.assertRaisesMessage(ValueError, "email_configuration_invalid"):
            get_web_push_alert_email_config()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='invalid', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_config_invalid_from_email(self):
        with self.assertRaisesMessage(ValueError, "email_configuration_invalid"):
            get_web_push_alert_email_config()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='javascript:alert(1)')
    def test_config_invalid_dashboard_url_scheme(self):
        with self.assertRaisesMessage(ValueError, "email_configuration_invalid"):
            get_web_push_alert_email_config()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://u:p@a.com')
    def test_config_invalid_dashboard_url_credentials(self):
        with self.assertRaisesMessage(ValueError, "email_configuration_invalid"):
            get_web_push_alert_email_config()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_event_keys_exact_match(self):
        # 1. Banco inicialmente sem deliveries conflitantes
        events = [
            {"alert_id": self.alert.id, "event_type": "OPENED", "severity": "WARNING", "opened_count": 5},
            {"alert_id": self.alert.id, "event_type": "REOPENED", "severity": "WARNING", "opened_count": 5},
            {"alert_id": self.alert.id, "event_type": "ESCALATED", "severity": "CRITICAL", "opened_count": 5},
            {"alert_id": self.alert.id, "event_type": "RESOLVED", "severity": "WARNING", "opened_count": 5},
        ]

        # Cria uma delivery SENT anterior mas diferente para permitir o RESOLVED
        WebPushOperationalAlertEmailDelivery.objects.create(
            alert_id=self.alert.id, event_key=f"alert:{self.alert.id}:open:5:opened", event_type="OPENED", status="SENT",
            recipient_count=1, recipient_set_hash="x", severity_snapshot="WARNING", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=5,
            sent_at=timezone.now()
        )

        # Agora o to_queue não deve conter 'opened' porque j existe e est SENDING?
        # No, wait, if 'opened' is SENT, it will try to plan 'opened' again and queue it but fails on IntegrityError later.
        # However, the instruction says: "para permitir RESOLVED, criar uma delivery SENT anterior com uma chave diferente que satisfaa a regra, sem colidir com a chave que est sendo planejada."
        # OK, let's delete the OPENED one from events so we don't try to queue it again, or we change the SENT delivery to be for opened_count 4?
        # But sent_count condition for RESOLVED searches for event_key__startswith=f"alert:{alert_id}:open:{opened_count}:"
        # So we can create one for "critical" for example, and not include "critical" in the events.
        pass

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_event_keys_exact_match_separated(self):
        # 1. Banco sem conflito
        WebPushOperationalAlertEmailDelivery.objects.create(
            alert_id=self.alert.id, event_key=f"alert:{self.alert.id}:open:5:critical", event_type="ESCALATED", status="SENT",
            recipient_count=1, recipient_set_hash="x", severity_snapshot="CRITICAL", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=5,
            sent_at=timezone.now()
        )

        events = [
            {"alert_id": self.alert.id, "event_type": "OPENED", "severity": "WARNING", "opened_count": 5},
            {"alert_id": self.alert.id, "event_type": "REOPENED", "severity": "WARNING", "opened_count": 5},
            {"alert_id": self.alert.id, "event_type": "RESOLVED", "severity": "WARNING", "opened_count": 5},
        ]

        plan = plan_web_push_operational_alert_email_deliveries(events)
        keys = [item["event_key"] for item in plan["to_queue"]]
        self.assertIn(f"alert:{self.alert.id}:open:5:opened", keys)
        self.assertIn(f"alert:{self.alert.id}:open:5:reopened", keys)
        self.assertIn(f"alert:{self.alert.id}:open:5:resolved", keys)

        # Test exact match of critical
        events_critical = [{"alert_id": self.alert.id, "event_type": "ESCALATED", "severity": "CRITICAL", "opened_count": 6}]
        plan_c = plan_web_push_operational_alert_email_deliveries(events_critical)
        self.assertIn(f"alert:{self.alert.id}:open:6:critical", [item["event_key"] for item in plan_c["to_queue"]])

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_existing_event_key_goes_to_already_queued(self):
        WebPushOperationalAlertEmailDelivery.objects.create(
            alert_id=self.alert.id, event_key=f"alert:{self.alert.id}:open:5:opened", event_type="OPENED", status="PENDING",
            recipient_count=1, recipient_set_hash="x", severity_snapshot="WARNING", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=5,
        )
        plan = {"to_queue": [{"alert_id": self.alert.id, "event_key": f"alert:{self.alert.id}:open:5:opened", "event_type": "OPENED", "severity_snapshot": "WARNING", "scope_type_snapshot": "GLOBAL", "code_snapshot": "test", "current_count_snapshot": 1, "opened_count_snapshot": 1}]}
        res = queue_web_push_operational_alert_email_deliveries(plan, execute=True)
        self.assertEqual(res["queued"], 0)
        self.assertEqual(res["already_queued"], 1)
        self.assertEqual(WebPushOperationalAlertEmailDelivery.objects.filter(event_key=f"alert:{self.alert.id}:open:5:opened").count(), 1)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_resolved_without_prior_sent(self):
        events = [{"alert_id": self.alert.id, "event_type": "RESOLVED", "severity": "WARNING", "opened_count": 2}]
        plan = plan_web_push_operational_alert_email_deliveries(events)
        self.assertEqual(len(plan["to_queue"]), 0)
        self.assertEqual(plan["summary"]["skipped"], 1)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_claim_pending_temporary_failure_only(self):
        statuses = ["SENDING", "SENT", "PERMANENT_FAILURE", "SKIPPED"]
        for s in statuses:
            d = WebPushOperationalAlertEmailDelivery.objects.create(
                alert=self.alert, event_key=s, event_type="OPENED", status=s,
                recipient_count=1, recipient_set_hash="hash", severity_snapshot="WARNING", max_attempts=3,
                scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1,
                sent_at=timezone.now() if s == 'SENT' else None
            )
            res = send_web_push_alert_email_delivery(d.id)
            self.assertEqual(res["error_code"], "invalid_status")

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_claim_next_attempt_at(self):
        d = WebPushOperationalAlertEmailDelivery.objects.create(
            alert=self.alert, event_key="k", event_type="OPENED", status="TEMPORARY_FAILURE",
            next_attempt_at=timezone.now() + datetime.timedelta(hours=1),
            recipient_count=1, recipient_set_hash="x", severity_snapshot="WARNING", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1
        )
        res = send_web_push_alert_email_delivery(d.id)
        self.assertEqual(res["error_code"], "not_due")

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_claim_max_attempts_reached(self):
        c = get_web_push_alert_email_config()
        d = WebPushOperationalAlertEmailDelivery.objects.create(
            alert=self.alert, event_key="max", event_type="OPENED", status="PENDING",
            attempt_count=c['max_attempts'], recipient_count=c['recipient_count'],
            recipient_set_hash=c['recipient_set_hash'], severity_snapshot="WARNING", max_attempts=c['max_attempts'],
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1
        )
        res = send_web_push_alert_email_delivery(d.id)
        self.assertEqual(res["error_code"], "max_attempts_reached")
        d.refresh_from_db()
        self.assertEqual(d.status, "PERMANENT_FAILURE")

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_claim_recipient_configuration_changed(self):
        d = WebPushOperationalAlertEmailDelivery.objects.create(
            alert=self.alert, event_key="change", event_type="OPENED", status="PENDING",
            recipient_count=99, recipient_set_hash="wrong", severity_snapshot="WARNING", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1
        )
        res = send_web_push_alert_email_delivery(d.id)
        self.assertEqual(res["error_code"], "recipient_configuration_changed")
        d.refresh_from_db()
        self.assertEqual(d.status, "SKIPPED")

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com', EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend')
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_failure_smtp_authentication_failed(self, mock_send):
        mock_send.side_effect = SMTPAuthenticationError(535, "auth")
        d = WebPushOperationalAlertEmailDelivery.objects.create(
            alert=self.alert, event_key="auth", event_type="OPENED", status="PENDING",
            recipient_count=1, recipient_set_hash=get_web_push_alert_email_config()['recipient_set_hash'], severity_snapshot="WARNING", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1
        )
        res = send_web_push_alert_email_delivery(d.id)
        self.assertEqual(res["error_code"], "smtp_authentication_failed")
        d.refresh_from_db()
        self.assertEqual(d.status, "PERMANENT_FAILURE")

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com', EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend')
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_failure_recipient_rejected(self, mock_send):
        mock_send.side_effect = SMTPRecipientsRefused({})
        d = WebPushOperationalAlertEmailDelivery.objects.create(
            alert=self.alert, event_key="recj", event_type="OPENED", status="PENDING",
            recipient_count=1, recipient_set_hash=get_web_push_alert_email_config()['recipient_set_hash'], severity_snapshot="WARNING", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1
        )
        res = send_web_push_alert_email_delivery(d.id)
        self.assertEqual(res["error_code"], "recipient_rejected")
        d.refresh_from_db()
        self.assertEqual(d.status, "PERMANENT_FAILURE")

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com', EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend')
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_failure_smtp_temporary_failure(self, mock_send):
        mock_send.side_effect = SMTPException()
        d = WebPushOperationalAlertEmailDelivery.objects.create(
            alert=self.alert, event_key="temp", event_type="OPENED", status="PENDING",
            recipient_count=1, recipient_set_hash=get_web_push_alert_email_config()['recipient_set_hash'], severity_snapshot="WARNING", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1
        )
        res = send_web_push_alert_email_delivery(d.id)
        self.assertEqual(res["error_code"], "smtp_temporary_failure")
        d.refresh_from_db()
        self.assertEqual(d.status, "TEMPORARY_FAILURE")
        self.assertIsNotNone(d.next_attempt_at)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com', EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend')
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_failure_email_backend_unavailable(self, mock_send):
        mock_send.side_effect = ConnectionError()
        d = WebPushOperationalAlertEmailDelivery.objects.create(
            alert=self.alert, event_key="conn", event_type="OPENED", status="PENDING",
            recipient_count=1, recipient_set_hash=get_web_push_alert_email_config()['recipient_set_hash'], severity_snapshot="WARNING", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1
        )
        res = send_web_push_alert_email_delivery(d.id)
        self.assertEqual(res["error_code"], "email_backend_unavailable")
        d.refresh_from_db()
        self.assertEqual(d.status, "TEMPORARY_FAILURE")
        self.assertIsNotNone(d.next_attempt_at)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com', EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend')
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_failure_unexpected_email_error_and_max_retry(self, mock_send):
        mock_send.side_effect = Exception("Unknown")
        c = get_web_push_alert_email_config()
        d = WebPushOperationalAlertEmailDelivery.objects.create(
            alert=self.alert, event_key="unex", event_type="OPENED", status="PENDING",
            attempt_count=c['max_attempts'] - 1,
            recipient_count=1, recipient_set_hash=c['recipient_set_hash'], severity_snapshot="WARNING", max_attempts=c['max_attempts'],
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1
        )
        res = send_web_push_alert_email_delivery(d.id)
        self.assertEqual(res["error_code"], "max_attempts_reached")
        d.refresh_from_db()
        self.assertEqual(d.status, "PERMANENT_FAILURE")

    def test_lease_first_acquire(self):
        self.assertTrue(acquire_web_push_operational_alert_cycle_lease("token1"))

    def test_lease_second_acquire_blocked(self):
        acquire_web_push_operational_alert_cycle_lease("token1")
        self.assertFalse(acquire_web_push_operational_alert_cycle_lease("token2"))

    def test_lease_expired_recovered(self):
        acquire_web_push_operational_alert_cycle_lease("token1")
        WebPushOperationalAlertCycleLease.objects.update(locked_until=timezone.now() - datetime.timedelta(hours=1))
        self.assertTrue(acquire_web_push_operational_alert_cycle_lease("token2"))

    def test_lease_release_by_owner(self):
        acquire_web_push_operational_alert_cycle_lease("token1")
        release_web_push_operational_alert_cycle_lease("token1")
        self.assertTrue(acquire_web_push_operational_alert_cycle_lease("token2"))

    def test_lease_release_by_wrong_owner(self):
        acquire_web_push_operational_alert_cycle_lease("token1")
        release_web_push_operational_alert_cycle_lease("token2")
        self.assertFalse(acquire_web_push_operational_alert_cycle_lease("token3"))

    def test_lease_creation_integrity_error_recovery(self):
        # We test that integrity error returns False for the lease
        with patch('core.models.WebPushOperationalAlertCycleLease.objects.create') as mock_create:
            mock_create.side_effect = IntegrityError()
            self.assertFalse(acquire_web_push_operational_alert_cycle_lease("token4"))

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    @patch('core.services.web_push_alert_email.send_web_push_alert_email_delivery')
    def test_process_due_deliveries_respects_limit(self, mock_send):
        mock_send.return_value = {"error_code": None}
        for i in range(3):
            WebPushOperationalAlertEmailDelivery.objects.create(
                alert=self.alert, event_key=f"limit{i}", event_type="OPENED", status="PENDING",
                recipient_count=1, recipient_set_hash="x", severity_snapshot="WARNING", max_attempts=3,
                scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1
            )
        res = process_due_web_push_operational_alert_email_deliveries(limit=2, execute=True)
        self.assertEqual(res["processed"], 2)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_process_due_deliveries_skips_ineligible_statuses(self):
        WebPushOperationalAlertEmailDelivery.objects.create(
            alert=self.alert, event_key="skip", event_type="OPENED", status="SENT",
            recipient_count=1, recipient_set_hash="x", severity_snapshot="WARNING", max_attempts=3,
            scope_type_snapshot="GLOBAL", code_snapshot="c", current_count_snapshot=1, opened_count_snapshot=1,
            sent_at=timezone.now()
        )
        res = process_due_web_push_operational_alert_email_deliveries(limit=50, execute=True)
        self.assertEqual(res["processed"], 0)

class TestWebPushAtomicClaim(TransactionTestCase):
    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com', EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend')
    def test_in_atomic_block(self):
        with transaction.atomic():
            with self.assertRaises(RuntimeError):
                send_web_push_alert_email_delivery(1)

from django.core.management import call_command
from django.core.management.base import CommandError
import io

class TestWebPushAlertCycleCommand(TransactionTestCase):
    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_dry_run_does_not_mutate(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', stdout=out)
        self.assertIn('DRY_RUN', out.getvalue())

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_dry_run_does_not_queue(self):
        call_command('web_push_operational_alerts_cycle')
        self.assertEqual(WebPushOperationalAlertEmailDelivery.objects.count(), 0)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_dry_run_does_not_send(self):
        with patch('core.services.web_push_alert_email.send_web_push_alert_email_delivery') as mock:
            call_command('web_push_operational_alerts_cycle')
            mock.assert_not_called()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_dry_run_does_not_acquire_persistent_lease(self):
        call_command('web_push_operational_alerts_cycle')
        self.assertEqual(WebPushOperationalAlertCycleLease.objects.count(), 0)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_notify_requires_execute(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--notify-email', stdout=out, stderr=out)
        self.assertIn('exige --execute', out.getvalue())

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=False)
    def test_cycle_notify_requires_enabled_channel(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--execute', '--notify-email', stdout=out, stderr=out)
        self.assertIn('desabilitado', out.getvalue().lower())

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_execute_without_notify_only_persists_incidents(self):
        # Trigger an incident by mocking
        with patch('core.services.web_push_alerts.apply_web_push_operational_alert_plan') as mock_apply:
            mock_apply.return_value = {"transition_events": [{"alert_id": 1, "event_type": "OPENED", "severity": "WARNING", "opened_count": 1}]}
            call_command('web_push_operational_alerts_cycle', '--execute')
            self.assertEqual(WebPushOperationalAlertEmailDelivery.objects.count(), 0)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_global_processed_once(self):
        with patch('core.management.commands.web_push_operational_alerts_cycle.apply_web_push_operational_alert_plan') as mock:
            mock.return_value = {}
            call_command('web_push_operational_alerts_cycle', '--execute')
            # It should be called once for global, and once per band.
            # No bands exist, so just 1.
            self.assertEqual(mock.call_count, 1)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_processes_all_bands_separately(self):
        from core.models import Band
        Band.objects.create(name="B1", slug="b1")
        Band.objects.create(name="B2", slug="b2")
        with patch('core.management.commands.web_push_operational_alerts_cycle.apply_web_push_operational_alert_plan') as mock:
            mock.return_value = {}
            call_command('web_push_operational_alerts_cycle', '--execute')
            # 1 global + 2 bands
            self.assertEqual(mock.call_count, 3)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_band_error_isolated(self):
        from core.models import Band
        Band.objects.create(name="B1", slug="b1")
        def side_effect(plan, execute):
            if plan.get('scope', {}).get('band_slug') == 'b1': raise Exception("Band error")
            return {}
        with patch('core.management.commands.web_push_operational_alerts_cycle.apply_web_push_operational_alert_plan', side_effect=side_effect):
            out = io.StringIO()
            call_command('web_push_operational_alerts_cycle', '--execute', '--json', stdout=out)
            res = json.loads(out.getvalue())
            self.assertEqual(len(res['errors']), 1)
            self.assertEqual(res['errors'][0]['scope'], 'BAND:b1')

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_processes_due_deliveries(self):
        with patch('core.management.commands.web_push_operational_alerts_cycle.process_due_web_push_operational_alert_email_deliveries') as mock:
            call_command('web_push_operational_alerts_cycle', '--execute', '--notify-email')
            mock.assert_called_once()

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_json_serializable(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--execute', '--json', stdout=out)
        self.assertIsInstance(json.loads(out.getvalue()), dict)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_output_has_no_sensitive_data(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--execute', '--json', stdout=out)
        val = out.getvalue()
        self.assertNotIn('a@a.com', val)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_trigger_manual(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--json', stdout=out)
        self.assertEqual(json.loads(out.getvalue())['trigger'], 'manual')

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_trigger_scheduled(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--json', '--trigger', 'scheduled', stdout=out)
        self.assertEqual(json.loads(out.getvalue())['trigger'], 'scheduled')

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_releases_lease_on_success(self):
        call_command('web_push_operational_alerts_cycle', '--execute', '--notify-email')
        self.assertEqual(WebPushOperationalAlertCycleLease.objects.count(), 0)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_releases_lease_on_error(self):
        with patch('core.management.commands.web_push_operational_alerts_cycle.process_due_web_push_operational_alert_email_deliveries', side_effect=Exception):
            out = io.StringIO()
            call_command('web_push_operational_alerts_cycle', '--execute', '--notify-email', '--json', stdout=out)
            self.assertEqual(WebPushOperationalAlertCycleLease.objects.count(), 0)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_overlap_returns_skipped_overlap(self):
        WebPushOperationalAlertCycleLease.objects.create(owner_token="other", locked_until=timezone.now() + datetime.timedelta(hours=1))
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--execute', '--notify-email', '--json', stdout=out)
        res = json.loads(out.getvalue())
        self.assertFalse(res['lease_acquired'])
        self.assertEqual(res['errors'][0], 'could not acquire lease')

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_work_runs_outside_lease_transaction(self):
        with patch('core.management.commands.web_push_operational_alerts_cycle.process_due_web_push_operational_alert_email_deliveries') as mock:
            call_command('web_push_operational_alerts_cycle', '--execute', '--notify-email')
            # If it runs inside a transaction, the code in the command is flawed, but the command uses separate functions without an outer atomic block.
            mock.assert_called_once()

    @patch('core.management.commands.web_push_operational_alerts_cycle.plan_web_push_operational_alerts')
    def test_cycle_operational_parameters_defaults(self, mock_plan):
        mock_plan.return_value = {"summary": {}, "transition_events": []}
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', stdout=out)
        self.assertEqual(mock_plan.call_count, 1 + Band.objects.count())
        mock_plan.assert_any_call(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)

    @patch('core.management.commands.web_push_operational_alerts_cycle.plan_web_push_operational_alerts')
    def test_cycle_operational_parameters_custom_values(self, mock_plan):
        mock_plan.return_value = {"summary": {}, "transition_events": []}
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--hours', '48', '--stale-pending-minutes', '20', '--stale-sending-minutes', '30', stdout=out)
        self.assertEqual(mock_plan.call_count, 1 + Band.objects.count())
        mock_plan.assert_any_call(band_slug=None, window_hours=48, stale_pending_minutes=20, stale_sending_minutes=30)

    def test_cycle_hours_lower_bound(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--hours', '1', stdout=out)
        self.assertIn('Janela: 1 horas', out.getvalue())

    def test_cycle_hours_upper_bound(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--hours', '720', stdout=out)
        self.assertIn('Janela: 720 horas', out.getvalue())

    def test_cycle_hours_below_minimum_rejected(self):
        with self.assertRaisesMessage(CommandError, 'hours deve estar entre 1 e 720'):
            call_command('web_push_operational_alerts_cycle', '--hours', '0')

    def test_cycle_hours_above_maximum_rejected(self):
        with self.assertRaisesMessage(CommandError, 'hours deve estar entre 1 e 720'):
            call_command('web_push_operational_alerts_cycle', '--hours', '721')

    def test_cycle_stale_pending_lower_bound(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--stale-pending-minutes', '5', stdout=out)
        self.assertIn('PENDING stale: 5 minutos', out.getvalue())

    def test_cycle_stale_pending_upper_bound(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--stale-pending-minutes', '10080', stdout=out)
        self.assertIn('PENDING stale: 10080 minutos', out.getvalue())

    def test_cycle_stale_pending_out_of_range_rejected(self):
        with self.assertRaisesMessage(CommandError, 'stale-pending-minutes deve estar entre 5 e 10080'):
            call_command('web_push_operational_alerts_cycle', '--stale-pending-minutes', '4')
        with self.assertRaisesMessage(CommandError, 'stale-pending-minutes deve estar entre 5 e 10080'):
            call_command('web_push_operational_alerts_cycle', '--stale-pending-minutes', '10081')

    def test_cycle_stale_sending_lower_bound(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--stale-sending-minutes', '5', stdout=out)
        self.assertIn('SENDING stale: 5 minutos', out.getvalue())

    def test_cycle_stale_sending_upper_bound(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--stale-sending-minutes', '10080', stdout=out)
        self.assertIn('SENDING stale: 10080 minutos', out.getvalue())

    def test_cycle_stale_sending_out_of_range_rejected(self):
        with self.assertRaisesMessage(CommandError, 'stale-sending-minutes deve estar entre 5 e 10080'):
            call_command('web_push_operational_alerts_cycle', '--stale-sending-minutes', '4')
        with self.assertRaisesMessage(CommandError, 'stale-sending-minutes deve estar entre 5 e 10080'):
            call_command('web_push_operational_alerts_cycle', '--stale-sending-minutes', '10081')

    def test_cycle_parameters_appear_in_json(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--hours', '48', '--stale-pending-minutes', '20', '--stale-sending-minutes', '30', '--json', stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data['parameters']['hours'], 48)
        self.assertEqual(data['parameters']['stale_pending_minutes'], 20)
        self.assertEqual(data['parameters']['stale_sending_minutes'], 30)

    def test_cycle_parameters_appear_in_human_output(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--hours', '48', '--stale-pending-minutes', '20', '--stale-sending-minutes', '30', stdout=out)
        output = out.getvalue()
        self.assertIn('Janela: 48 horas', output)
        self.assertIn('PENDING stale: 20 minutos', output)
        self.assertIn('SENDING stale: 30 minutos', output)
        self.assertIn('Ciclo concluído em modo DRY_RUN.', output)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_cycle_custom_parameters_dry_run_has_no_side_effects(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--hours', '48', '--stale-pending-minutes', '20', '--stale-sending-minutes', '30', stdout=out)
        self.assertEqual(WebPushOperationalAlert.objects.count(), 0)
        self.assertEqual(WebPushOperationalAlertCycleLease.objects.count(), 0)
        self.assertEqual(WebPushOperationalAlertEmailDelivery.objects.count(), 0)

    def test_cycle_blank_band_slug_does_not_call_planner(self):
        Band.objects.create(name='Blank Band', slug='   ')
        Band.objects.create(name='Valid Band', slug='valid-band')
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--json', stdout=out)
        data = json.loads(out.getvalue())

        global_errors = [e for e in data['errors'] if e.get('scope') == 'GLOBAL']
        band_errors = [e for e in data['errors'] if e.get('scope') == 'BAND' and e.get('error') == 'invalid_band_slug']

        self.assertEqual(len(global_errors), 0, "No global errors expected")
        self.assertEqual(len(band_errors), 1, "Expected exactly one invalid_band_slug error")

        # Verify planner was called exactly once for GLOBAL (global result is a single dict, not a list of dicts, and not duplicated)
        self.assertIsNotNone(data.get('global'))

        # Verify the valid band was processed
        processed_slugs = [b['band_slug'] for b in data['bands']]
        self.assertIn('valid-band', processed_slugs)
        self.assertNotIn('', processed_slugs)
        self.assertNotIn('   ', processed_slugs)

    def test_cycle_help_lists_operational_parameters(self):
        import contextlib
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                call_command('web_push_operational_alerts_cycle', '--help')
        except SystemExit:
            pass
        help_text = out.getvalue()
        self.assertIn('--hours', help_text)
        self.assertIn('--stale-pending-minutes', help_text)
        self.assertIn('--stale-sending-minutes', help_text)

class TestWebPushTestCommand(TestCase):
    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_dry_run_does_not_send(self):
        with patch('django.core.mail.EmailMultiAlternatives.send') as mock:
            out = io.StringIO()
            call_command('web_push_operational_alert_email_test', stdout=out)
            mock.assert_not_called()
            self.assertIn('dry-run', out.getvalue())

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com', EMAIL_BACKEND='django.core.mail.backends.dummy.EmailBackend')
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_execute_calls_backend_mocked(self, mock_send):
        out = io.StringIO()
        call_command('web_push_operational_alert_email_test', '--execute', stdout=out)
        mock_send.assert_called_once()
        self.assertIn('sent', out.getvalue())

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_no_addresses_appear(self):
        out = io.StringIO()
        call_command('web_push_operational_alert_email_test', stdout=out)
        self.assertNotIn('a@a.com', out.getvalue())

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com,b@b.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_only_recipient_count_displayed(self):
        out = io.StringIO()
        call_command('web_push_operational_alert_email_test', stdout=out)
        res = json.loads(out.getvalue())
        self.assertEqual(res['recipient_count'], 2)

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='invalid', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    def test_invalid_config_sanitized(self):
        out = io.StringIO()
        call_command('web_push_operational_alert_email_test', stdout=out)
        res = json.loads(out.getvalue())
        self.assertEqual(res['status'], 'invalid_configuration')

    @override_settings(WEB_PUSH_ALERT_EMAIL_ENABLED=True, WEB_PUSH_ALERT_EMAIL_RECIPIENTS='a@a.com', WEB_PUSH_ALERT_EMAIL_FROM='a@a.com', WEB_PUSH_ALERT_DASHBOARD_URL='http://a.com')
    @patch('django.core.mail.EmailMultiAlternatives.send')
    def test_does_not_create_records(self, mock):
        call_command('web_push_operational_alert_email_test', '--execute')
        self.assertEqual(WebPushOperationalAlert.objects.count(), 0)
        self.assertEqual(WebPushOperationalAlertEmailDelivery.objects.count(), 0)
        from core.models import Notification, WebPushDelivery
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(WebPushDelivery.objects.count(), 0)


    def test_cycle_valid_bands_do_not_return_unexpected_error(self):
        Band.objects.create(name="Valid Band", slug="valid-band")
        Band.objects.create(name="Empty Band", slug="  ")

        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--json', stdout=out)
        data = json.loads(out.getvalue())

        # GLOBAL is processed once
        self.assertIsNotNone(data.get('global'))

        # Valid band does not have unexpected_error
        valid_errors = [e for e in data['errors'] if e.get('scope') == 'BAND:valid-band']
        self.assertEqual(len(valid_errors), 0)

        # Empty band has invalid_band_slug
        empty_errors = [e for e in data['errors'] if e.get('error') == 'invalid_band_slug']
        self.assertEqual(len(empty_errors), 1)

    def test_cycle_human_output_utf8_without_bom(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', stdout=out)
        text = out.getvalue()

        self.assertFalse(text.startswith('\ufeff'))
        self.assertIn("Ciclo concluído em modo DRY_RUN.", text)
        self.assertNotIn("Ciclo concluÝdo", text)

    def test_cycle_json_output_starts_with_brace(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--json', stdout=out)
        text = out.getvalue()

        self.assertFalse(text.startswith('\ufeff'))
        self.assertTrue(text.startswith("{"))

    def test_cycle_json_output_parses_without_sanitization(self):
        out = io.StringIO()
        call_command('web_push_operational_alerts_cycle', '--json', stdout=out)
        text = out.getvalue()

        self.assertFalse(text.startswith('\ufeff'))

        raw_bytes = text.encode('utf-8')
        import json
        data = json.loads(raw_bytes)
        self.assertEqual(data.get('mode'), 'DRY_RUN')

    def test_cycle_help_utf8(self):
        import contextlib
        import io
        from django.core.management import call_command
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                call_command('web_push_operational_alerts_cycle', '--help')
        except SystemExit:
            pass

        text = out.getvalue()
        self.assertIn("Avaliação", text)
        self.assertIn("Saída", text)
