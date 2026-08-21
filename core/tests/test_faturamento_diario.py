import datetime
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from core.models import Band, BandSubscription, BillingRecord
from django.core.management import call_command

User = get_user_model()

class FaturamentoDiarioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin_test', password='password123', is_superuser=True, is_staff=True)
        self.client = Client()
        self.client.login(username='admin_test', password='password123')
        self.band = Band.objects.create(name='Banda Teste', slug='banda-teste')
        
    def test_01_checkbox_default_false(self):
        # 3. Valor padrão desmarcado.
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL')
        self.assertFalse(sub.auto_renew)

    def test_02_gera_fatura_7_dias(self):
        # 4. Assinatura ativa gera fatura com sete dias de antecedência.
        today = timezone.localdate()
        target = today + datetime.timedelta(days=7)
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=target, status='ATIVO')
        call_command('process_subscription_billings')
        self.assertTrue(BillingRecord.objects.filter(subscription=sub).exists())

    def test_03_nao_gera_fatura_8_dias(self):
        # 5. Não gera com oito dias.
        today = timezone.localdate()
        target = today + datetime.timedelta(days=8)
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=target, status='ATIVO')
        call_command('process_subscription_billings')
        self.assertFalse(BillingRecord.objects.filter(subscription=sub).exists())
        
    def test_04_gera_fatura_vencida(self):
        # 6. Gera fatura vencida que ainda não exista.
        today = timezone.localdate()
        target = today - datetime.timedelta(days=2)
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=target, status='ATIVO')
        call_command('process_subscription_billings')
        self.assertTrue(BillingRecord.objects.filter(subscription=sub).exists())
        
    def test_05_idempotencia_nao_duplica(self):
        # 7. Processo diário não duplica faturas.
        today = timezone.localdate()
        target = today + datetime.timedelta(days=2)
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=target, status='ATIVO')
        call_command('process_subscription_billings')
        call_command('process_subscription_billings')
        call_command('process_subscription_billings')
        self.assertEqual(BillingRecord.objects.filter(subscription=sub).count(), 1)
        
    def test_06_badges_status(self):
        # 9, 10, 11
        today = timezone.localdate()
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', status='ATIVO')
        # Vencido
        rec1 = BillingRecord.objects.create(subscription=sub, band=self.band, due_date=today - datetime.timedelta(days=1), amount=100, status='PENDENTE')
        self.assertEqual(rec1.dynamic_status, 'VENCIDO')
        # Prox Vencimento
        rec2 = BillingRecord.objects.create(subscription=sub, band=self.band, due_date=today + datetime.timedelta(days=1), amount=100, status='PENDENTE')
        self.assertEqual(rec2.dynamic_status, 'PROX_VENCIMENTO')
        # Pago
        rec3 = BillingRecord.objects.create(subscription=sub, band=self.band, due_date=today + datetime.timedelta(days=2), amount=100, status='PAGO')
        self.assertEqual(rec3.dynamic_status, 'PAGO')

    def test_07_pagamento_preenche_paid_date(self):
        # 13, 15, 18, 22
        # Data simulada: 20/08/2026. Vencimento: 01/08/2026
        # Let's mock today
        due = datetime.date(2026, 8, 1)
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=due, status='ATIVO', auto_renew=True)
        rec = BillingRecord.objects.create(subscription=sub, band=self.band, due_date=due, amount=100, status='PENDENTE')
        
        url = reverse('admin_painel:cobrancas_pagar', args=[rec.id])
        resp = self.client.post(url, {'paid_date': '2026-08-20', 'payment_method': 'PIX', 'notes': 'Test'})
        
        rec.refresh_from_db()
        sub.refresh_from_db()
        
        self.assertEqual(rec.status, 'PAGO')
        self.assertEqual(rec.paid_date, datetime.date(2026, 8, 20))
        self.assertEqual(sub.next_due_date, datetime.date(2026, 9, 1))
        
    def test_08_pagamento_sem_auto_renew(self):
        # 21. auto_renew=False não altera o próximo vencimento.
        due = datetime.date(2026, 8, 1)
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=due, status='ATIVO', auto_renew=False)
        rec = BillingRecord.objects.create(subscription=sub, band=self.band, due_date=due, amount=100, status='PENDENTE')
        
        url = reverse('admin_painel:cobrancas_pagar', args=[rec.id])
        resp = self.client.post(url, {'paid_date': '2026-08-20'})
        
        rec.refresh_from_db()
        sub.refresh_from_db()
        
        self.assertEqual(rec.status, 'PAGO')
        self.assertEqual(sub.next_due_date, due) # Did not change!

    def test_09_renovacao_anual(self):
        # 17. Renovação anual avança doze meses.
        due = datetime.date(2026, 8, 1)
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='ANUAL', next_due_date=due, status='ATIVO', auto_renew=True)
        rec = BillingRecord.objects.create(subscription=sub, band=self.band, due_date=due, amount=100, status='PENDENTE')
        
        url = reverse('admin_painel:cobrancas_pagar', args=[rec.id])
        self.client.post(url, {'paid_date': '2026-08-20'})
        
        sub.refresh_from_db()
        self.assertEqual(sub.next_due_date, datetime.date(2027, 8, 1))

    def test_10_dia_31_ajuste(self):
        # 20. Data de dia 31 é ajustada corretamente.
        due = datetime.date(2027, 1, 31)
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=due, status='ATIVO', auto_renew=True)
        rec = BillingRecord.objects.create(subscription=sub, band=self.band, due_date=due, amount=100, status='PENDENTE')
        
        url = reverse('admin_painel:cobrancas_pagar', args=[rec.id])
        self.client.post(url, {'paid_date': '2027-02-15'})
        
        sub.refresh_from_db()
        self.assertEqual(sub.next_due_date, datetime.date(2027, 2, 28))

    def test_11_assinatura_desativada(self):
        # 23 e 24. Excluída ou desativada não gera.
        today = timezone.localdate()
        target = today + datetime.timedelta(days=2)
        sub1 = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=target, status='DESATIVADO')
        sub2 = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=target, status='ATIVO', is_deleted=True)
        
        call_command('process_subscription_billings')
        self.assertFalse(BillingRecord.objects.filter(subscription=sub1).exists())
        self.assertFalse(BillingRecord.objects.filter(subscription=sub2).exists())
        
    def test_12_pagamento_duplicado(self):
        # 14. Pagamento duplicado impedido.
        due = datetime.date(2026, 8, 1)
        sub = BandSubscription.objects.create(band=self.band, billing_cycle='MENSAL', next_due_date=due, status='ATIVO', auto_renew=True)
        rec = BillingRecord.objects.create(subscription=sub, band=self.band, due_date=due, amount=100, status='PAGO')
        
        url = reverse('admin_painel:cobrancas_pagar', args=[rec.id])
        self.client.post(url, {'paid_date': '2026-08-20'})
        
        sub.refresh_from_db()
        # Next due date shouldn't have changed because it was already PAGO
        self.assertEqual(sub.next_due_date, due)
