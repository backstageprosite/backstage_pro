from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, User, SupportTicket, SupportTicketMessage
from django.utils import timezone

class SupportContactTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.band = Band.objects.create(name='Test Band', slug='test-band', is_active=True)
        
        self.producer = User.objects.create_user(
            username='producer', 
            password='123',
            role='PRODUTOR',
            band=self.band
        )
        
        self.admin = User.objects.create_user(
            username='admin', 
            password='123',
            is_staff=True,
            is_superuser=True
        )

    def test_producer_create_ticket(self):
        self.client.login(username='producer', password='123')
        url = reverse('support_create', kwargs={'band_slug': self.band.slug})
        
        response = self.client.post(url, {
            'message': 'Hello, I have an issue.'
        })
        
        self.assertEqual(SupportTicket.objects.count(), 1)
        ticket = SupportTicket.objects.first()
        self.assertEqual(ticket.status, 'NEW')
        self.assertEqual(ticket.band, self.band)
        
        self.assertEqual(SupportTicketMessage.objects.count(), 1)
        msg = SupportTicketMessage.objects.first()
        self.assertEqual(msg.body, 'Hello, I have an issue.')
        self.assertEqual(msg.author, self.producer)

    def test_admin_reply_ticket(self):
        ticket = SupportTicket.objects.create(
            band=self.band,
            created_by=self.producer,
            status='NEW'
        )
        
        self.client.login(username='admin', password='123')
        url = reverse('admin_painel:support_detail', kwargs={'pk': ticket.pk})
        
        response = self.client.post(url, {
            'action': 'reply',
            'message': 'We are checking it.'
        })
        
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'WAITING_PRODUCER')
        self.assertEqual(SupportTicketMessage.objects.filter(sender_type='ADMIN').count(), 1)

    def test_reopen_ticket(self):
        ticket = SupportTicket.objects.create(
            band=self.band,
            created_by=self.producer,
            status='RESOLVED'
        )
        
        self.client.login(username='producer', password='123')
        url = reverse('support_reopen', kwargs={'band_slug': self.band.slug, 'pk': ticket.pk})
        
        response = self.client.post(url, {
            'message': 'Issue came back.'
        })
        
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'WAITING_ADMIN')
        self.assertEqual(SupportTicketMessage.objects.count(), 1)
