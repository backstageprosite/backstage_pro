import json
import datetime
from django.test import TestCase
from django.utils import timezone
from django.db import IntegrityError
from django.core.management import call_command
from core.models import Band, WebPushOperationalAlert
from core.services.web_push_alerts import plan_web_push_operational_alerts, apply_web_push_operational_alert_plan
from django.core.management.base import CommandError

class WebPushOperationalAlertModelTests(TestCase):
    def test_global_without_band(self):
        alert = WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL",
            dedupe_key="global:test",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test"
        )
        self.assertIsNone(alert.band)

    def test_band_with_band(self):
        b = Band.objects.create(name="Test", slug="test")
        alert = WebPushOperationalAlert.objects.create(
            scope_type="BAND",
            band=b,
            dedupe_key="band:test:test_code",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test"
        )
        self.assertEqual(alert.band, b)

    def test_global_with_band_invalid(self):
        b = Band.objects.create(name="Test", slug="test")
        alert = WebPushOperationalAlert(
            scope_type="GLOBAL",
            band=b,
            dedupe_key="global:invalid",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test"
        )
        with self.assertRaises(IntegrityError):
            alert.save()

    def test_band_without_band_invalid(self):
        alert = WebPushOperationalAlert(
            scope_type="BAND",
            dedupe_key="band:invalid",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test"
        )
        with self.assertRaises(IntegrityError):
            alert.save()

    def test_dedupe_key_unique(self):
        WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL",
            dedupe_key="global:test",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test"
        )
        with self.assertRaises(IntegrityError):
            WebPushOperationalAlert.objects.create(
                scope_type="GLOBAL",
                dedupe_key="global:test",
                code="test_code2",
                severity="WARNING",
                status="ACTIVE",
                title="Test2",
                message="Test2"
            )

    def test_current_count_negative_invalid(self):
        alert = WebPushOperationalAlert(
            scope_type="GLOBAL",
            dedupe_key="global:test2",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test",
            current_count=-1
        )
        with self.assertRaises(IntegrityError):
            alert.save()

    def test_opened_count_zero_invalid(self):
        alert = WebPushOperationalAlert(
            scope_type="GLOBAL",
            dedupe_key="global:test3",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test",
            opened_count=0
        )
        with self.assertRaises(IntegrityError):
            alert.save()

    def test_active_with_resolved_at_invalid(self):
        alert = WebPushOperationalAlert(
            scope_type="GLOBAL",
            dedupe_key="global:test4",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test",
            resolved_at=timezone.now()
        )
        with self.assertRaises(IntegrityError):
            alert.save()

    def test_resolved_without_resolved_at_invalid(self):
        alert = WebPushOperationalAlert(
            scope_type="GLOBAL",
            dedupe_key="global:test5",
            code="test_code",
            severity="RESOLVED",
            status="RESOLVED",
            title="Test",
            message="Test",
            resolved_at=None
        )
        with self.assertRaises(IntegrityError):
            alert.save()

    def test_timestamps_initials(self):
        now = timezone.now()
        alert = WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL",
            dedupe_key="global:test6",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test"
        )
        self.assertIsNotNone(alert.first_detected_at)
        self.assertIsNotNone(alert.last_detected_at)
        self.assertIsNone(alert.resolved_at)
        self.assertIsNotNone(alert.created_at)
        self.assertIsNotNone(alert.updated_at)

    def test_on_delete_protect(self):
        from django.db.models import ProtectedError
        b = Band.objects.create(name="Test2", slug="test2")
        WebPushOperationalAlert.objects.create(
            scope_type="BAND",
            band=b,
            dedupe_key="band:test2:test_code",
            code="test_code",
            severity="WARNING",
            status="ACTIVE",
            title="Test",
            message="Test"
        )
        with self.assertRaises(ProtectedError):
            b.delete()


from unittest.mock import patch

class WebPushOperationalAlertPlanTests(TestCase):

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_plan_new_alert(self, mock_snapshot, mock_alerts):
        mock_alerts.return_value = [{'code': 'test_1', 'severity': 'WARNING', 'title': 'Test 1', 'message': 'Msg 1', 'recommended_action': 'Action 1', 'count': 1}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan['to_open']), 1)
        self.assertEqual(len(plan['to_update']), 0)
        self.assertEqual(len(plan['to_resolve']), 0)
        self.assertEqual(len(plan['unchanged']), 0)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_plan_update_alert(self, mock_snapshot, mock_alerts):
        WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL", dedupe_key="global:test_2", code="test_2",
            severity="WARNING", status="ACTIVE", title="Test 2", message="Msg 2"
        )
        mock_alerts.return_value = [{'code': 'test_2', 'severity': 'CRITICAL', 'title': 'Test 2', 'message': 'Msg 2 modified', 'recommended_action': 'Action 2', 'count': 2}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan['to_update']), 1)
        self.assertEqual(plan['to_update'][0]['severity'], 'CRITICAL')
        self.assertEqual(len(plan['to_open']), 0)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_plan_unchanged_alert(self, mock_snapshot, mock_alerts):
        WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL", dedupe_key="global:test_3", code="test_3",
            severity="WARNING", status="ACTIVE", title="Test 3", message="Msg 3", recommended_action="Action 3", current_count=1
        )
        mock_alerts.return_value = [{'code': 'test_3', 'severity': 'WARNING', 'title': 'Test 3', 'message': 'Msg 3', 'recommended_action': 'Action 3', 'count': 1}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan['unchanged']), 1)
        self.assertEqual(len(plan['to_update']), 0)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_plan_resolve_alert(self, mock_snapshot, mock_alerts):
        WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL", dedupe_key="global:test_4", code="test_4",
            severity="WARNING", status="ACTIVE", title="Test 4", message="Msg 4", recommended_action="Action 4", current_count=1
        )
        mock_alerts.return_value = []
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan['to_resolve']), 1)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_plan_reopen_alert(self, mock_snapshot, mock_alerts):
        WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL", dedupe_key="global:test_5", code="test_5",
            severity="WARNING", status="RESOLVED", title="Test 5", message="Msg 5", recommended_action="Action 5", current_count=1,
            resolved_at=timezone.now()
        )
        mock_alerts.return_value = [{'code': 'test_5', 'severity': 'WARNING', 'title': 'Test 5', 'message': 'Msg 5', 'recommended_action': 'Action 5', 'count': 1}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan['to_update']), 1)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_plan_ignores_info_alerts(self, mock_snapshot, mock_alerts):
        mock_alerts.return_value = [{'code': 'test_info', 'severity': 'INFO', 'title': 'Test INFO', 'message': 'Msg INFO', 'recommended_action': 'Action INFO', 'count': 1}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan['to_open']), 0)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_apply_plan_dry_run(self, mock_snapshot, mock_alerts):
        mock_alerts.return_value = [{'code': 'test_6', 'severity': 'WARNING', 'title': 'Test 6', 'message': 'Msg 6', 'recommended_action': 'Action 6', 'count': 1}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        apply_web_push_operational_alert_plan(plan, execute=False)
        self.assertEqual(WebPushOperationalAlert.objects.count(), 0)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_apply_plan_execute(self, mock_snapshot, mock_alerts):
        mock_alerts.return_value = [{'code': 'test_7', 'severity': 'WARNING', 'title': 'Test 7', 'message': 'Msg 7', 'recommended_action': 'Action 7', 'count': 1}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        apply_web_push_operational_alert_plan(plan, execute=True)
        self.assertEqual(WebPushOperationalAlert.objects.count(), 1)
        alert = WebPushOperationalAlert.objects.first()
        self.assertEqual(alert.code, 'test_7')
        self.assertEqual(alert.status, 'ACTIVE')
        self.assertEqual(alert.opened_count, 1)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_apply_plan_execute_update(self, mock_snapshot, mock_alerts):
        WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL", dedupe_key="global:test_8", code="test_8",
            severity="WARNING", status="ACTIVE", title="Test 8", message="Msg 8"
        )
        mock_alerts.return_value = [{'code': 'test_8', 'severity': 'CRITICAL', 'title': 'Test 8', 'message': 'Msg 8 mod', 'recommended_action': 'Action 8', 'count': 2}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        apply_web_push_operational_alert_plan(plan, execute=True)

        alert = WebPushOperationalAlert.objects.first()
        self.assertEqual(alert.severity, 'CRITICAL')
        self.assertEqual(alert.message, 'Msg 8 mod')

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_apply_plan_execute_resolve(self, mock_snapshot, mock_alerts):
        WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL", dedupe_key="global:test_9", code="test_9",
            severity="WARNING", status="ACTIVE", title="Test 9", message="Msg 9"
        )
        mock_alerts.return_value = []
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        apply_web_push_operational_alert_plan(plan, execute=True)

        alert = WebPushOperationalAlert.objects.first()
        self.assertEqual(alert.status, 'RESOLVED')
        self.assertIsNotNone(alert.resolved_at)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_apply_plan_execute_reopen(self, mock_snapshot, mock_alerts):
        WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL", dedupe_key="global:test_10", code="test_10",
            severity="WARNING", status="RESOLVED", title="Test 10", message="Msg 10",
            resolved_at=timezone.now(), opened_count=1
        )
        mock_alerts.return_value = [{'code': 'test_10', 'severity': 'WARNING', 'title': 'Test 10', 'message': 'Msg 10', 'recommended_action': 'Action 10', 'count': 1}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        apply_web_push_operational_alert_plan(plan, execute=True)

        alert = WebPushOperationalAlert.objects.first()
        self.assertEqual(alert.status, 'ACTIVE')
        self.assertIsNone(alert.resolved_at)
        self.assertEqual(alert.opened_count, 2)

    def test_apply_plan_invalid_structure(self):
        with self.assertRaisesRegex(ValueError, "Plan must be a dict"):
            apply_web_push_operational_alert_plan([])

        with self.assertRaisesRegex(ValueError, "Missing required key"):
            apply_web_push_operational_alert_plan({"scope": {"scope_type": "GLOBAL"}})

    def test_apply_plan_invalid_scope(self):
        base_plan = {"to_open": [], "to_update": [], "to_resolve": [], "unchanged": []}
        plan = dict(base_plan)
        plan["scope"] = {"scope_type": "INVALID"}
        with self.assertRaisesRegex(ValueError, "Invalid scope_type"):
            apply_web_push_operational_alert_plan(plan)

    def test_apply_plan_invalid_band_scope(self):
        base_plan = {"to_open": [], "to_update": [], "to_resolve": [], "unchanged": []}
        plan = dict(base_plan)
        plan["scope"] = {"scope_type": "BAND", "band_slug": None}
        with self.assertRaisesRegex(ValueError, "band_slug missing for BAND scope"):
            apply_web_push_operational_alert_plan(plan)

    def test_apply_plan_incompatible_dedupe_key(self):
        plan = {
            "scope": {"scope_type": "GLOBAL"},
            "to_open": [{"dedupe_key": "band:invalid:1", "code": "c", "severity": "WARNING", "title": "t", "message": "m", "recommended_action": "", "current_count": 1}],
            "to_update": [], "to_resolve": [], "unchanged": []
        }
        with self.assertRaisesRegex(ValueError, "dedupe_key incompatible with GLOBAL scope"):
            apply_web_push_operational_alert_plan(plan)

        band = Band.objects.create(name="test-band", slug="test-band")
        plan = {
            "scope": {"scope_type": "BAND", "band_slug": band.slug},
            "to_open": [{"dedupe_key": "global:1", "code": "c", "severity": "WARNING", "title": "t", "message": "m", "recommended_action": "", "current_count": 1}],
            "to_update": [], "to_resolve": [], "unchanged": []
        }
        with self.assertRaisesRegex(ValueError, "dedupe_key incompatible with BAND scope"):
            apply_web_push_operational_alert_plan(plan)

    def test_apply_plan_invalid_severity(self):
        plan = {
            "scope": {"scope_type": "GLOBAL"},
            "to_open": [{"dedupe_key": "global:1", "code": "c", "severity": "INVALID", "title": "t", "message": "m", "recommended_action": "", "current_count": 1}],
            "to_update": [], "to_resolve": [], "unchanged": []
        }
        with self.assertRaisesRegex(ValueError, "Invalid severity"):
            apply_web_push_operational_alert_plan(plan)

    def test_apply_plan_raw_datetime(self):
        plan = {
            "scope": {"scope_type": "GLOBAL"},
            "to_open": [{"dedupe_key": "global:1", "code": "c", "severity": "WARNING", "title": "t", "message": "m", "recommended_action": "", "current_count": 1, "date": timezone.now()}],
            "to_update": [], "to_resolve": [], "unchanged": []
        }
        with self.assertRaisesRegex(ValueError, "Raw datetime found"):
            apply_web_push_operational_alert_plan(plan)

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_plan_idempotency(self, mock_snapshot, mock_alerts):
        mock_alerts.return_value = [{'code': 'test_idem', 'severity': 'WARNING', 'title': 'Test', 'message': 'Msg', 'recommended_action': 'Action', 'count': 1}]
        plan1 = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        res1 = apply_web_push_operational_alert_plan(plan1, execute=True)
        self.assertEqual(res1["opened"], 1)
        self.assertEqual(res1["updated"], 0)
        self.assertEqual(res1["resolved"], 0)
        self.assertEqual(res1["unchanged"], 0)

        plan2 = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        res2 = apply_web_push_operational_alert_plan(plan2, execute=True)
        self.assertEqual(res2["opened"], 0)
        self.assertEqual(res2["updated"], 0)
        self.assertEqual(res2["resolved"], 0)
        self.assertEqual(res2["unchanged"], 1)

        import json
        self.assertIsInstance(json.dumps(res2), str)

    def test_apply_plan_integrity_error_recovery(self):
        # We simulate that the create will raise IntegrityError (like concurrent creation)
        # and it should fall back to select_for_update().get() and update the existing.
        from django.db import IntegrityError

        WebPushOperationalAlert.objects.create(
            scope_type="GLOBAL", dedupe_key="global:test_concurrent", code="c",
            severity="WARNING", status="ACTIVE", title="Old", message="Old", current_count=1
        )

        plan = {
            "scope": {"scope_type": "GLOBAL", "band_slug": None},
            "to_open": [{"dedupe_key": "global:test_concurrent", "code": "c", "severity": "CRITICAL", "title": "New", "message": "New", "recommended_action": "", "current_count": 2}],
            "to_update": [], "to_resolve": [], "unchanged": []
        }

        with patch('core.services.web_push_alerts.WebPushOperationalAlert.objects.create') as mock_create:
            mock_create.side_effect = IntegrityError("Unique violation")
            res = apply_web_push_operational_alert_plan(plan, execute=True)

        # It should have recovered and updated the existing record
        self.assertEqual(res["errors"], 0)
        self.assertEqual(res["updated"], 1)
        self.assertEqual(WebPushOperationalAlert.objects.filter(dedupe_key="global:test_concurrent").count(), 1)
        alert = WebPushOperationalAlert.objects.get(dedupe_key="global:test_concurrent")
        self.assertEqual(alert.severity, "CRITICAL")
        self.assertEqual(alert.title, "New")

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_isolation_scopes(self, mock_snapshot, mock_alerts):
        b1 = Band.objects.create(name="B1", slug="b1")
        b2 = Band.objects.create(name="B2", slug="b2")

        # Create global alert
        WebPushOperationalAlert.objects.create(scope_type="GLOBAL", dedupe_key="global:test_iso", code="c", severity="WARNING", status="ACTIVE", title="T", message="M", current_count=1)

        # Create b1 alert
        WebPushOperationalAlert.objects.create(scope_type="BAND", band=b1, dedupe_key="band:b1:test_iso", code="c", severity="WARNING", status="ACTIVE", title="T", message="M", current_count=1)

        # Plan for B2 should resolve B2's alerts if any, but since B2 has none, it should not resolve B1 or GLOBAL
        mock_alerts.return_value = []
        plan_b2 = plan_web_push_operational_alerts(band_slug="b2", window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan_b2["to_resolve"]), 0)

        # Plan for B1 should resolve ONLY B1
        plan_b1 = plan_web_push_operational_alerts(band_slug="b1", window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan_b1["to_resolve"]), 1)
        self.assertEqual(plan_b1["to_resolve"][0]["dedupe_key"], "band:b1:test_iso")

        # Plan for GLOBAL should resolve ONLY GLOBAL
        plan_global = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan_global["to_resolve"]), 1)
        self.assertEqual(plan_global["to_resolve"][0]["dedupe_key"], "global:test_iso")

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    @patch('core.services.web_push_alerts.build_web_push_health_snapshot')
    def test_info_resolves_active(self, mock_snapshot, mock_alerts):
        WebPushOperationalAlert.objects.create(scope_type="GLOBAL", dedupe_key="global:test_info_resolve", code="test_info_resolve", severity="WARNING", status="ACTIVE", title="T", message="M", current_count=1)
        mock_alerts.return_value = [{'code': 'test_info_resolve', 'severity': 'INFO', 'title': 'Test INFO', 'message': 'Msg INFO', 'recommended_action': 'Action INFO', 'count': 1}]
        plan = plan_web_push_operational_alerts(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        self.assertEqual(len(plan['to_resolve']), 1)


class WebPushOperationalAlertCommandTests(TestCase):
    def setUp(self):
        from core.models import Band
        self.band1 = Band.objects.create(name="B1", slug="b1")
        self.band2 = Band.objects.create(name="B2", slug="b2")

    def test_command_no_scope_rejected(self):
        # 1. nenhum escopo informado é rejeitado;
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('web_push_operational_alerts')

    def test_command_mutually_exclusive_global_band(self):
        # 2. --global e --band-slug juntos são rejeitados;
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('web_push_operational_alerts', '--global', '--band-slug', 'b1')

    def test_command_mutually_exclusive_global_all(self):
        # 3. --global e --all-bands juntos são rejeitados;
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('web_push_operational_alerts', '--global', '--all-bands')

    def test_command_mutually_exclusive_band_all(self):
        # 4. --band-slug e --all-bands juntos são rejeitados;
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('web_push_operational_alerts', '--band-slug', 'b1', '--all-bands')

    @patch('core.management.commands.web_push_operational_alerts.plan_web_push_operational_alerts')
    def test_command_executes_only_global(self, mock_plan):
        # 5. --global executa somente escopo GLOBAL;
        mock_plan.return_value = {"to_open": [], "to_update": [], "to_resolve": [], "unchanged": []}
        import io
        call_command('web_push_operational_alerts', '--global', stdout=io.StringIO())
        mock_plan.assert_called_once_with(band_slug=None, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)

    @patch('core.management.commands.web_push_operational_alerts.plan_web_push_operational_alerts')
    def test_command_executes_only_band(self, mock_plan):
        # 6. --band-slug executa somente a banda informada;
        mock_plan.return_value = {"to_open": [], "to_update": [], "to_resolve": [], "unchanged": []}
        import io
        call_command('web_push_operational_alerts', '--band-slug', 'b1', stdout=io.StringIO())
        mock_plan.assert_called_once_with(band_slug='b1', window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)

    @patch('core.management.commands.web_push_operational_alerts.plan_web_push_operational_alerts')
    def test_command_executes_all_bands_separately(self, mock_plan):
        # 7. --all-bands processa todas as bandas separadamente;
        # 8. --all-bands não processa escopo GLOBAL;
        mock_plan.return_value = {"to_open": [], "to_update": [], "to_resolve": [], "unchanged": []}
        import io
        call_command('web_push_operational_alerts', '--all-bands', stdout=io.StringIO())

        self.assertEqual(mock_plan.call_count, 2)
        mock_plan.assert_any_call(band_slug='b1', window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        mock_plan.assert_any_call(band_slug='b2', window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15)
        for call_args in mock_plan.call_args_list:
            self.assertIsNotNone(call_args.kwargs.get('band_slug'))

    @patch('core.management.commands.web_push_operational_alerts.plan_web_push_operational_alerts')
    def test_command_error_isolation_all_bands(self, mock_plan):
        # 9. erro em uma banda não impede o processamento das demais;
        def side_effect(band_slug, **kwargs):
            if band_slug == 'b1':
                raise Exception("SEGREDO_INTERNO_DATABASE_PASSWORD")
            return {"to_open": [], "to_update": [], "to_resolve": [], "unchanged": []}
        mock_plan.side_effect = side_effect

        import io
        out = io.StringIO()
        err = io.StringIO()
        call_command('web_push_operational_alerts', '--all-bands', stdout=out, stderr=err)

        self.assertEqual(mock_plan.call_count, 2)

        err_output = err.getvalue()
        self.assertIn("Erro ao processar o escopo b1.", err_output)
        self.assertNotIn("SEGREDO_INTERNO_DATABASE_PASSWORD", err_output)
        self.assertNotIn("SEGREDO_INTERNO_DATABASE_PASSWORD", out.getvalue())
        self.assertNotIn("Traceback", err_output)
        self.assertNotIn("Traceback", out.getvalue())

    def test_command_dry_run_is_default(self):
        # 10. DRY-RUN é o comportamento padrão;
        # 22. não existe flag --dry-run; (argparse will reject it if passed)
        import io
        out = io.StringIO()
        call_command('web_push_operational_alerts', '--global', stdout=out)
        self.assertIn("DRY-RUN", out.getvalue())
        self.assertIn("Nenhuma altera", out.getvalue())

    def test_command_no_dry_run_flag_exists(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('web_push_operational_alerts', '--global', '--dry-run')

    @patch('core.management.commands.web_push_operational_alerts.apply_web_push_operational_alert_plan')
    @patch('core.management.commands.web_push_operational_alerts.plan_web_push_operational_alerts')
    def test_command_only_execute_persists(self, mock_plan, mock_apply):
        # 11. somente --execute persiste;
        mock_plan.return_value = {"to_open": [], "to_update": [], "to_resolve": [], "unchanged": []}
        mock_apply.return_value = {'opened': 0, 'updated': 0, 'resolved': 0, 'unchanged': 0, 'errors': 0, 'results': []}

        import io
        call_command('web_push_operational_alerts', '--global', stdout=io.StringIO())
        mock_apply.assert_called_once_with(mock_plan.return_value, execute=False)

        mock_apply.reset_mock()

        call_command('web_push_operational_alerts', '--global', '--execute', stdout=io.StringIO())
        mock_apply.assert_called_once_with(mock_plan.return_value, execute=True)

    def test_command_json_valid_and_serializable(self):
        # 12. --json produz JSON válido;
        # 13. --json contém somente tipos serializáveis;
        import io, json
        out = io.StringIO()
        call_command('web_push_operational_alerts', '--global', '--json', stdout=out)

        data = json.loads(out.getvalue())
        self.assertIsInstance(data, dict)
        self.assertEqual(data['mode'], 'DRY_RUN')
        self.assertEqual(data['scopes_processed'], 1)

    def test_command_hours_bounds(self):
        # 14. hours abaixo do mínimo é rejeitado ou tratado conforme contrato;
        # 15. hours acima do máximo é rejeitado ou tratado conforme contrato;
        from django.core.management.base import CommandError
        with self.assertRaisesMessage(CommandError, 'hours deve estar entre 1 e 720'):
            call_command('web_push_operational_alerts', '--global', '--hours', '0')

        with self.assertRaisesMessage(CommandError, 'hours deve estar entre 1 e 720'):
            call_command('web_push_operational_alerts', '--global', '--hours', '721')

    def test_command_stale_pending_bounds(self):
        # 16. stale-pending-minutes abaixo e acima dos limites;
        from django.core.management.base import CommandError
        with self.assertRaisesMessage(CommandError, 'stale-pending-minutes deve estar entre 5 e 10080'):
            call_command('web_push_operational_alerts', '--global', '--stale-pending-minutes', '4')

        with self.assertRaisesMessage(CommandError, 'stale-pending-minutes deve estar entre 5 e 10080'):
            call_command('web_push_operational_alerts', '--global', '--stale-pending-minutes', '10081')

    def test_command_stale_sending_bounds(self):
        # 17. stale-sending-minutes abaixo e acima dos limites;
        from django.core.management.base import CommandError
        with self.assertRaisesMessage(CommandError, 'stale-sending-minutes deve estar entre 5 e 10080'):
            call_command('web_push_operational_alerts', '--global', '--stale-sending-minutes', '4')

        with self.assertRaisesMessage(CommandError, 'stale-sending-minutes deve estar entre 5 e 10080'):
            call_command('web_push_operational_alerts', '--global', '--stale-sending-minutes', '10081')

    def test_command_invalid_band_friendly_error(self):
        # 18. banda inexistente gera erro amigável;
        from django.core.management.base import CommandError
        with self.assertRaisesMessage(CommandError, 'Banda com slug invalid-slug não encontrada'):
            call_command('web_push_operational_alerts', '--band-slug', 'invalid-slug')

    def test_command_no_sensitive_data(self):
        # 19. saída humana não contém dados sensíveis;
        # 20. saída JSON não contém dados sensíveis;
        import io, json

        out_human = io.StringIO()
        call_command('web_push_operational_alerts', '--global', stdout=out_human)
        human_str = out_human.getvalue().lower()

        out_json = io.StringIO()
        call_command('web_push_operational_alerts', '--global', '--json', stdout=out_json)
        json_str = out_json.getvalue().lower()

        banned_words = ['endpoint', 'p256dh', 'auth', 'vapid', 'recipient', 'username', 'e-mail', 'payload', 'cookie']
        for word in banned_words:
            self.assertNotIn(word, human_str)
            self.assertNotIn(word, json_str)

    def test_command_no_stacktrace_on_errors_json(self):
        # 21. erros não exibem stacktrace;
        with patch('core.management.commands.web_push_operational_alerts.plan_web_push_operational_alerts') as mock_plan:
            mock_plan.side_effect = Exception("SEGREDO_INTERNO_DATABASE_PASSWORD")
            import io, json
            out_json = io.StringIO()
            call_command('web_push_operational_alerts', '--global', '--json', stdout=out_json)
            data = json.loads(out_json.getvalue())
            self.assertEqual(data['errors'], 1)
            self.assertEqual(data['results'][0]['error_code'], 'scope_processing_failed')
            self.assertNotIn("SEGREDO_INTERNO_DATABASE_PASSWORD", out_json.getvalue())
            self.assertNotIn("Traceback", out_json.getvalue())

    @patch('core.models.Notification.objects.create')
    @patch('core.models.WebPushDelivery.objects.create')
    @patch('requests.post')
    def test_command_no_side_effects(self, mock_post, mock_delivery, mock_notification):
        # 23. nenhuma Notification é criada;
        # 24. nenhuma WebPushDelivery é criada;
        # 25. nenhuma chamada de rede é feita.
        import io
        call_command('web_push_operational_alerts', '--global', '--execute', stdout=io.StringIO())
        mock_post.assert_not_called()
        mock_delivery.assert_not_called()
        mock_notification.assert_not_called()

    @patch('core.services.web_push_alerts.build_web_push_operational_alerts')
    def test_band_plan_and_apply_use_band_id_dedupe_key(self, mock_build):
        mock_build.return_value = [
            {"code": "test_code", "severity": "WARNING", "title": "t", "message": "m", "description": "d", "action_required": False, "recommended_action": "a", "count": 1}
        ]
        band = Band.objects.create(name="dedupe-band", slug="dedupe-band")
        plan = plan_web_push_operational_alerts(
            band_slug=band.slug, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15
        )
        self.assertEqual(len(plan['to_open']), 1)
        self.assertTrue(plan['to_open'][0]['dedupe_key'].startswith(f"band:{band.id}:"))

        result = apply_web_push_operational_alert_plan(plan)
        self.assertEqual(result['errors'], 0)
        self.assertEqual(result['opened'], 1)

    def test_band_apply_accepts_matching_band_id_key(self):
        band = Band.objects.create(name="matching-id-band", slug="matching-id-band")
        plan = {
            "scope": {"scope_type": "BAND", "band_slug": band.slug},
            "to_open": [
                {
                    "dedupe_key": f"band:{band.id}:test_code",
                    "severity": "INFO",
                    "code": "test_code",
                    "message": "msg",
                    "title": "t",
                    "description": "d",
                    "action_required": False,
                    "recommended_action": "action",
                    "current_count": 1
                }
            ],
            "to_update": [], "to_resolve": [], "unchanged": []
        }
        result = apply_web_push_operational_alert_plan(plan, execute=True)
        self.assertEqual(result['errors'], 0)
        self.assertEqual(result['opened'], 1)

    def test_band_apply_rejects_other_band_id_key(self):
        band1 = Band.objects.create(name="dedupe-reject-b1", slug="dedupe-reject-b1")
        band2 = Band.objects.create(name="dedupe-reject-b2", slug="dedupe-reject-b2")
        plan = {
            "scope": {"scope_type": "BAND", "band_slug": band1.slug},
            "to_open": [
                {
                    "dedupe_key": f"band:{band2.id}:test_code",
                    "severity": "INFO",
                    "code": "test_code",
                    "message": "msg",
                    "title": "t",
                    "description": "d",
                    "action_required": False,
                    "recommended_action": "action",
                    "current_count": 1
                }
            ],
            "to_update": [], "to_resolve": [], "unchanged": []
        }
        with self.assertRaisesMessage(ValueError, "dedupe_key incompatible with BAND scope"):
            apply_web_push_operational_alert_plan(plan, execute=True)
        self.assertEqual(WebPushOperationalAlert.objects.count(), 0)

    def test_band_apply_does_not_use_slug_as_dedupe_key(self):
        band = Band.objects.create(name="dedupe-b-slug", slug="dedupe-b-slug")
        plan = {
            "scope": {"scope_type": "BAND", "band_slug": band.slug},
            "to_open": [
                {
                    "dedupe_key": f"band:{band.slug}:test_code",
                    "severity": "INFO",
                    "code": "test_code",
                    "message": "msg",
                    "title": "t",
                    "description": "d",
                    "action_required": False,
                    "recommended_action": "action",
                    "current_count": 1
                }
            ],
            "to_update": [], "to_resolve": [], "unchanged": []
        }
        with self.assertRaisesMessage(ValueError, "dedupe_key incompatible with BAND scope"):
            apply_web_push_operational_alert_plan(plan, execute=True)

    def test_global_dedupe_key_regression(self):
        plan = {
            "scope": {"scope_type": "GLOBAL", "band_slug": None},
            "to_open": [
                {
                    "dedupe_key": "global:test_code",
                    "severity": "INFO",
                    "code": "test_code",
                    "message": "msg",
                    "title": "t",
                    "description": "d",
                    "action_required": False,
                    "recommended_action": "action",
                    "current_count": 1
                }
            ],
            "to_update": [], "to_resolve": [], "unchanged": []
        }
        result = apply_web_push_operational_alert_plan(plan, execute=True)
        self.assertEqual(result['errors'], 0)
