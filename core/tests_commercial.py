
import tempfile
import io
from datetime import date, time
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Band, User, Show, CommercialProposal, CommercialProposalDocument

class CommercialModuleTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.band_adv = Band.objects.create(name="Banda Avançada", slug="banda-avancada", plan_type=Band.PlanType.AVANCADO, is_active=True)
        self.band_bas = Band.objects.create(name="Banda Básica", slug="banda-basica", plan_type=Band.PlanType.BASICO, is_active=True)
        self.produtor_adv = User.objects.create_user(username="produtor_adv", email="prod_adv@teste.com", password="senha", role="PRODUTOR", band=self.band_adv)
        self.integrante_adv = User.objects.create_user(username="integrante_adv", email="int_adv@teste.com", password="senha", role="INTEGRANTE", band=self.band_adv)
        self.produtor_bas = User.objects.create_user(username="produtor_bas", email="prod_bas@teste.com", password="senha", role="PRODUTOR", band=self.band_bas)

    def test_1_permissoes_e_bloqueios(self):
        self.client.login(username="produtor_adv", password="senha")
        res_adv = self.client.get(reverse('commercial_index', args=[self.band_adv.slug]))
        self.assertEqual(res_adv.status_code, 200)

        self.client.login(username="integrante_adv", password="senha")
        self.assertEqual(self.client.get(reverse('commercial_index', args=[self.band_adv.slug])).status_code, 403)

        self.client.login(username="produtor_bas", password="senha")
        self.assertEqual(self.client.get(reverse('commercial_index', args=[self.band_bas.slug])).status_code, 403)

    def test_2_protecao_multibanda(self):
        prop = CommercialProposal.objects.create(
            band=self.band_adv, name="Secreto", date=date(2026, 12, 31),
            phase=CommercialProposal.Phase.RESERVA, created_by=self.produtor_adv
        )
        self.client.login(username="produtor_bas", password="senha")
        self.assertEqual(self.client.get(reverse('commercial_index', args=[self.band_adv.slug])).status_code, 403)
        self.assertEqual(self.client.post(reverse('commercial_edit', args=[self.band_bas.slug, prop.id]), {'name': 'Invasão'}).status_code, 403)

    def test_3_layout_cabecalho_secoes_dropdown(self):
        self.client.login(username="produtor_adv", password="senha")
        from core.models import CommercialProposal
        CommercialProposal.objects.create(band=self.band_adv, name='Test Dropdown', date='2026-12-10', phase='RESERVA')
        res = self.client.get(reverse('commercial_index', args=[self.band_adv.slug]))
        html = res.content.decode('utf-8')

        # 1. Voltar immediately before Novo Orçamento
        idx_voltar = html.find('Voltar')
        idx_novo = html.find('Novo Orçamento')
        self.assertTrue(0 < idx_voltar < idx_novo)

        # 2. Ausência de abas (tabs)
        self.assertNotIn('commercialTabs', html)
        self.assertNotIn('commercialTabContent', html)

        # 3. Duas seções empilhadas
        self.assertIn('Reservas</h5>', html)
        self.assertIn('Fechados e Desistências</h5>', html)

        # 4. Coluna Fase presente, Contato ausente
        self.assertIn('<th class="py-3 text-center">Fase</th>', html)
        self.assertNotIn('Contato</th>', html)

        # 5. Renderiza a linha com botão e dropdown
        self.assertIn('Test Dropdown', html)
        self.assertIn('fa-gear', html)
        self.assertIn('dropdown-menu dropdown-menu-end shadow-sm border-0', html)

        idx_editar = html.find('Editar')
        idx_excluir = html.find('Excluir', idx_editar)
        self.assertTrue(idx_editar > 0 and idx_excluir > 0, "Editar and Excluir must exist")
        self.assertTrue(idx_editar < idx_excluir, "Editar must appear before Excluir")

        # Dropdown ul block check (ensuring no <hr> or dropdown-divider between them)
        dropdown_html = html[html.find('dropdown-menu dropdown-menu-end shadow-sm border-0'):html.find('</ul>', html.find('dropdown-menu dropdown-menu-end shadow-sm border-0'))]
        self.assertNotIn('<hr', dropdown_html)
        self.assertNotIn('dropdown-divider', dropdown_html)


        # 5. Dropdown Editar e Excluir sem hr


        self.assertNotIn('dropdown-divider', html)

    def test_4_filtros_buscas_limpar(self):
        self.client.login(username="produtor_adv", password="senha")
        CommercialProposal.objects.create(band=self.band_adv, name="Show R", date=date(2026,10,1), phase='RESERVA')
        CommercialProposal.objects.create(band=self.band_adv, name="Show F", date=date(2026,10,2), phase='FECHADO')
        CommercialProposal.objects.create(band=self.band_adv, name="Show D", date=date(2026,10,3), phase='DESISTENCIA')

        # Sem filtro
        html = self.client.get(reverse('commercial_index', args=[self.band_adv.slug])).content.decode('utf-8')
        self.assertIn('Show R', html)
        self.assertIn('Show F', html)
        self.assertIn('Show D', html)

        # Filtro de Fase: Reserva
        url = reverse('commercial_index', args=[self.band_adv.slug])
        html = self.client.get(url + '?phase=RESERVA').content.decode('utf-8')
        self.assertIn('Show R', html)
        self.assertNotIn('Show F', html)
        self.assertNotIn('Show D', html)

        # Filtro de Nome
        html = self.client.get(url + '?name=Show F').content.decode('utf-8')
        self.assertNotIn('Show R', html)
        self.assertIn('Show F', html)

        # Botões Limpar e Filtrar
        self.assertIn('fa-eraser', html)
        self.assertIn('fa-filter', html)

    def test_5_campos_opcionais_e_formatacao(self):
        self.client.login(username="produtor_adv", password="senha")
        create_url = reverse('commercial_create', args=[self.band_adv.slug])

        # 1. Criar com campos opcionais vazios
        data_vazio = {'name': 'Sem Opcionais', 'date': '2026-11-01', 'phase': 'RESERVA', 'fee': ''}
        self.client.post(create_url, data_vazio, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        prop_vazia = CommercialProposal.objects.get(name='Sem Opcionais')
        self.assertIsNone(prop_vazia.time)
        self.assertIsNone(prop_vazia.fee)
        self.assertFalse(bool(prop_vazia.contact))

        # 2. Criar com valores e verificar formatação
        data_cheio = {'name': 'Com Valores', 'date': '2026-11-01', 'time': '12:00', 'phase': 'RESERVA', 'fee': '8.000,00'}
        self.client.post(create_url, data_cheio, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        # Verificar ordenação: 'Com Valores' (tem time) deve vir antes de 'Sem Opcionais' (time=None) no mesmo date
        res = self.client.get(reverse('commercial_index', args=[self.band_adv.slug]))
        html = res.content.decode('utf-8')

        idx_cheio = html.find('Com Valores')
        idx_vazio = html.find('Sem Opcionais')
        self.assertTrue(idx_cheio < idx_vazio)

        # Formatação
        self.assertIn('R$ 8.000,00', html)
        self.assertIn('<td>—</td>', html) # Origin/Time fallback
        self.assertIn('<td class="fw-semibold text-dark">—</td>', html) # Fee fallback

    def test_6_criacao_edicao_com_horario_opcional_agenda(self):
        self.client.login(username="produtor_adv", password="senha")
        create_url = reverse('commercial_create', args=[self.band_adv.slug])

        # Show sem horário
        self.client.post(create_url, {'name': 'No Time', 'date': '2026-09-01', 'phase': 'FECHADO'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        prop = CommercialProposal.objects.get(name='No Time')
        self.assertEqual(prop.show.status, 'CONFIRMADO')
        self.assertIsNone(prop.show.show_time)

        # Checa ausência de horário falso 00:00 na tabela
        html = self.client.get(reverse('commercial_index', args=[self.band_adv.slug])).content.decode('utf-8')
        self.assertNotIn('00:00', html[html.find('No Time'):html.find('No Time')+200])

    def test_7_mudanca_para_desistencia_retira_da_agenda(self):
        self.client.login(username="produtor_adv", password="senha")
        show = Show.objects.create(band=self.band_adv, title="A Cancelar", date=date(2026, 11, 5), status='CONFIRMADO')
        prop = CommercialProposal.objects.create(band=self.band_adv, show=show, name="A Cancelar", date=date(2026, 11, 5), phase=CommercialProposal.Phase.FECHADO, created_by=self.produtor_adv)

        edit_url = reverse('commercial_edit', args=[self.band_adv.slug, prop.id])
        self.client.post(edit_url, {'name': 'Cancelado', 'date': '2026-11-05', 'phase': 'DESISTENCIA'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        prop.refresh_from_db()
        self.assertEqual(prop.phase, CommercialProposal.Phase.DESISTENCIA)
        self.assertEqual(prop.show.status, 'CANCELADO')

    def test_8_reativacao_de_desistencia_sem_duplicar(self):
        self.client.login(username="produtor_adv", password="senha")
        show = Show.objects.create(band=self.band_adv, title="Reativar", date=date(2026, 12, 20), status='CANCELADO')
        prop = CommercialProposal.objects.create(band=self.band_adv, show=show, name="Reativar", date=date(2026, 12, 20), phase=CommercialProposal.Phase.DESISTENCIA, created_by=self.produtor_adv)

        total = Show.objects.count()
        self.client.post(reverse('commercial_edit', args=[self.band_adv.slug, prop.id]), {'name': 'Reativar', 'date': '2026-12-20', 'phase': 'FECHADO'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.assertEqual(total, Show.objects.count())
        prop.refresh_from_db()
        self.assertEqual(prop.show.status, 'CONFIRMADO')

    def test_9_upload_acesso_protegido_e_exclusao_anexos(self):
        self.client.login(username="produtor_adv", password="senha")
        fake_pdf = SimpleUploadedFile("contrato.pdf", b"%PDF-1.4 Test Content", content_type="application/pdf")

        res = self.client.post(reverse('commercial_create', args=[self.band_adv.slug]), {
            'name': 'Doc Test', 'date': '2026-10-01', 'phase': 'RESERVA', 'documents': [fake_pdf]
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        if res.status_code != 200:
            print("test_9 POST error:", res.content)

        prop = CommercialProposal.objects.get(name='Doc Test')
        self.assertEqual(prop.documents.count(), 1)

        del_url = reverse('commercial_delete_document', args=[self.band_adv.slug, prop.id, prop.documents.first().id])
        self.client.post(del_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(prop.documents.count(), 0)

    def test_10_exclusao_atomica_solicitacao_show_e_anexos(self):
        self.client.login(username="produtor_adv", password="senha")
        fake_pdf = SimpleUploadedFile("anexo.pdf", b"%PDF-1.4 Test Content", content_type="application/pdf")
        show = Show.objects.create(band=self.band_adv, title="Delete", date=date(2026, 11, 1), status='PRE_RESERVADO')
        prop = CommercialProposal.objects.create(band=self.band_adv, show=show, name="Delete", date=date(2026, 11, 1), phase=CommercialProposal.Phase.RESERVA, created_by=self.produtor_adv)
        doc = CommercialProposalDocument.objects.create(proposal=prop, file=fake_pdf, original_name="anexo.pdf", uploaded_by=self.produtor_adv)

        self.client.post(reverse('commercial_delete', args=[self.band_adv.slug, prop.id]))
        self.assertFalse(CommercialProposal.objects.filter(id=prop.id).exists())
        self.assertFalse(Show.objects.filter(id=show.id).exists())
        self.assertFalse(CommercialProposalDocument.objects.filter(id=doc.id).exists())

