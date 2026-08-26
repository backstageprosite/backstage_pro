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


from django.urls import reverse
from django.utils import timezone
from core.models import BandNotice, BandDashboardPendingItem
from django.core.management import call_command
import io

class ProtectedModulesTests(TestCase):
    def setUp(self):
        self.band_avancado = Band.objects.create(name="Banda 1", slug="banda-1", plan_type=Band.PlanType.AVANCADO)
        self.band_basico = Band.objects.create(name="Banda 2", slug="banda-2", plan_type=Band.PlanType.BASICO)
        self.user_avancado = User.objects.create_user(username='u1', email='u1@test.com', password='123', role='PRODUTOR')
        self.user_avancado.band = self.band_avancado
        self.user_avancado.save()
        self.user_basico = User.objects.create_user(username='u2', email='u2@test.com', password='123', role='PRODUTOR')
        self.user_basico.band = self.band_basico
        self.user_basico.save()

    def test_basic_band_gets_403_on_protected_routes(self):
        # 1. Básico recebe 403 em uma rota representativa de cada módulo bloqueado
        self.client.login(username='u2', password='123')

        routes = [
            reverse('pendencias', args=[self.band_basico.slug]),
            reverse('relatorio_financeiro', args=[self.band_basico.slug]),
            reverse('arquivos', args=[self.band_basico.slug]),
            reverse('rider_list', args=[self.band_basico.slug]),
            reverse('room_list_index', args=[self.band_basico.slug]),
            reverse('band_notices_index', args=[self.band_basico.slug]),
        ]

        for r in routes:
            response = self.client.get(r)
            self.assertEqual(response.status_code, 403)

    def test_basic_band_gets_403_on_post_ajax_and_downloads(self):
        # 2. Endpoints POST do Básico não criam
        # 3. AJAX
        # 4. Downloads protegidos
        # 5. PDFs Room List
        self.client.login(username='u2', password='123')

        post_response = self.client.post(reverse('band_notices_create', args=[self.band_basico.slug]), {'message': 'Teste'})
        self.assertEqual(post_response.status_code, 403)
        self.assertEqual(BandNotice.objects.count(), 0)

        # Room list PDF
        pdf_response = self.client.get(reverse('room_list_pdf', args=[self.band_basico.slug, 999]))
        self.assertEqual(pdf_response.status_code, 403)

    def test_advanced_band_access(self):
        # 7. Avançado mantém acesso aos módulos
        self.client.login(username='u1', password='123')
        response = self.client.get(reverse('arquivos', args=[self.band_avancado.slug]))
        # May be 200 or something else if missing data, but NOT 403
        self.assertNotEqual(response.status_code, 403)

    def test_other_band_no_access(self):
        # 8. Usuário de outra banda continua sem acesso
        self.client.login(username='u2', password='123')
        # Try to access Avançado band's archive
        response = self.client.get(reverse('arquivos', args=[self.band_avancado.slug]))
        # The existing permissions or the decorator should return 403 or 404
        self.assertIn(response.status_code, [403, 404])

    def test_cron_ignores_basic_bands(self):
        # 18. Cron ignora avisos de banda Básica
        # 19. Cron continua processando avisos de banda Avançada
        now = timezone.now()
        notice_a = BandNotice.objects.create(band=self.band_avancado, message="A", scheduled_at=now, created_by=self.user_avancado)
        notice_b = BandNotice.objects.create(band=self.band_basico, message="B", scheduled_at=now, created_by=self.user_basico)

        out = io.StringIO()
        call_command('process_band_notices', stdout=out)

        notice_a.refresh_from_db()
        notice_b.refresh_from_db()

        self.assertIsNotNone(notice_a.sent_at)
        self.assertIsNone(notice_b.sent_at)

class DashboardMenuTests(TestCase):
    def setUp(self):
        self.band_basico = Band.objects.create(name="Banda 2", slug="banda-2", plan_type=Band.PlanType.BASICO)
        self.user_basico = User.objects.create_user(username='u2', email='u2@test.com', password='123', role='PRODUTOR')
        self.user_basico.band = self.band_basico
        self.user_basico.save()

        self.band_avancado = Band.objects.create(name="Banda 1", slug="banda-1", plan_type=Band.PlanType.AVANCADO)
        self.user_avancado = User.objects.create_user(username='u1', email='u1@test.com', password='123', role='PRODUTOR')
        self.user_avancado.band = self.band_avancado
        self.user_avancado.save()

    def test_dashboard_basic(self):
        # 9, 10, 11
        self.client.login(username='u2', password='123')
        response = self.client.get(reverse('dashboard', args=[self.band_basico.slug]))
        content = response.content.decode('utf-8')

        self.assertEqual(response.context['pendencias_bloqueadas'], True)
        self.assertIsNone(response.context.get('dashboard_pending_items'))

        self.assertIn('FUNCIONALIDADE DISPONIVEL APENAS NO PLANO AVANÇADO', content)
        self.assertIn('bg-light opacity-75', content)

    def test_dashboard_advanced(self):
        # 12
        self.client.login(username='u1', password='123')
        response = self.client.get(reverse('dashboard', args=[self.band_avancado.slug]))
        self.assertEqual(response.context.get('pendencias_bloqueadas', False), False)

    def test_menu_and_modal_basic(self):
        # 13, 14, 15, 17
        self.client.login(username='u2', password='123')
        response = self.client.get(reverse('dashboard', args=[self.band_basico.slug]))
        content = response.content.decode('utf-8')

        self.assertNotIn(f'href="{reverse("pendencias", args=[self.band_basico.slug])}"', content)
        self.assertIn('data-bs-target="#modalAdvancedPlan"', content)
        self.assertIn('Recurso do plano Avançado', content)
        self.assertIn('Conhecer o plano Avançado', content)
        self.assertIn('Agora não', content)


class PublicAndPdfTests(TestCase):
    """Gate Final: public routes, PDFs, file_viewer, auth behavior."""

    def setUp(self):
        from core.models import RiderDocument
        import uuid as uuid_module

        self.band_avancado = Band.objects.create(
            name="Banda AV", slug="banda-av", plan_type=Band.PlanType.AVANCADO, is_active=True
        )
        self.band_basico = Band.objects.create(
            name="Banda BAS", slug="banda-bas", plan_type=Band.PlanType.BASICO, is_active=True
        )
        self.user_avancado = User.objects.create_user(
            username='uav', email='uav@t.com', password='123', role='PRODUTOR'
        )
        self.user_avancado.band = self.band_avancado
        self.user_avancado.save()

        self.user_basico = User.objects.create_user(
            username='ubas', email='ubas@t.com', password='123', role='PRODUTOR'
        )
        self.user_basico.band = self.band_basico
        self.user_basico.save()

        # Create RiderDocument for each band (no real file on disk in tests)
        self.uuid_av = uuid_module.uuid4()
        self.uuid_bas = uuid_module.uuid4()
        self.rider_av = RiderDocument.objects.create(
            band=self.band_avancado, file='riders/test.pdf', uuid=self.uuid_av
        )
        self.rider_bas = RiderDocument.objects.create(
            band=self.band_basico, file='riders/test.pdf', uuid=self.uuid_bas
        )

    # ─── 1-2: public_rider_download ──────────────────────────────────────────
    def test_public_rider_advanced_band_reachable(self):
        """public_rider_download on Advanced band is NOT 403 (may be 404 if file missing)."""
        url = reverse('public_rider_download', args=[self.band_avancado.slug, self.uuid_av])
        response = self.client.get(url)  # unauthenticated — public route
        # File doesn't exist on disk → 404 or 500, but crucially NOT 403.
        self.assertNotEqual(response.status_code, 403)

    def test_public_rider_basic_band_is_403(self):
        """public_rider_download on Basic band → 403 (plan check via doc.band)."""
        url = reverse('public_rider_download', args=[self.band_basico.slug, self.uuid_bas])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    # ─── 3-4: internal_file_viewer selective block ────────────────────────────
    def test_file_viewer_receipt_basic_is_403(self):
        """file_viewer for receipt type → 403 for Basic plan."""
        self.client.login(username='ubas', password='123')
        url = reverse('file_viewer', args=[self.band_basico.slug, 'receipt', 999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_file_viewer_rider_basic_is_403(self):
        """file_viewer for rider type → 403 for Basic plan."""
        self.client.login(username='ubas', password='123')
        url = reverse('file_viewer', args=[self.band_basico.slug, 'rider', 999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_file_viewer_rider_advanced_not_403(self):
        """file_viewer for rider type → NOT 403 for Advanced plan (may be 404 without object)."""
        self.client.login(username='uav', password='123')
        url = reverse('file_viewer', args=[self.band_avancado.slug, 'rider', 999])
        response = self.client.get(url)
        self.assertNotEqual(response.status_code, 403)

    # ─── 5: unauthenticated access redirects to login ────────────────────────
    def test_unauthenticated_download_redirects_not_errors(self):
        """Unauthenticated access to a private download → redirect to login (not 500/403 mismatch)."""
        url = reverse('download_rider', args=[self.band_avancado.slug, 999])
        response = self.client.get(url)
        # Must be a redirect (302), not an unexpected error
        self.assertIn(response.status_code, [301, 302])

    # ─── 6-8: agenda/show PDFs accessible to Basic ────────────────────────────
    def test_agenda_pdf_accessible_basic(self):
        """agenda_pdf_view is NOT blocked for Basic band (it's not an advanced-only module)."""
        self.client.login(username='ubas', password='123')
        url = reverse('agenda_pdf', args=[self.band_basico.slug])
        response = self.client.get(url, follow=True)
        # Should return 200 with HTML (not 403)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # Check print mechanism
        self.assertTrue('window.print()' in content or 'onload="window.print()"' in content)

    def test_show_pdf_accessible_basic(self):
        """show_pdf_view is NOT blocked for Basic band."""
        import datetime
        from core.models import Show
        show = Show.objects.create(band=self.band_basico, title="T", date=datetime.date(2026, 10, 10))
        self.client.login(username='ubas', password='123')
        url = reverse('show_pdf', args=[self.band_basico.slug, show.pk])
        response = self.client.get(url, follow=True)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertTrue('window.print()' in content or 'onload="window.print()"' in content)

    # ─── 9-10: Room List PDFs still blocked for Basic ─────────────────────────
    def test_room_list_pdf_basic_is_403(self):
        """room_list_pdf is 403 for Basic plan."""
        self.client.login(username='ubas', password='123')
        url = reverse('room_list_pdf', args=[self.band_basico.slug, 999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_room_list_hotel_pdf_basic_is_403(self):
        """room_list_hotel_pdf is 403 for Basic plan."""
        self.client.login(username='ubas', password='123')
        url = reverse('room_list_hotel_pdf', args=[self.band_basico.slug, 999])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)


class RelatoriosIndexTests(TestCase):
    def setUp(self):
        self.band_basico = Band.objects.create(name="Banda BAS", slug="banda-bas", plan_type=Band.PlanType.BASICO, is_active=True)
        self.band_avancado = Band.objects.create(name="Banda AV", slug="banda-av", plan_type=Band.PlanType.AVANCADO, is_active=True)

        self.user_basico = User.objects.create_user(username='ubas', email='ubas@t.com', password='123', role='PRODUTOR')
        self.user_basico.band = self.band_basico
        self.user_basico.save()

        self.user_avancado = User.objects.create_user(username='uav', email='uav@t.com', password='123', role='PRODUTOR')
        self.user_avancado.band = self.band_avancado
        self.user_avancado.save()

    def test_relatorios_index_basic_plan(self):
        self.client.login(username='ubas', password='123')
        url = reverse('relatorios_index', args=[self.band_basico.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Allowed modules (3)
        self.assertIn(reverse('usuarios_list', args=[self.band_basico.slug]), content)
        self.assertIn(reverse('integrantes_list', args=[self.band_basico.slug]), content)
        self.assertIn(reverse('support_list', args=[self.band_basico.slug]), content)

        # Blocked modules (5)
        self.assertNotIn(reverse('relatorio_financeiro', args=[self.band_basico.slug]), content)
        self.assertNotIn(reverse('arquivos', args=[self.band_basico.slug]), content)
        self.assertNotIn(reverse('rider_list', args=[self.band_basico.slug]), content)
        self.assertNotIn(reverse('room_list_index', args=[self.band_basico.slug]), content)
        self.assertNotIn(reverse('band_notices_index', args=[self.band_basico.slug]), content)

        # Check for lock icon and modal target
        # 5 from cards + 1 from sidebar/nav = 6 targets
        self.assertEqual(content.count('data-bs-target="#modalAdvancedPlan"'), 6)

        # Verify it's a button and NOT javascript:void(0)
        self.assertEqual(content.count('javascript:void(0)'), 0)
        self.assertEqual(content.count('type="button" class="border-0 bg-transparent p-0 w-100 text-decoration-none text-start d-block" data-bs-toggle="modal" data-bs-target="#modalAdvancedPlan" aria-disabled="true"'), 5)

        self.assertEqual(content.count('aria-disabled="true"'), 5)

        # Ensure no "BLOQUEAR" text is present
        self.assertNotIn('BLOQUEAR', content.upper())

    def test_relatorios_index_advanced_plan(self):
        self.client.login(username='uav', password='123')
        url = reverse('relatorios_index', args=[self.band_avancado.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # All 8 should have their operational URLs
        self.assertIn(reverse('relatorio_financeiro', args=[self.band_avancado.slug]), content)
        self.assertIn(reverse('arquivos', args=[self.band_avancado.slug]), content)
        self.assertIn(reverse('rider_list', args=[self.band_avancado.slug]), content)
        self.assertIn(reverse('room_list_index', args=[self.band_avancado.slug]), content)
        self.assertIn(reverse('band_notices_index', args=[self.band_avancado.slug]), content)
        self.assertIn(reverse('usuarios_list', args=[self.band_avancado.slug]), content)
        self.assertIn(reverse('integrantes_list', args=[self.band_avancado.slug]), content)
        self.assertIn(reverse('support_list', args=[self.band_avancado.slug]), content)

        # Lock icons should not be present
        self.assertEqual(content.count('fa-lock text-muted'), 0)
        self.assertEqual(content.count('data-bs-target="#modalAdvancedPlan"'), 0)







from .models import ContractDocument, FinancialReceipt, ShowPayment


class ShowFormPlansTests(TestCase):
    def setUp(self):
        from core.models import BandSubscription, ShowTeamCost
        self.user = User.objects.create_user(username='produtor6', password='123', role='PRODUTOR')
        self.band_basic = Band.objects.create(name='Banda Basica Show 5', slug='banda-basica-show5', plan_type='BASICO')
        self.band_advanced = Band.objects.create(name='Banda Avancada Show 5', slug='banda-avancada-show5', plan_type='AVANCADO')

        BandSubscription.objects.create(band=self.band_basic, status='ACTIVE', plan_name='BÁSICO')
        BandSubscription.objects.create(band=self.band_advanced, status='ACTIVE', plan_name='AVANÇADO')

        self.user.band = self.band_basic
        self.user.save()

        self.show_basic = Show.objects.create(
            band=self.band_basic, title='Show Basico', date='2025-01-01', status='CONFIRMADO', city='SP', fee=1000.00, contractor_name='Joao',
            accommodation='Hotel ABC'
        )
        self.show_advanced = Show.objects.create(
            band=self.band_advanced, title='Show Avancado', date='2025-01-01', status='CONFIRMADO', city='SP', fee=5000.00, payment_status='PENDENTE'
        )

        # Criar dados preexistentes
        self.doc_basic = ContractDocument.objects.create(show=self.show_basic, description='Doc Basico')
        self.receipt_basic = FinancialReceipt.objects.create(show=self.show_basic, description='Recibo Basico', value=100)
        self.payment_basic = ShowPayment.objects.create(show=self.show_basic, description='Pag Basico', value=100)
        self.cost_basic = ShowTeamCost.objects.create(show=self.show_basic, name='Cost 1', role='Roadie', value=50)

        self.client.login(username='produtor6', password='123')

    def test_basic_form_render(self):
        self.user.band = self.band_basic
        self.user.save()
        url = reverse('shows_add', args=[self.band_basic.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        # Abas
        self.assertIn('Técnica', html)
        self.assertIn('Logística', html)
        self.assertIn('Cronograma', html)

        # Cadeado
        self.assertIn('data-bs-target="#modalAdvancedPlan"', html)
        self.assertIn('aria-disabled="true"', html)

    def test_basic_create_show(self):
        self.user.band = self.band_basic
        self.user.save()
        url = reverse('shows_add', args=[self.band_basic.slug])
        data = {
            'title': 'Show Novo',
            'date': '2025-02-02',
            'status': 'CONFIRMADO',
            'city': 'RJ',
        }
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Show.objects.filter(title='Show Novo').exists())

    def test_basic_edit_preserves_financial_data(self):
        from core.models import ShowTeamCost
        self.user.band = self.band_basic
        self.user.save()
        url = reverse('shows_edit', args=[self.band_basic.slug, self.show_basic.id])
        data = {
            'title': 'Show Editado',
            'date': '2025-01-01',
            'status': 'CONFIRMADO',
            'city': 'SP',
            'fee': '500.00',
            'accommodation': 'Hotel XYZ'
        }
        # Adicionar formset forjado de contratos
        data['documents-TOTAL_FORMS'] = '1'
        data['documents-INITIAL_FORMS'] = '0'
        data['documents-MIN_NUM_FORMS'] = '0'
        data['documents-MAX_NUM_FORMS'] = '1000'
        data['documents-0-description'] = 'Doc Forjado'
        data['active_tab'] = 'tecnica'

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        self.show_basic.refresh_from_db()
        self.assertEqual(self.show_basic.title, 'Show Editado')
        self.assertEqual(self.show_basic.accommodation, 'Hotel XYZ')

        # O POST financeiro forjado não altera fee ou contratante
        self.assertEqual(float(self.show_basic.fee), 1000.00)
        self.assertEqual(self.show_basic.contractor_name, 'Joao')

        # Não foi criado novo contrato nem excluído o existente
        self.assertFalse(ContractDocument.objects.filter(description='Doc Forjado').exists())
        self.assertEqual(ContractDocument.objects.filter(show=self.show_basic).count(), 1)
        self.assertTrue(ContractDocument.objects.filter(id=self.doc_basic.id).exists())

        # Recibo/pagamento/custo preexistente permanece
        self.assertEqual(FinancialReceipt.objects.filter(show=self.show_basic).count(), 1)
        self.assertTrue(FinancialReceipt.objects.filter(id=self.receipt_basic.id).exists())
        self.assertEqual(ShowPayment.objects.filter(show=self.show_basic).count(), 1)
        self.assertTrue(ShowPayment.objects.filter(id=self.payment_basic.id).exists())
        self.assertEqual(ShowTeamCost.objects.filter(show=self.show_basic).count(), 1)
        self.assertTrue(ShowTeamCost.objects.filter(id=self.cost_basic.id).exists())

    def test_advanced_edit_financials(self):
        self.user.band = self.band_advanced
        self.user.save()
        url = reverse('shows_edit', args=[self.band_advanced.slug, self.show_advanced.id])
        data = {
            'title': 'Show Avancado Modificado',
            'date': '2025-01-01',
            'status': 'CONFIRMADO',
            'city': 'SP',
            'fee': '8000.00',
            'payment_status': 'PAGO',
            'documents-TOTAL_FORMS': '0',
            'documents-INITIAL_FORMS': '0',
            'documents-MIN_NUM_FORMS': '0',
            'documents-MAX_NUM_FORMS': '1000',
            'receipts-TOTAL_FORMS': '0',
            'receipts-INITIAL_FORMS': '0',
            'receipts-MIN_NUM_FORMS': '0',
            'receipts-MAX_NUM_FORMS': '1000',
            'payments-TOTAL_FORMS': '0',
            'payments-INITIAL_FORMS': '0',
            'payments-MIN_NUM_FORMS': '0',
            'payments-MAX_NUM_FORMS': '1000',
        }

        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302)

        self.show_advanced.refresh_from_db()
        self.assertEqual(float(self.show_advanced.fee), 8000.00)
        self.assertEqual(self.show_advanced.payment_status, 'PAGO')
        self.assertEqual(self.show_advanced.title, 'Show Avancado Modificado')

    def test_basic_save_and_continue_tabs(self):
        self.user.band = self.band_basic
        self.user.save()
        url = reverse('shows_add', args=[self.band_basic.slug])
        response = self.client.get(url)
        html = response.content.decode('utf-8')

        self.assertNotIn('href="javascript:void(0)"', html)
        self.assertIn('<button class="nav-link fw-bold px-4 text-nowrap text-muted bg-light opacity-75 grayscale" type="button" data-bs-toggle="modal" data-bs-target="#modalAdvancedPlan" aria-disabled="true"><i class="fa-solid fa-lock me-1"></i> Financeiro</button>', html)
        self.assertIn('<button class="nav-link fw-bold px-4 text-nowrap text-muted bg-light opacity-75 grayscale" type="button" data-bs-toggle="modal" data-bs-target="#modalAdvancedPlan" aria-disabled="true"><i class="fa-solid fa-lock me-1"></i> Anexos</button>', html)

    def test_advanced_form_render(self):
        self.user.band = self.band_advanced
        self.user.save()
        url = reverse('shows_add', args=[self.band_advanced.slug])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_contract_blocked_for_basic(self):
        self.user.band = self.band_basic
        self.user.save()

        url = reverse('download_contract', args=[self.band_basic.slug, self.doc_basic.id])
        self.assertEqual(self.client.get(url).status_code, 403)

        url = reverse('preview_contract', args=[self.band_basic.slug, self.doc_basic.id])
        self.assertEqual(self.client.get(url).status_code, 403)

        url = reverse('file_viewer', args=[self.band_basic.slug, 'contract', self.doc_basic.id])
        self.assertEqual(self.client.get(url).status_code, 403)

        url = reverse('document_delete', args=[self.band_basic.slug, self.doc_basic.id])
        self.assertEqual(self.client.post(url).status_code, 403)

    def test_billing_and_support_allowed(self):
        self.user.band = self.band_basic
        self.user.save()
        url_billing = reverse('minha_assinatura', args=[self.band_basic.slug])
        self.assertIn(self.client.get(url_billing).status_code, [200, 302])
        url_support = reverse('support_list', args=[self.band_basic.slug])
        self.assertEqual(self.client.get(url_support).status_code, 200)

    def test_pdfs_and_detail_basic(self):
        self.user.band = self.band_basic
        self.user.save()
        url_pdf_show = reverse('show_pdf', args=[self.band_basic.slug, self.show_basic.id])
        self.assertEqual(self.client.get(url_pdf_show).status_code, 200)
        url_pdf_agenda = reverse('agenda_pdf', args=[self.band_basic.slug])
        self.assertEqual(self.client.get(url_pdf_agenda).status_code, 200)

        url_detail = reverse('show_detail', args=[self.band_basic.slug, self.show_basic.id])
        response = self.client.get(url_detail)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')

        self.assertNotIn('Dados do Contrato', html)
        self.assertNotIn('1000,00', html)
        self.assertIn('Hotel ABC', html)

    def test_downgrade_preserves_data(self):
        self.show_advanced.fee = 9999.00
        self.show_advanced.save()
        self.band_advanced.plan_type = 'BASICO'
        self.band_advanced.save()
        self.show_advanced.refresh_from_db()
        self.assertEqual(float(self.show_advanced.fee), 9999.00)
