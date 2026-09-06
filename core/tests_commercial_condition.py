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

    def test_minha_assinatura_ui_partnership_scenarios(self):
        """
        PARCERIA-02C: Testes de interface da página Minha Assinatura (/relatorios/assinatura/):
        1. Parceria Básico:
           - Exibe Plano Atual Básico
           - Exibe Status Ativo
           - Exibe Valor Isento
           - Exibe Condição Comercial: Parceria
           - Exibe Início formatado
           - Exibe Acesso: Sem prazo definido
           - Exibe Forma de Pagamento: Não se aplica
           - Exibe Renovação Automática: Não se aplica
           - Não exibe link/botão de regularização, renovação, cancelamento ou reativação
           - Não exibe controle Editar no KPI de pagamento
           - Não renderiza o modal de forma de pagamento
        2. Parceria Avançado:
           - Mesmas blindagens, exibindo Plano Atual Avançado
        3. Blindagem contra dados residuais legados:
           - contracted_value residual ignorado (renderiza Isento)
           - next_due_date no passado ignorada (não renderiza alerta de vencimento nem suspensão)
           - BillingRecord pendente com gateway_invoice_url não renderiza CTA de regularização
        4. Histórico com pagamentos legados anteriores:
           - Mantém tabela de histórico preservada
        5. Histórico vazio em parceria:
           - Exibe empty state neutro específico de parceria
        6. Regressão visual de PAGO:
           - Mantém rótulos originais: Ciclo, Próxima Cobrança, Formas de Pagamento, botão Editar, modal e botões de ação
        """
        from django.test import Client
        from django.urls import reverse
        from core.models import User

        client = Client()

        # 1. Parceria Básico
        user_basic = User.objects.create_user(
            username="user_part_basic",
            email="upb@teste.com",
            password="pass",
            role="PRODUTOR",
            band=self.band_basic
        )
        sub_basic = BandSubscription.objects.create(
            band=self.band_basic,
            plan_name="Básico",
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            start_date=datetime.date(2026, 1, 1),
            contracted_value=Decimal("0.00")
        )

        client.force_login(user_basic)
        url_basic = reverse("minha_assinatura", kwargs={"band_slug": self.band_basic.slug})
        resp_basic = client.get(url_basic)
        self.assertEqual(resp_basic.status_code, 200)
        content_basic = resp_basic.content.decode("utf-8")

        # Verificações básicas
        self.assertIn("Básico", content_basic)
        self.assertIn("Ativo", content_basic)
        self.assertIn("Isento", content_basic)
        self.assertIn("Condição Comercial", content_basic)
        self.assertIn("Parceria", content_basic)
        self.assertIn("Sem prazo definido", content_basic)
        self.assertIn("Não se aplica", content_basic)
        self.assertIn("01/01/2026", content_basic)

        # Não deve conter botões/controles de pagamento ou cancelamento
        self.assertNotIn("modalFormaPagamento", content_basic)
        self.assertNotIn("Regularizar Pagamento", content_basic)
        self.assertNotIn("Cancelar Assinatura", content_basic)
        self.assertNotIn("Reativar Assinatura", content_basic)
        self.assertNotIn("data-bs-target=\"#modalFormaPagamento\"", content_basic)
        # Empty state de histórico específico
        self.assertIn("Nenhum pagamento registrado. Esta conta opera sob condição de Parceria.", content_basic)

        # 2. Parceria Avançado
        user_adv = User.objects.create_user(
            username="user_part_adv",
            email="upa@teste.com",
            password="pass",
            role="PRODUTOR",
            band=self.band_advanced
        )
        sub_adv = BandSubscription.objects.create(
            band=self.band_advanced,
            plan_name="Avançado",
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            start_date=datetime.date(2026, 2, 1),
            contracted_value=Decimal("0.00")
        )
        client.force_login(user_adv)
        url_adv = reverse("minha_assinatura", kwargs={"band_slug": self.band_advanced.slug})
        resp_adv = client.get(url_adv)
        self.assertEqual(resp_adv.status_code, 200)
        content_adv = resp_adv.content.decode("utf-8")
        self.assertIn("Avançado", content_adv)
        self.assertIn("Isento", content_adv)
        self.assertIn("Parceria", content_adv)
        self.assertIn("Sem prazo definido", content_adv)
        self.assertNotIn("modalFormaPagamento", content_adv)

        # 3. Blindagem contra dados residuais legados em parceria
        band_resid = Band.objects.create(name="Banda Residual", slug="banda-residual", is_active=True)
        user_resid = User.objects.create_user(
            username="user_resid",
            email="uresid@teste.com",
            password="pass",
            role="PRODUTOR",
            band=band_resid
        )
        sub_resid = BandSubscription.objects.create(
            band=band_resid,
            plan_name="Avançado",
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP,
            status="ATIVO",
            contracted_value=Decimal("999.00"),
            next_due_date=timezone.localdate() - datetime.timedelta(days=30),
            billing_cycle="ANUAL",
            auto_renew=True
        )
        # BillingRecord pendente residual com link de fatura
        BillingRecord.objects.create(
            band=band_resid,
            subscription=sub_resid,
            amount=Decimal("999.00"),
            due_date=timezone.localdate() - datetime.timedelta(days=30),
            status="PENDENTE",
            gateway_invoice_url="https://gateway.asaas.com/i/residual123"
        )
        client.force_login(user_resid)
        url_resid = reverse("minha_assinatura", kwargs={"band_slug": band_resid.slug})
        resp_resid = client.get(url_resid)
        self.assertEqual(resp_resid.status_code, 200)
        content_resid = resp_resid.content.decode("utf-8")

        # Não deve mostrar R$ 999,00 no KPI de Valor (deve mostrar Isento)
        self.assertIn("Isento", content_resid)
        self.assertNotIn(">R$ 999,00<", content_resid)
        self.assertIn("Sem prazo definido", content_resid)
        # Não deve renderizar alertas de atraso nem modal de regularização
        self.assertNotIn("Regularizar Pagamento", content_resid)
        self.assertNotIn("modalFormaPagamento", content_resid)

        # 4. Histórico com pagamentos legados anteriores preservados
        BillingRecord.objects.create(
            band=band_resid,
            subscription=sub_resid,
            reference_period="01/2025",
            amount=Decimal("199.90"),
            due_date=datetime.date(2025, 1, 10),
            paid_date=datetime.date(2025, 1, 10),
            status="PAGO",
            payment_method="CARTAO"
        )
        resp_resid_hist = client.get(url_resid)
        content_resid_hist = resp_resid_hist.content.decode("utf-8")
        self.assertIn("01/2025", content_resid_hist)
        self.assertIn("199,90", content_resid_hist)
        self.assertIn("Pago", content_resid_hist)

        # 6. Regressão visual de PAGO
        user_paid = User.objects.create_user(
            username="user_paid",
            email="upaid@teste.com",
            password="pass",
            role="PRODUTOR",
            band=self.band_paid
        )
        sub_paid = BandSubscription.objects.create(
            band=self.band_paid,
            plan_name="Básico",
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
            status="ATIVO",
            billing_cycle="MENSAL",
            payment_method_preference="CARTAO",
            contracted_value=Decimal("150.00"),
            start_date=datetime.date(2026, 1, 1),
            next_due_date=datetime.date(2026, 10, 1),
            auto_renew=True
        )
        pm_paid = GatewayPaymentMethod.objects.create(
            subscription=sub_paid,
            gateway_provider="ASAAS",
            gateway_customer_id="cus_paid_test",
            card_brand="Visa",
            card_last4="4321",
            expiration_month="12",
            expiration_year="2028",
            is_active=True
        )
        pm_paid.set_token("tok_paid_secret")
        pm_paid.save()

        client.force_login(user_paid)
        url_paid = reverse("minha_assinatura", kwargs={"band_slug": self.band_paid.slug})
        resp_paid = client.get(url_paid)
        self.assertEqual(resp_paid.status_code, 200)
        content_paid = resp_paid.content.decode("utf-8")

        # Deve conter dados normais de PAGO
        self.assertIn("Ciclo", content_paid)
        self.assertIn("Mensal", content_paid)
        self.assertIn("R$ 150,00", content_paid)
        self.assertIn("Próxima Cobrança", content_paid)
        self.assertIn("01/10/2026", content_paid)
        self.assertIn("Visa", content_paid)
        self.assertIn("•••• 4321", content_paid)
        self.assertIn("modalFormaPagamento", content_paid)
        self.assertIn("data-bs-target=\"#modalFormaPagamento\"", content_paid)
        self.assertIn("Editar", content_paid)

