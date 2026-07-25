from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import Band, Show, BandDashboardPendingItem
import datetime

User = get_user_model()

class PendingItemsAndDashboardTest(TestCase):
    def setUp(self):
        # Create bands
        self.band_a = Band.objects.create(name="Band A", slug="band-a")
        self.band_b = Band.objects.create(name="Band B", slug="band-b")
        
        # Create users
        self.produtor_a = User.objects.create_user(username="prodA", password="123", email="proda@test.com", role="PRODUTOR", band=self.band_a)
        self.integrante_a = User.objects.create_user(username="intA", password="123", email="inta@test.com", role="INTEGRANTE", band=self.band_a)
        
        self.produtor_b = User.objects.create_user(username="prodB", password="123", email="prodb@test.com", role="PRODUTOR", band=self.band_b)
        
        # Common dates
        self.today = datetime.date.today()
        self.tomorrow = self.today + datetime.timedelta(days=1)
        self.yesterday = self.today - datetime.timedelta(days=1)
        self.next_week = self.today + datetime.timedelta(days=7)
        
    def test_dashboard_limits(self):
        """Dashboard should show exactly max 4 upcoming shows and 4 pending items"""
        # Create 5 shows for tomorrow
        for i in range(5):
            Show.objects.create(band=self.band_a, title=f"Show {i}", date=self.tomorrow, show_time=datetime.time(20,0))
            
        # Create 5 pending items with show
        for i in range(5):
            show = Show.objects.create(band=self.band_a, title=f"Show {i}", date=self.tomorrow, show_time=datetime.time(20,0))
            BandDashboardPendingItem.objects.create(band=self.band_a, description=f"Pending {i}", show=show, created_by=self.produtor_a)
            
        self.client.login(username="prodA", password="123")
        response = self.client.get(reverse('dashboard', args=[self.band_a.slug]))
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['shows_proximos']), 4)
        self.assertEqual(len(response.context['dashboard_pending_items']), 4)
        
        # Test Integrante A limits (should not have pending items)
        self.client.login(username="intA", password="123")
        response = self.client.get(reverse('dashboard', args=[self.band_a.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context.get('dashboard_pending_items'))
        self.assertEqual(len(response.context['shows_proximos']), 4)
        
    def test_pending_list_view_access(self):
        """Test if pendencias view loads correctly for members of the band"""
        # Produtor A accesses Band A
        self.client.login(username="prodA", password="123")
        response = self.client.get(reverse('pendencias', args=[self.band_a.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Adicionar') # Produtor sees add button
        
        # Integrante A accesses Band A (should be blocked)
        self.client.login(username="intA", password="123")
        response = self.client.get(reverse('pendencias', args=[self.band_a.slug]))
        self.assertEqual(response.status_code, 403)
        
        # Produtor B tries to access Band A
        self.client.login(username="prodB", password="123")
        response = self.client.get(reverse('pendencias', args=[self.band_a.slug]))
        self.assertEqual(response.status_code, 403)
        
    def test_pending_items_ordering(self):
        """Test the logic for ordering pending items"""
        # Shows
        show_past = Show.objects.create(band=self.band_a, title="Past", date=self.yesterday, show_time=datetime.time(20,0))
        show_today = Show.objects.create(band=self.band_a, title="Today", date=self.today, show_time=datetime.time(20,0))
        show_future = Show.objects.create(band=self.band_a, title="Future", date=self.tomorrow, show_time=datetime.time(20,0))
        show_no_date = Show.objects.create(band=self.band_a, title="No date", show_time=datetime.time(20,0))
        
        # Pendencies
        p1 = BandDashboardPendingItem.objects.create(band=self.band_a, description="Another no date show", show=show_no_date, created_by=self.produtor_a)
        p2 = BandDashboardPendingItem.objects.create(band=self.band_a, description="Past show", show=show_past, created_by=self.produtor_a)
        p3 = BandDashboardPendingItem.objects.create(band=self.band_a, description="Future show", show=show_future, created_by=self.produtor_a)
        p4 = BandDashboardPendingItem.objects.create(band=self.band_a, description="Today show", show=show_today, created_by=self.produtor_a)
        p5 = BandDashboardPendingItem.objects.create(band=self.band_a, description="No date show", show=show_no_date, created_by=self.produtor_a)
        
        # Fetch ordered items
        ordered_items = list(BandDashboardPendingItem.objects.filter(band=self.band_a).with_ordering())
        
        # Expected order: Today, Future, Past, No date
        
        self.assertEqual(ordered_items[0], p4) # Today
        self.assertEqual(ordered_items[1], p3) # Future
        self.assertEqual(ordered_items[2], p2) # Past
        self.assertIn(ordered_items[3], [p5, p1])
        
    def test_post_redirects_back_to_next(self):
        """Test if POST operations respect the 'next' parameter"""
        show_test = Show.objects.create(band=self.band_a, title="Test", date=self.today, show_time=datetime.time(20,0))
        p1 = BandDashboardPendingItem.objects.create(band=self.band_a, description="Task to delete", show=show_test, created_by=self.produtor_a)
        
        self.client.login(username="prodA", password="123")
        response = self.client.post(
            reverse('delete_dashboard_pending_item', args=[self.band_a.slug, p1.id]),
            {'next': f'/{self.band_a.slug}/pendencias/'}
        )
        self.assertRedirects(response, f'/{self.band_a.slug}/pendencias/')
