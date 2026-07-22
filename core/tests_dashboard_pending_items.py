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

    # 6. MULTI-TENANT ISOLATION TESTS
    def test_produtor_band_a_cannot_add_pending_item_to_band_b(self):
        self.client.login(username="prod_a", password="pwd")
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_b.slug})
        data = {'description': 'Test', 'show': self.show_b.id}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 403)

    def test_produtor_band_a_cannot_edit_band_b_pending_item(self):
        item = BandDashboardPendingItem.objects.create(band=self.band_b, show=self.show_b, description="Task B", created_by=self.produtor_b)
        self.client.login(username="prod_a", password="pwd")
        url = reverse('edit_dashboard_pending_item', kwargs={'band_slug': self.band_b.slug, 'pending_id': item.id})
        data = {f'edit_{item.id}-description': 'Updated', f'edit_{item.id}-show': self.show_b.id}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 403)

    def test_superuser_without_band_role_cannot_add_pending_item(self):
        superuser = User.objects.create_superuser(username="su", email="su@test.com", password="pwd")
        self.client.login(username="su", password="pwd")
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        data = {'description': 'Test', 'show': self.show_a.id}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 403)

    def test_superuser_without_band_role_cannot_edit_pending_item(self):
        User.objects.create_superuser(username="su_edit", email="su2@test.com", password="pwd")
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task", created_by=self.produtor_a)
        self.client.login(username="su_edit", password="pwd")
        url = reverse('edit_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        data = {f'edit_{item.id}-description': 'Updated', f'edit_{item.id}-show': self.show_a.id}
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 403)

    def test_superuser_without_band_role_cannot_delete_pending_item(self):
        User.objects.create_superuser(username="su_del", email="su3@test.com", password="pwd")
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task", created_by=self.produtor_a)
        self.client.login(username="su_del", password="pwd")
        url = reverse('delete_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

    def test_pending_edit_preserves_band_created_by_created_at_and_updates_updated_at(self):
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)
        original_band = item.band
        original_created_by = item.created_by
        original_created_at = item.created_at
        original_updated_at = item.updated_at

        # Mock passage of time for DB update
        import time
        time.sleep(0.01)

        self.client.login(username="prod_a", password="pwd")
        url = reverse('edit_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        data = {f'edit_{item.id}-description': 'Updated Task A', f'edit_{item.id}-show': self.show_a.id}
        self.client.post(url, data)

        item.refresh_from_db()
        self.assertEqual(item.band, original_band)
        self.assertEqual(item.created_by, original_created_by)
        self.assertEqual(item.created_at, original_created_at)
        self.assertGreater(item.updated_at, original_updated_at)

    def test_pending_edit_rejects_other_band_show(self):
        item = BandDashboardPendingItem.objects.create(band=self.band_a, show=self.show_a, description="Task A", created_by=self.produtor_a)
        self.client.login(username="prod_a", password="pwd")
        url = reverse('edit_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        data = {f'edit_{item.id}-description': 'Updated Task A', f'edit_{item.id}-show': self.show_b.id}
        response = self.client.post(url, data)
        # Assuming the form rejects it and redirects back to dashboard with errors
        self.assertEqual(response.status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.show, self.show_a) # Not changed to show_b

    def test_pending_operations_do_not_create_side_effects(self):
        from .models import Notification, WebPushDelivery

        notif_before = Notification.objects.count()
        wp_before = WebPushDelivery.objects.count()

        # Create
        self.client.login(username="prod_a", password="pwd")
        url = reverse('add_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug})
        self.client.post(url, {'description': 'Test', 'show': self.show_a.id})

        self.assertEqual(Notification.objects.count(), notif_before)
        self.assertEqual(WebPushDelivery.objects.count(), wp_before)

        item = BandDashboardPendingItem.objects.first()

        # Edit
        url = reverse('edit_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        self.client.post(url, {f'edit_{item.id}-description': 'Updated', f'edit_{item.id}-show': self.show_a.id})

        self.assertEqual(Notification.objects.count(), notif_before)
        self.assertEqual(WebPushDelivery.objects.count(), wp_before)

        # Delete
        url = reverse('delete_dashboard_pending_item', kwargs={'band_slug': self.band_a.slug, 'pending_id': item.id})
        self.client.post(url)

        self.assertEqual(Notification.objects.count(), notif_before)
        self.assertEqual(WebPushDelivery.objects.count(), wp_before)

    def test_pending_feature_is_not_exposed_in_admin_panel(self):
        from django.contrib import admin
        self.assertFalse(admin.site.is_registered(BandDashboardPendingItem))
    def test_pending_items_are_ordered_by_show_date(self):
        from django.utils import timezone
        import datetime
        today = timezone.localdate()

        show1 = Show.objects.create(band=self.band_a, title='Show 1', date=today + datetime.timedelta(days=2))
        show2 = Show.objects.create(band=self.band_a, title='Show 2', date=today + datetime.timedelta(days=5))
        show3 = Show.objects.create(band=self.band_a, title='Show 3', date=today + datetime.timedelta(days=1))

        BandDashboardPendingItem.objects.create(band=self.band_a, show=show1, description='P1', created_by=self.produtor_a)
        BandDashboardPendingItem.objects.create(band=self.band_a, show=show2, description='P2', created_by=self.produtor_a)
        BandDashboardPendingItem.objects.create(band=self.band_a, show=show3, description='P3', created_by=self.produtor_a)

        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        items = list(response.context['dashboard_pending_items'])

        self.assertEqual(len(items), 3)
        self.assertEqual(items[0].show, show3) # +1 day
        self.assertEqual(items[1].show, show1) # +2 days
        self.assertEqual(items[2].show, show2) # +5 days

    def test_newer_pending_item_does_not_override_show_date_order(self):
        from django.utils import timezone
        import datetime
        today = timezone.localdate()

        show_distante = Show.objects.create(band=self.band_a, title='Distante', date=today + datetime.timedelta(days=10))
        show_proximo = Show.objects.create(band=self.band_a, title='Proximo', date=today + datetime.timedelta(days=2))

        # Cria a do show distante primeiro
        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_distante, description='D', created_by=self.produtor_a)
        # Cria a do show prximo depois
        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_proximo, description='P', created_by=self.produtor_a)

        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        items = list(response.context['dashboard_pending_items'])

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].show, show_proximo)
        self.assertEqual(items[1].show, show_distante)

    def test_pending_items_same_date_are_ordered_by_show_time(self):
        from django.utils import timezone
        import datetime
        today = timezone.localdate()

        show_tarde = Show.objects.create(band=self.band_a, title='Tarde', date=today + datetime.timedelta(days=3), show_time=datetime.time(15, 0))
        show_cedo = Show.objects.create(band=self.band_a, title='Cedo', date=today + datetime.timedelta(days=3), show_time=datetime.time(10, 0))

        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_tarde, description='T', created_by=self.produtor_a)
        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_cedo, description='C', created_by=self.produtor_a)

        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        items = list(response.context['dashboard_pending_items'])

        self.assertEqual(items[0].show, show_cedo)
        self.assertEqual(items[1].show, show_tarde)

    def test_pending_items_without_show_date_are_last(self):
        from django.utils import timezone
        import datetime
        today = timezone.localdate()

        show_sem_data = Show.objects.create(band=self.band_a, title='Sem Data', date=None)
        show_futuro = Show.objects.create(band=self.band_a, title='Futuro', date=today + datetime.timedelta(days=5))

        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_sem_data, description='S', created_by=self.produtor_a)
        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_futuro, description='F', created_by=self.produtor_a)

        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        items = list(response.context['dashboard_pending_items'])

        self.assertEqual(items[0].show, show_futuro)
        self.assertEqual(items[1].show, show_sem_data)

    def test_past_show_pending_items_come_after_future_items(self):
        from django.utils import timezone
        import datetime
        today = timezone.localdate()

        show_passado = Show.objects.create(band=self.band_a, title='Passado', date=today - datetime.timedelta(days=2))
        show_futuro = Show.objects.create(band=self.band_a, title='Futuro', date=today + datetime.timedelta(days=2))

        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_passado, description='P', created_by=self.produtor_a)
        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_futuro, description='F', created_by=self.produtor_a)

        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        items = list(response.context['dashboard_pending_items'])

        self.assertEqual(items[0].show, show_futuro)
        self.assertEqual(items[1].show, show_passado)

    def test_past_show_pending_items_are_ordered_newest_first(self):
        from django.utils import timezone
        import datetime
        today = timezone.localdate()

        # mais antigo
        show_antigo = Show.objects.create(band=self.band_a, title='Antigo', date=today - datetime.timedelta(days=10))
        # mais recente (passado prximo)
        show_recente = Show.objects.create(band=self.band_a, title='Recente', date=today - datetime.timedelta(days=2))

        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_antigo, description='A', created_by=self.produtor_a)
        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_recente, description='R', created_by=self.produtor_a)

        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        items = list(response.context['dashboard_pending_items'])

        self.assertEqual(items[0].show, show_recente)
        self.assertEqual(items[1].show, show_antigo)

    def test_pending_order_is_isolated_by_band(self):
        from django.utils import timezone
        import datetime
        today = timezone.localdate()

        show_a = Show.objects.create(band=self.band_a, title='Show A', date=today + datetime.timedelta(days=5))
        show_b = Show.objects.create(band=self.band_b, title='Show B', date=today + datetime.timedelta(days=1))

        BandDashboardPendingItem.objects.create(band=self.band_a, show=show_a, description='A', created_by=self.produtor_a)
        BandDashboardPendingItem.objects.create(band=self.band_b, show=show_b, description='B', created_by=self.produtor_b)

        self.client.force_login(self.produtor_a)
        response = self.client.get(reverse('dashboard', kwargs={'band_slug': self.band_a.slug}))
        items = list(response.context['dashboard_pending_items'])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].show, show_a)
