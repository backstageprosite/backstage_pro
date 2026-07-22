from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import datetime
from .models import Band, Show, BandDashboardPendingItem

User = get_user_model()

class DashboardPendingItemsTests(TestCase):
    def setUp(self):
        # Create Band A
        self.band_a = Band.objects.create(name="Band A", slug="band-a", is_active=True)
        self.produtor_a = User.objects.create_user(username="prod_a", password="pwd", email="pa@test.com", role="PRODUTOR", band=self.band_a)
        self.integrante_a = User.objects.create_user(username="int_a", password="pwd", email="ia@test.com", role="INTEGRANTE", band=self.band_a)

        self.show_a = Show.objects.create(
            band=self.band_a,
            title="Show A",
            date=datetime.date.today(),
            show_time=datetime.time(20, 0),
            status='CONFIRMADO'
        )

        # Create Band B
        self.band_b = Band.objects.create(name="Band B", slug="band-b", is_active=True)
        self.produtor_b = User.objects.create_user(username="prod_b", password="pwd", email="pb@test.com", role="PRODUTOR", band=self.band_b)
        self.show_b = Show.objects.create(
            band=self.band_b,
            title="Show B",
            date=datetime.date.today(),
            show_time=datetime.time(20, 0),
            status='CONFIRMADO'
        )

    # 1. MODEL AND VALIDATION TESTS
    def test_create_pending_item(self):
        item = BandDashboardPendingItem.objects.create(
            band=self.band_a,
            show=self.show_a,
            description="Comprar cabos",
            created_by=self.produtor_a
        )
        self.assertEqual(item.band, self.band_a)
        self.assertEqual(item.show, self.show_a)
        self.assertEqual(item.description, "Comprar cabos")
        self.assertEqual(item.created_by, self.produtor_a)

    def test_ordering(self):
        item1 = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="1", created_by=self.produtor_a)
        item2 = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="2", created_by=self.produtor_a)
        items = list(BandDashboardPendingItem.objects.all())
        self.assertEqual(items[0], item2)
        self.assertEqual(items[1], item1)

    # 2. LISTING TESTS
    def test_dashboard_shows_only_band_items(self):
        BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)
        BandDashboardPendingItem.objects.create(band=self.band_b, show=self.show_b, description="Task B", created_by=self.produtor_b)

        self.client.login(username="prod_a", password="pwd")
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Task A")
        self.assertNotContains(response, "Task B")

    def test_integrante_sees_items_but_no_add_button(self):
        BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)

        self.client.login(username="int_a", password="pwd")
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Task A")
        self.assertNotContains(response, 'data-bs-target="#addPendingModal"')
        self.assertNotContains(response, 'Excluir')

    def test_produtor_sees_add_and_delete_buttons(self):
        BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)

        self.client.login(username="prod_a", password="pwd")
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Task A")
        self.assertContains(response, 'data-bs-target="#addPendingModal"')
        self.assertContains(response, 'Excluir')

    def test_empty_state_preservation(self):
        self.client.login(username="prod_a", password="pwd")
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertContains(response, "Nenhuma pendência no momento.")

    # 3. CREATION TESTS
    def test_produtor_can_create_pending_item(self):
        self.client.login(username="prod_a", password="pwd")
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        data = {
            'description': 'Test description',
            'show': self.show_a.id
        }
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(BandDashboardPendingItem.objects.count(), 1)
        item = BandDashboardPendingItem.objects.first()
        self.assertEqual(item.description, 'Test description')

    def test_description_trim(self):
        self.client.login(username="prod_a", password="pwd")
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        response = self.client.post(url, {'description': '   Spaces   ', 'show': self.show_a.id})
        item = BandDashboardPendingItem.objects.first()
        self.assertEqual(item.description, 'Spaces')

    def test_integrante_cannot_create_pending_item(self):
        self.client.login(username="int_a", password="pwd")
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        response = self.client.post(url, {'description': 'Test', 'show': self.show_a.id})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(BandDashboardPendingItem.objects.count(), 0)

    def test_produtor_cannot_create_with_other_band_show(self):
        self.client.login(username="prod_a", password="pwd")
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        response = self.client.post(url, {'description': 'Test', 'show': self.show_b.id})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(BandDashboardPendingItem.objects.count(), 0)

    def test_empty_description_rejected(self):
        self.client.login(username="prod_a", password="pwd")
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        response = self.client.post(url, {'description': '   ', 'show': self.show_a.id})
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(BandDashboardPendingItem.objects.count(), 0)

    def test_get_on_add_view_rejected(self):
        self.client.login(username="prod_a", password="pwd")
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405) # require_POST

    # 4. DELETION TESTS
    def test_produtor_can_delete_pending_item(self):
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)
        self.client.login(username="prod_a", password="pwd")
        url = reverse('delete_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        response = self.client.post(url)
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        self.assertEqual(BandDashboardPendingItem.objects.count(), 0)

    def test_integrante_cannot_delete_pending_item(self):
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)
        self.client.login(username="int_a", password="pwd")
        url = reverse('delete_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(BandDashboardPendingItem.objects.count(), 1)

    def test_produtor_cannot_delete_item_from_other_band(self):
        item = BandDashboardPendingItem.objects.create(band=self.band_b, show=self.show_b, description="Task B", created_by=self.produtor_b)
        self.client.login(username="prod_a", password="pwd")
        url = reverse('delete_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(BandDashboardPendingItem.objects.count(), 1)

    def test_get_on_delete_view_rejected(self):
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)
        self.client.login(username="prod_a", password="pwd")
        url = reverse('delete_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405) # require_POST
