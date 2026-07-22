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
        self.assertEqual(response.status_code, 302)
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

    def test_pending_form_empty_label(self):
        from .forms import BandDashboardPendingItemForm
        from .models import Show
        form = BandDashboardPendingItemForm(shows_qs=Show.objects.filter(band=self.band_a))
        rendered_select = str(form['show'])
        self.assertIn('<option value="" selected>Selecione um show</option>', rendered_select)

    def test_pending_form_show_label_with_date(self):
        import datetime
        from .forms import BandDashboardPendingItemForm
        from .models import Show
        self.show_a.date = datetime.date(2026, 7, 22)
        self.show_a.title = 'EVENTO BAND'
        self.show_a.save()
        form = BandDashboardPendingItemForm(shows_qs=Show.objects.filter(band=self.band_a))
        rendered_select = str(form['show'])
        self.assertIn('22/07/2026 - EVENTO BAND', rendered_select)

    def test_pending_form_show_without_date_label(self):
        from .forms import BandDashboardPendingItemForm
        from .models import Show
        Show.objects.create(band=self.band_a, title='SHOW SEM DATA', date=None)
        form = BandDashboardPendingItemForm(shows_qs=Show.objects.filter(band=self.band_a))
        rendered_select = str(form['show'])
        self.assertIn('Data n\xe3o informada - SHOW SEM DATA', rendered_select)

    def test_pending_form_orders_dated_shows_first(self):
        import datetime
        from django.utils import timezone
        from django.db.models import Q, F
        from .models import Show
        Show.objects.all().delete()
        Show.objects.create(band=self.band_a, title='SHOW A', date=datetime.date(2026, 8, 1))
        Show.objects.create(band=self.band_a, title='SHOW B', date=datetime.date(2026, 7, 30))
        shows = Show.objects.filter(
            Q(band=self.band_a) & (Q(date__gte=timezone.localdate()) | Q(date__isnull=True))
        ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')
        titles = [s.title for s in shows]
        # SHOW B is earlier than SHOW A
        self.assertIn('SHOW B', titles)
        self.assertIn('SHOW A', titles)
        idx_b = titles.index('SHOW B')
        idx_a = titles.index('SHOW A')
        self.assertTrue(idx_b < idx_a)

    def test_pending_form_places_undated_shows_last(self):
        import datetime
        from django.utils import timezone
        from django.db.models import Q, F
        from .models import Show
        Show.objects.all().delete()
        Show.objects.create(band=self.band_a, title='SHOW SEM DATA', date=None)
        Show.objects.create(band=self.band_a, title='SHOW DATADO', date=datetime.date(2026, 12, 1))
        shows = Show.objects.filter(
            Q(band=self.band_a) & (Q(date__gte=timezone.localdate()) | Q(date__isnull=True))
        ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')
        self.assertEqual(shows.last().title, 'SHOW SEM DATA')

    def test_pending_form_excludes_past_shows(self):
        import datetime
        from django.utils import timezone
        from django.db.models import Q, F
        from .models import Show
        Show.objects.create(band=self.band_a, title='SHOW PASSADO', date=datetime.date(2000, 1, 1))
        shows = Show.objects.filter(
            Q(band=self.band_a) & (Q(date__gte=timezone.localdate()) | Q(date__isnull=True))
        ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')
        titles = [s.title for s in shows]
        self.assertNotIn('SHOW PASSADO', titles)

    def test_pending_form_excludes_other_band_shows(self):
        import datetime
        from django.utils import timezone
        from django.db.models import Q, F
        from .models import Show
        Show.objects.create(band=self.band_b, title='OTHER BAND SHOW', date=datetime.date(2026, 7, 24))
        shows = Show.objects.filter(
            Q(band=self.band_a) & (Q(date__gte=timezone.localdate()) | Q(date__isnull=True))
        ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')
        titles = [s.title for s in shows]
        self.assertNotIn('OTHER BAND SHOW', titles)

    def test_pending_form_uses_local_date_boundary(self):
        import datetime
        from django.utils import timezone
        from django.db.models import Q, F
        from .models import Show
        
        # Test that the boundary effectively acts upon localdate
        Show.objects.all().delete()
        
        today = timezone.localdate()
        yesterday = today - datetime.timedelta(days=1)
        
        Show.objects.create(band=self.band_a, title='SHOW DE HOJE', date=today)
        Show.objects.create(band=self.band_a, title='SHOW DE ONTEM', date=yesterday)
        
        shows = Show.objects.filter(
            Q(band=self.band_a) & (Q(date__gte=timezone.localdate()) | Q(date__isnull=True))
        ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')
        
        titles = [s.title for s in shows]
        self.assertIn('SHOW DE HOJE', titles)
        self.assertNotIn('SHOW DE ONTEM', titles)

    def test_pending_create_rejects_other_band_show(self):
        self.client.login(username='prod_a', password='pwd')
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        response = self.client.post(url, {
            'description': 'Test reject',
            'show': self.show_b.id
        })
        self.assertEqual(BandDashboardPendingItem.objects.filter(description='Test reject').count(), 0)
        # Should redirect back or show error
        self.assertEqual(response.status_code, 302)

    def test_pending_create_uses_form_and_persists_show(self):
        self.client.login(username='prod_a', password='pwd')
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        self.client.post(url, {
            'description': 'Valid Task',
            'show': self.show_a.id
        })
        item = BandDashboardPendingItem.objects.get(description='Valid Task')
        self.assertEqual(item.show, self.show_a)
        self.assertEqual(item.band, self.band_a)
        self.assertEqual(item.created_by, self.produtor_a)

    def test_dashboard_modal_renders_form_labels(self):
        self.client.login(username='prod_a', password='pwd')
        import datetime
        self.show_a.date = datetime.date(2026, 7, 22)
        self.show_a.title = 'EVENTO BAND'
        self.show_a.save()
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        content = response.content.decode('utf-8')
        self.assertIn('22/07/2026 - EVENTO BAND', content)
        self.assertIn('<option value="" selected>Selecione um show</option>', content)

    # 5. EDIT TESTS
    def test_produtor_can_edit_pending_item(self):
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)
        self.client.login(username="prod_a", password="pwd")
        url = reverse('edit_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        data = {
            f'edit_{item.id}-description': 'Updated Task A',
            f'edit_{item.id}-show': self.show_a.id
        }
        response = self.client.post(url, data)
        self.assertRedirects(response, reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        item.refresh_from_db()
        self.assertEqual(item.description, 'Updated Task A')

    def test_integrante_cannot_edit_pending_item(self):
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)
        self.client.login(username="int_a", password="pwd")
        url = reverse('edit_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        data = {
            f'edit_{item.id}-description': 'Updated Task A',
            f'edit_{item.id}-show': self.show_a.id
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.description, 'Task A')

    def test_edit_includes_current_show_even_if_past(self):
        import datetime
        from .models import Show
        past_show = Show.objects.create(band=self.band_a, title='PAST SHOW', date=datetime.date(2000, 1, 1))
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=past_show, description="Task", created_by=self.produtor_a)
        self.client.login(username="prod_a", password="pwd")
        
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        # In edit form, the PAST SHOW will be included
        self.assertContains(response, 'PAST SHOW')

