import os
import django
from django.test import TestCase, RequestFactory, Client
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.http import HttpResponse

from core.models import Band, Show
from core.decorators import advanced_plan_required
from core.admin_forms import AdminBandForm

User = get_user_model()

class PlanSystemTests(TestCase):
    def setUp(self):
        self.band_avancado = Band.objects.create(
            name="Banda 1", slug="banda-1",
            subscription_plan='MENSAL', is_active=True
        )
        self.band_basico = Band.objects.create(
            name="Banda 2", slug="banda-2", plan_type=Band.PlanType.BASICO,
            subscription_plan='ANUAL', is_active=False
        )
        self.factory = RequestFactory()

        Show.objects.create(band=self.band_avancado, title="Show Test", date="2026-10-10")

    def test_default_plan_is_advanced_and_properties(self):
        self.assertEqual(self.band_avancado.plan_type, Band.PlanType.AVANCADO)
        self.assertTrue(self.band_avancado.is_advanced)
        self.assertFalse(self.band_avancado.is_basic)

        self.assertEqual(self.band_basico.plan_type, Band.PlanType.BASICO)
        self.assertFalse(self.band_basico.is_advanced)
        self.assertTrue(self.band_basico.is_basic)

    def test_admin_form_validation(self):
        form_empty = AdminBandForm(data={})
        self.assertFalse(form_empty.is_valid())
        self.assertIn('name', form_empty.errors)
        self.assertIn('slug', form_empty.errors)
        self.assertIn('plan_type', form_empty.errors)

        form_valid = AdminBandForm(data={
            'name': 'Nova',
            'slug': 'nova',
            'plan_type': 'BASICO'
        })
        self.assertTrue(form_valid.is_valid())

        form_edit = AdminBandForm(instance=self.band_avancado)
        self.assertEqual(form_edit.initial['plan_type'], Band.PlanType.AVANCADO)

    def test_band_plan_change_isolation(self):
        original_shows_count = Show.objects.filter(band=self.band_avancado).count()

        self.band_avancado.plan_type = Band.PlanType.BASICO
        self.band_avancado.save()

        self.band_avancado.refresh_from_db()
        self.assertEqual(self.band_avancado.plan_type, 'BASICO')
        self.assertTrue(self.band_avancado.is_active)
        self.assertEqual(self.band_avancado.subscription_plan, 'MENSAL')
        self.assertEqual(Show.objects.filter(band=self.band_avancado).count(), original_shows_count)

    def test_central_barrier_decorator(self):
        @advanced_plan_required
        def dummy_view(request):
            return HttpResponse("OK")

        req1 = self.factory.get('/fake/')
        req1.band = self.band_avancado
        resp1 = dummy_view(req1)
        self.assertEqual(resp1.status_code, 200)

        req2 = self.factory.get('/fake/')
        req2.band = self.band_basico
        with self.assertRaises(PermissionDenied):
            dummy_view(req2)

        req3 = self.factory.get('/fake/')
        with self.assertRaises(PermissionDenied):
            dummy_view(req3)

class PlanTemplateTests(TestCase):
    def setUp(self):
        self.band_basico = Band.objects.create(name="Banda Basico", slug="banda-basico", plan_type=Band.PlanType.BASICO)
        self.band_avancado = Band.objects.create(name="Banda Avancado", slug="banda-avancado")
        self.admin_user = User.objects.create_superuser(username='admin', password='123', email='admin@test.com')
        self.client = Client()
        self.client.login(username='admin', password='123')

    def test_bandas_list_template(self):
        response = self.client.get('/painel/bandas/')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        self.assertIn('<th class="border-0">Plano</th>', content)
        self.assertIn('Básico', content)
        self.assertIn('Avançado', content)
        self.assertIn('bg-primary', content)
        self.assertIn('bg-success', content)

        self.assertIn('Painel</a>', content)
        self.assertIn('Editar</button>', content)
        self.assertIn('Excluir', content)
        self.assertIn('calendario', content)
        self.assertIn('modalToggleBand', content)

class MigrationTest(TestCase):
    def test_migration_assigns_avancado(self):
        from django.db.migrations.loader import MigrationLoader
        from django.db import connection
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        migration = loader.get_migration('core', '0084_band_plan_type')

        self.assertEqual(len(migration.operations), 1)
        op = migration.operations[0]
        self.assertEqual(op.name, 'plan_type')
        self.assertEqual(op.field.default, 'AVANCADO')
        self.assertFalse(op.field.null)
