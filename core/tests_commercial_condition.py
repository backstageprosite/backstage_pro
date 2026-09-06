import datetime
from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from core.models import Band, BandSubscription, BillingRecord, AnnualPlanPurchase, AnnualRenewalNotice, EmailDelivery, GatewayPaymentMethod
from core.services.payments.renewal import AnnualRenewalService
from core.services.payments.methods import replace_active_gateway_payment_method
from core.services.payments.asaas.webhooks import reconcile_and_update_billing_record, handle_subscription_event


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

    def test_check_subscription_due_dates_ignores_partnership_completely(self):
        """
        Job check_subscription_due_dates ignora Parceria:
        Mesmo com dados deliberadamente inconsistentes (auto_renew=True, contracted_value>0, next_due_date no passado),
        não gera BillingRecord, não suspende e não envia e-mails transacionais.
        """
        today = timezone.localdate()
        sub_partnership = BandSubscription.objects.create(
            band=self.band_basic,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            billing_cycle="MENSAL",
            auto_renew=True,
            contracted_value=Decimal("500.00"),
            next_due_date=today - datetime.timedelta(days=10),
            billing_email="parceiro@teste.com"
        )
        sub_paid = BandSubscription.objects.create(
            band=self.band_paid,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
            status="ATIVO",
            billing_cycle="MENSAL",
            auto_renew=True,
            contracted_value=Decimal("300.00"),
            next_due_date=today + datetime.timedelta(days=2),
            billing_email="pago@teste.com"
        )

        call_command("check_subscription_due_dates")

        # Não deve haver BillingRecord para a parceria
        self.assertFalse(BillingRecord.objects.filter(subscription=sub_partnership).exists())
        # Deve haver BillingRecord para a assinatura paga
        self.assertTrue(BillingRecord.objects.filter(subscription=sub_paid).exists())

        # Não deve haver e-mail de suspensão financeira para a parceria
        self.assertFalse(EmailDelivery.objects.filter(recipient_email="parceiro@teste.com").exists())
        sub_partnership.refresh_from_db()
        self.assertEqual(sub_partnership.status, "ATIVO")

    def test_annual_renewal_notices_command_ignores_partnership(self):
        """
        process_annual_renewal_notices ignora Parceria mesmo se billing_cycle=ANUAL,
        auto_renew=True e na janela D-30.
        """
        today = timezone.localdate()
        target_due = today + datetime.timedelta(days=30)
        sub_partnership = BandSubscription.objects.create(
            band=self.band_basic,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            billing_cycle="ANUAL",
            auto_renew=True,
            next_due_date=target_due,
            billing_email="parceiro_anual@teste.com"
        )

        call_command("process_annual_renewal_notices", dry_run=True)

        self.assertFalse(AnnualRenewalNotice.objects.filter(band_subscription=sub_partnership).exists())
        self.assertFalse(EmailDelivery.objects.filter(recipient_email="parceiro_anual@teste.com").exists())

    def test_annual_renewal_service_direct_call_blocks_partnership(self):
        """
        Defesa em profundidade: Chamada direta ao AnnualRenewalService para uma Parceria
        retorna PARTNERSHIP_NOT_BILLABLE e não realiza nenhuma cobrança ou installment.
        """
        today = timezone.localdate()
        sub = BandSubscription.objects.create(
            band=self.band_basic,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            billing_cycle="ANUAL",
            auto_renew=True,
            next_due_date=today,
            gateway_customer_id="cus_part_test_01"
        )

        service = AnnualRenewalService()
        eligible, reason = service.is_eligible_for_renewal(sub)
        self.assertFalse(eligible)
        self.assertEqual(reason, "PARTNERSHIP_NOT_BILLABLE")

        with patch.object(service.client, "create_installment") as mock_inst, \
             patch.object(service.client, "pay_with_credit_card") as mock_pay:
            success, msg, purchase = service.process_subscription_renewal(sub)
            self.assertFalse(success)
            self.assertEqual(msg, "PARTNERSHIP_NOT_BILLABLE")
            self.assertIsNone(purchase)
            mock_inst.assert_not_called()
            mock_pay.assert_not_called()

    def test_legacy_webhooks_on_partnership_ignored_without_financial_side_effects(self):
        """
        Webhook legado recebido apontando para BillingRecord/Subscription de Parceria
        não altera status, não suspende e não envia e-mails financeiros.
        """
        today = timezone.localdate()
        sub = BandSubscription.objects.create(
            band=self.band_basic,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            auto_renew=False,
            next_due_date=today,
            gateway_provider="ASAAS",
            gateway_subscription_id="sub_part_webhook_123"
        )
        record = BillingRecord.objects.create(
            subscription=sub,
            band=self.band_basic,
            reference_period="09/2026",
            amount=Decimal("150.00"),
            due_date=today,
            status="PENDENTE",
            gateway_provider="ASAAS",
            gateway_payment_id="pay_part_overdue_999"
        )

        # 1. Teste PAYMENT_OVERDUE
        payload_overdue = {
            "event": "PAYMENT_OVERDUE",
            "payment": {
                "id": "pay_part_overdue_999",
                "status": "OVERDUE",
                "value": 150.00
            }
        }
        ok, msg = reconcile_and_update_billing_record(payload_overdue, "PAYMENT_OVERDUE")
        self.assertTrue(ok)
        self.assertFalse(EmailDelivery.objects.filter(email_type="PAYMENT_OVERDUE", related_object_id=str(record.id)).exists())
        sub.refresh_from_db()
        self.assertEqual(sub.status, "ATIVO")

        # 2. Teste PAYMENT_CREDIT_CARD_CAPTURE_REFUSED
        payload_cc_refused = {
            "event": "PAYMENT_CREDIT_CARD_CAPTURE_REFUSED",
            "payment": {
                "id": "pay_part_overdue_999",
                "refusalReason": "Cartão bloqueado"
            }
        }
        ok_cc, msg_cc = reconcile_and_update_billing_record(payload_cc_refused, "PAYMENT_CREDIT_CARD_CAPTURE_REFUSED")
        self.assertTrue(ok_cc)
        self.assertFalse(EmailDelivery.objects.filter(email_type="CREDIT_CARD_CAPTURE_REFUSED", related_object_id=str(record.id)).exists())

        # 3. Teste SUBSCRIPTION_INACTIVATED
        payload_sub = {
            "event": "SUBSCRIPTION_INACTIVATED",
            "subscription": {
                "id": "sub_part_webhook_123"
            }
        }
        ok_sub, msg_sub = handle_subscription_event(payload_sub, "SUBSCRIPTION_INACTIVATED")
        self.assertTrue(ok_sub)
        sub.refresh_from_db()
        # Não deve ser cancelada por webhook de gateway
        self.assertEqual(sub.status, "ATIVO")

    def test_replace_active_gateway_payment_method_blocks_partnership(self):
        """Tentativa de registrar cartão para assinatura em condição de parceria lança ValueError."""
        sub = BandSubscription.objects.create(
            band=self.band_basic,
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO"
        )
        with self.assertRaises(ValueError) as ctx:
            replace_active_gateway_payment_method(
                subscription=sub,
                credit_card_token="tok_test_part_123"
            )
        self.assertIn("partnership_not_billable", str(ctx.exception))
