from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Band, BandSubscription, SubscriptionCancellationFeedback, User, UserBandMembership


class SubscriptionCancellationFeedbackTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            username='empresaria_feedback', email='owner@example.com', password='testpass123',
        )
        self.admin = User.objects.create_superuser(
            username='admin_feedback', email='admin@example.com', password='testpass123',
        )
        self.band_a = Band.objects.create(name='Banda Alfa', slug='banda-alfa-feedback')
        self.band_b = Band.objects.create(name='Banda Beta', slug='banda-beta-feedback')
        for band in (self.band_a, self.band_b):
            UserBandMembership.objects.create(
                user=self.owner, band=band, role='EMPRESARIO', is_active=True,
            )
        self.sub_a = self.make_subscription(self.band_a, 'sub_feedback_alfa')
        self.sub_b = self.make_subscription(self.band_b, 'sub_feedback_beta')
        self.url = f'/{self.band_a.slug}/relatorios/assinatura/'
        self.client = Client()
        self.client.force_login(self.owner)

    @staticmethod
    def make_subscription(band, gateway_id):
        return BandSubscription.objects.create(
            band=band, plan_name='Avançado', billing_cycle='MENSAL',
            contracted_value=Decimal('49.90'), status='ATIVO',
            next_due_date=timezone.localdate() + timedelta(days=30), auto_renew=True,
            gateway_provider='ASAAS', gateway_subscription_id=gateway_id,
            gateway_customer_id='cus_feedback_owner',
        )

    def payload(self, **overrides):
        data = {
            'action': 'cancel_subscription',
            'subscription_id': str(self.sub_a.id),
            'reason': 'Deixei de empresariar esta banda.',
        }
        data.update(overrides)
        return data

    def test_modal_requires_reason_and_has_two_clear_actions(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'name="reason"')
        self.assertContains(response, 'maxlength="1000"')
        self.assertContains(response, 'Cancelar plano')
        self.assertContains(response, '>Voltar</button>')

    @patch('core.services.payments.asaas.client.AsaasClient.cancel_subscription')
    @patch('core.services.payments.asaas.client.AsaasClient.get_subscription')
    def test_confirmation_records_only_selected_band_and_is_idempotent(self, mock_get, mock_cancel):
        mock_get.return_value = {
            'id': self.sub_a.gateway_subscription_id, 'customer': 'cus_feedback_owner',
            'status': 'ACTIVE', 'deleted': False,
        }
        mock_cancel.return_value = (True, {'deleted': True})

        response = self.client.post(self.url, self.payload(), follow=True)
        self.assertEqual(response.status_code, 200)
        mock_cancel.assert_called_once_with(self.sub_a.gateway_subscription_id)
        self.sub_a.refresh_from_db()
        self.sub_b.refresh_from_db()
        self.assertTrue(self.sub_a.cancel_at_period_end)
        self.assertFalse(self.sub_b.cancel_at_period_end)
        self.assertTrue(self.sub_b.auto_renew)
        feedback = SubscriptionCancellationFeedback.objects.get()
        self.assertEqual(feedback.subscription_id, self.sub_a.id)
        self.assertEqual(feedback.band_name, self.band_a.name)
        self.assertEqual(feedback.requested_by, self.owner)
        self.assertEqual(feedback.reason, self.payload()['reason'])

        self.client.post(self.url, self.payload(), follow=True)
        self.assertEqual(SubscriptionCancellationFeedback.objects.count(), 1)
        mock_cancel.assert_called_once()

        self.client.force_login(self.admin)
        admin_response = self.client.get(reverse('admin_painel:assinaturas'))
        self.assertContains(admin_response, 'Deixei de empresariar esta banda.')
        self.assertContains(admin_response, self.band_a.name)

    @patch('core.services.payments.asaas.client.AsaasClient.cancel_subscription')
    @patch('core.services.payments.asaas.client.AsaasClient.get_subscription')
    def test_invalid_reason_or_stale_subscription_does_not_call_gateway(self, mock_get, mock_cancel):
        for payload in (
            self.payload(reason='  '),
            self.payload(reason='x' * 1001),
            self.payload(subscription_id=str(self.sub_b.id)),
        ):
            response = self.client.post(self.url, payload, follow=True)
            self.assertEqual(response.status_code, 200)
        mock_get.assert_not_called()
        mock_cancel.assert_not_called()
        self.sub_a.refresh_from_db()
        self.assertFalse(self.sub_a.cancel_at_period_end)
        self.assertFalse(SubscriptionCancellationFeedback.objects.exists())

    @patch('core.services.payments.asaas.client.AsaasClient.cancel_subscription')
    @patch('core.services.payments.asaas.client.AsaasClient.get_subscription')
    def test_gateway_failure_keeps_renewal_and_does_not_record_feedback(self, mock_get, mock_cancel):
        mock_get.return_value = {
            'id': self.sub_a.gateway_subscription_id, 'customer': 'cus_feedback_owner',
            'status': 'ACTIVE', 'deleted': False,
        }
        mock_cancel.return_value = (False, {'errors': ['unavailable']})
        self.client.post(self.url, self.payload(), follow=True)
        self.sub_a.refresh_from_db()
        self.assertTrue(self.sub_a.auto_renew)
        self.assertFalse(self.sub_a.cancel_at_period_end)
        self.assertFalse(SubscriptionCancellationFeedback.objects.exists())

    def test_non_admin_cannot_read_feedback(self):
        SubscriptionCancellationFeedback.objects.create(
            subscription=self.sub_a, band=self.band_a, band_name=self.band_a.name,
            requested_by=self.owner, reason='Motivo privado',
        )
        response = self.client.get(reverse('admin_painel:assinaturas'))
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn('Motivo privado', response.content.decode('utf-8'))
