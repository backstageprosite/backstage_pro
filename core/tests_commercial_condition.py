import datetime
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from core.models import Band, BandSubscription


class CommercialConditionTests(TestCase):
    def setUp(self):
        self.band_basic = Band.objects.create(
            name="Banda Básica Parceria",
            slug="banda-basica-parceria",
            plan_type=Band.PlanType.BASICO,
            is_active=True
        )
        self.band_advanced = Band.objects.create(
            name="Banda Avançada Parceria",
            slug="banda-avancada-parceria",
            plan_type=Band.PlanType.AVANCADO,
            is_active=True
        )
        self.band_paid = Band.objects.create(
            name="Banda Paga",
            slug="banda-paga",
            plan_type=Band.PlanType.BASICO,
            is_active=True
        )

    def test_default_commercial_condition_is_paid(self):
        """Nova BandSubscription sem commercial_condition explícito deve assumir PAGO."""
        sub = BandSubscription.objects.create(
            band=self.band_paid,
            billing_cycle="MENSAL",
            contracted_value=Decimal("300.00"),
            status="ATIVO",
            auto_renew=True,
            next_due_date=timezone.localdate() + datetime.timedelta(days=10)
        )
        self.assertEqual(sub.commercial_condition, BandSubscription.COMMERCIAL_CONDITION_PAID)
        self.assertEqual(sub.commercial_condition, "PAGO")
        self.assertTrue(sub.is_paid_commercial_condition)
        self.assertFalse(sub.is_partnership)

    def test_paid_subscription_overdue_behavior_preserved(self):
        """Assinatura PAGO continua com o comportamento original de tolerância e suspensão."""
        today = timezone.localdate()
        sub_overdue_4d = BandSubscription.objects.create(
            band=self.band_paid,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
            status="ATIVO",
            auto_renew=True,
            next_due_date=today - datetime.timedelta(days=4)
        )
        self.assertEqual(sub_overdue_4d.days_overdue(), 4)
        self.assertTrue(sub_overdue_4d.is_overdue_tolerance)
        self.assertFalse(sub_overdue_4d.is_financially_suspended)
        self.assertTrue(self.band_paid.has_active_subscription)

        sub_overdue_5d = BandSubscription.objects.create(
            band=self.band_paid,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
            status="ATIVO",
            auto_renew=True,
            next_due_date=today - datetime.timedelta(days=5)
        )
        self.assertEqual(sub_overdue_5d.days_overdue(), 5)
        self.assertFalse(sub_overdue_5d.is_overdue_tolerance)
        self.assertTrue(sub_overdue_5d.is_financially_suspended)
        self.assertFalse(self.band_paid.has_active_subscription)

    def test_partnership_subscription_properties_and_financial_guards(self):
        """Assinatura PARCERIA possui flags corretas e ignora atraso e suspensão."""
        today = timezone.localdate()
        sub = BandSubscription.objects.create(
            band=self.band_basic,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            auto_renew=False,
            next_due_date=today - datetime.timedelta(days=60)
        )
        self.assertTrue(sub.is_partnership)
        self.assertFalse(sub.is_paid_commercial_condition)

        self.assertEqual(sub.days_overdue(), 0)
        self.assertFalse(sub.is_overdue_tolerance)
        self.assertFalse(sub.is_financially_suspended)

        did_expire = sub.check_and_sync_auto_expiration()
        self.assertFalse(did_expire)
        sub.refresh_from_db()
        self.assertEqual(sub.status, "ATIVO")

        self.assertTrue(self.band_basic.has_active_subscription)

    def test_plans_remain_independent_with_partnership(self):
        """Planos Básico e Avançado preservam suas regras e permissões independentemente da parceria."""
        sub_basic = BandSubscription.objects.create(
            band=self.band_basic,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            auto_renew=False
        )
        sub_advanced = BandSubscription.objects.create(
            band=self.band_advanced,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            auto_renew=False
        )

        self.assertTrue(self.band_basic.is_basic)
        self.assertFalse(self.band_basic.is_advanced)
        self.assertTrue(self.band_basic.has_active_subscription)

        self.assertTrue(self.band_advanced.is_advanced)
        self.assertFalse(self.band_advanced.is_basic)
        self.assertTrue(self.band_advanced.has_active_subscription)

    def test_partnership_with_very_old_due_date_does_not_suspend_or_expire(self):
        """Cenário explícito: next_due_date no passado distante não suspende, não expira e mantém acesso."""
        ancient_date = timezone.localdate() - datetime.timedelta(days=365 * 2)
        sub = BandSubscription.objects.create(
            band=self.band_basic,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            auto_renew=False,
            next_due_date=ancient_date
        )

        self.assertEqual(sub.days_overdue(), 0)
        self.assertFalse(sub.is_overdue_tolerance)
        self.assertFalse(sub.is_financially_suspended)

        sub.check_and_sync_auto_expiration()
        sub.refresh_from_db()
        self.assertEqual(sub.status, "ATIVO")
        self.assertTrue(self.band_basic.has_active_subscription)
