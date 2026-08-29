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
        # Banda Avançada
        self.band_adv = Band.objects.create(
            name="Banda Avançada",
            slug="banda-avancada",
            plan_type=Band.PlanType.AVANCADO,
            is_active=True
        )
        # Banda Básica
        self.band_bas = Band.objects.create(
            name="Banda Básica",
            slug="banda-basica",
            plan_type=Band.PlanType.BASICO,
            is_active=True
        )
        # Produtor Avançado
        self.produtor_adv = User.objects.create_user(
            username="produtor_adv",
            email="prod_adv@teste.com",
            password="senha",
            role="PRODUTOR",
            band=self.band_adv
        )
        # Integrante Avançado
        self.integrante_adv = User.objects.create_user(
            username="integrante_adv",
            email="int_adv@teste.com",
            password="senha",
            role="INTEGRANTE",
            band=self.band_adv
        )
        # Produtor Básico
        self.produtor_bas = User.objects.create_user(
            username="produtor_bas",
            email="prod_bas@teste.com",
            password="senha",
            role="PRODUTOR",
            band=self.band_bas
        )

    # 1. Bloqueio do Plano Básico, liberação do Plano Avançado e bloqueio para integrantes
    def test_1_permissoes_e_bloqueios(self):
        # 1.1 Produtor Avançado acessa com sucesso
        self.client.login(username="produtor_adv", password="senha")
        res_adv = self.client.get(reverse('commercial_index', args=[self.band_adv.slug]))
        self.assertEqual(res_adv.status_code, 200)
        self.assertIn('Comercial', res_adv.content.decode('utf-8'))

        # 1.2 Integrante recebe 403 Forbidden
        self.client.login(username="integrante_adv", password="senha")
        res_int = self.client.get(reverse('commercial_index', args=[self.band_adv.slug]))
        self.assertEqual(res_int.status_code, 403)

        # 1.3 Produtor Básico recebe 403 Forbidden no backend
        self.client.login(username="produtor_bas", password="senha")
        res_bas = self.client.get(reverse('commercial_index', args=[self.band_bas.slug]))
        self.assertEqual(res_bas.status_code, 403)

        # 1.4 Na página principal de relatórios, Plano Básico visualiza bloqueio com modal
        res_rel = self.client.get(reverse('relatorios_index', args=[self.band_bas.slug]))
        self.assertEqual(res_rel.status_code, 200)
        html_rel = res_rel.content.decode('utf-8')
        self.assertIn('modalAdvancedPlan', html_rel)
        self.assertIn('fa-lock', html_rel)

    # 2. Proteção multibanda contra visualização e alteração por usuários de outra banda
    def test_2_protecao_multibanda(self):
        # Cria solicitação na Banda Avançada
        prop = CommercialProposal.objects.create(
            band=self.band_adv,
            name="Orçamento Secreto",
            date=date(2026, 12, 31),
            time=time(22, 0),
            contact="11999990001",
            origin="Direto",
            fee=Decimal("50000.00"),
            phase=CommercialProposal.Phase.RESERVA,
            created_by=self.produtor_adv
        )

        # Produtor Básico (ou de outra banda) tenta acessar ou alterar -> 403 / 404
        self.client.login(username="produtor_bas", password="senha")
        res_view = self.client.get(reverse('commercial_index', args=[self.band_adv.slug]))
        self.assertEqual(res_view.status_code, 403)

        res_edit = self.client.post(
            reverse('commercial_edit', args=[self.band_bas.slug, prop.id]),
            {'name': 'Invasão'}
        )
        self.assertEqual(res_edit.status_code, 403)

    # 3. Criação de Reserva com um único show vinculado, exibição na Agenda e ordenação cronológica
    def test_3_criacao_reserva_show_agenda_e_ordenacao(self):
        self.client.login(username="produtor_adv", password="senha")
        create_url = reverse('commercial_create', args=[self.band_adv.slug])

        # Cadastra dois orçamentos com datas diferentes para testar ordenação cronológica
        data_show2 = {
            'name': 'Show Distante',
            'date': '2026-11-20',
            'time': '21:00',
            'contact': '(11) 98888-0002',
            'origin': 'Instagram',
            'fee': '15.000,00',
            'phase': 'RESERVA'
        }
        data_show1 = {
            'name': 'Show Próximo',
            'date': '2026-10-10',
            'time': '20:00',
            'contact': '(11) 98888-0001',
            'origin': 'Site',
            'fee': '20.000,00',
            'phase': 'RESERVA'
        }

        r2 = self.client.post(create_url, data_show2, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json()['ok'])

        r1 = self.client.post(create_url, data_show1, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r1.status_code, 200)
        self.assertTrue(r1.json()['ok'])

        # Verifica que os shows foram criados com status PRE_RESERVADO
        prop_prox = CommercialProposal.objects.get(name='Show Próximo')
        self.assertIsNotNone(prop_prox.show)
        self.assertEqual(prop_prox.show.status, 'PRE_RESERVADO')
        self.assertEqual(prop_prox.show.date, date(2026, 10, 10))

        # Verifica exibição na Agenda
        res_cal = self.client.get(reverse('calendario', args=[self.band_adv.slug]))
        html_cal = res_cal.content.decode('utf-8')
        self.assertIn('Show Próximo', html_cal)
        self.assertIn('#ffc107', html_cal)  # Cor de PRE_RESERVADO

        # Verifica ordenação cronológica na listagem do Comercial (Show Próximo antes de Show Distante)
        res_list = self.client.get(reverse('commercial_index', args=[self.band_adv.slug]))
        html_list = res_list.content.decode('utf-8')
        idx_prox = html_list.find('Show Próximo')
        idx_dist = html_list.find('Show Distante')
        self.assertTrue(idx_prox != -1 and idx_dist != -1)
        self.assertTrue(idx_prox < idx_dist, "O show mais próximo deve aparecer antes do mais distante.")

        # Verifica formatação monetária brasileira na coluna Valor (R$ 8.000,00 e R$ 12.500,50)
        data_fee8k = {
            'name': 'Show Fee 8k',
            'date': '2026-10-25',
            'time': '20:00',
            'contact': '(11) 98888-0010',
            'origin': 'Teste Formatação',
            'fee': '8.000,00',
            'phase': 'RESERVA'
        }
        data_fee12k5 = {
            'name': 'Show Fee 12k5',
            'date': '2026-10-26',
            'time': '20:00',
            'contact': '(11) 98888-0011',
            'origin': 'Teste Formatação',
            'fee': '12500,50',
            'phase': 'RESERVA'
        }
        self.client.post(create_url, data_fee8k, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.client.post(create_url, data_fee12k5, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        res_fmt = self.client.get(reverse('commercial_index', args=[self.band_adv.slug]))
        html_fmt = res_fmt.content.decode('utf-8')

        # Formato correto com separador de milhar DEVE estar presente
        self.assertIn('R$ 8.000,00', html_fmt, "Fee 8000 deve ser exibida como 'R$ 8.000,00'")
        self.assertIn('R$ 12.500,50', html_fmt, "Fee 12500.50 deve ser exibida como 'R$ 12.500,50'")

        # Formato incorreto sem separador de milhar NÃO deve estar presente
        self.assertNotIn('R$ 8000,00', html_fmt, "Formato 'R$ 8000,00' (sem separador) não deve aparecer")

    # 4. Criação de Fechado mapeada para Show Confirmado
    def test_4_criacao_fechado_mapeada_para_confirmado(self):
        self.client.login(username="produtor_adv", password="senha")
        create_url = reverse('commercial_create', args=[self.band_adv.slug])
        data = {
            'name': 'Festival de Verão',
            'date': '2026-12-15',
            'time': '23:00',
            'contact': '(11) 97777-0001',
            'origin': 'Produtor Parceiro',
            'fee': '80.000,00',
            'phase': 'FECHADO'
        }
        res = self.client.post(create_url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)

        prop = CommercialProposal.objects.get(name='Festival de Verão')
        self.assertEqual(prop.phase, CommercialProposal.Phase.FECHADO)
        self.assertIsNotNone(prop.show)
        self.assertEqual(prop.show.status, 'CONFIRMADO')
        self.assertEqual(prop.show.fee, Decimal('80000.00'))

        # Na Agenda deve aparecer na cor verde #198754
        res_cal = self.client.get(reverse('calendario', args=[self.band_adv.slug]))
        self.assertIn('Festival de Verão', res_cal.content.decode('utf-8'))
        self.assertIn('#198754', res_cal.content.decode('utf-8'))

    # 5. Mudança Reserva → Fechado sem duplicar o show
    def test_5_mudanca_reserva_para_fechado_sem_duplicar(self):
        self.client.login(username="produtor_adv", password="senha")
        prop = CommercialProposal.objects.create(
            band=self.band_adv,
            name="Show Corporativo",
            date=date(2026, 9, 20),
            time=time(19, 0),
            contact="11966660001",
            origin="Indicação",
            fee=Decimal("30000.00"),
            phase=CommercialProposal.Phase.RESERVA,
            created_by=self.produtor_adv
        )
        # Cria show inicial
        show_inicial = Show.objects.create(
            band=self.band_adv,
            title=prop.name,
            date=prop.date,
            show_time=prop.time,
            status='PRE_RESERVADO',
            fee=prop.fee
        )
        prop.show = show_inicial
        prop.save()

        shows_count_before = Show.objects.filter(band=self.band_adv).count()

        # Atualiza a fase para FECHADO
        edit_url = reverse('commercial_edit', args=[self.band_adv.slug, prop.id])
        data = {
            'name': 'Show Corporativo Atualizado',
            'date': '2026-09-20',
            'time': '19:30',
            'contact': '(11) 96666-0001',
            'origin': 'Indicação',
            'fee': '35.000,00',
            'phase': 'FECHADO'
        }
        res = self.client.post(edit_url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)

        shows_count_after = Show.objects.filter(band=self.band_adv).count()
        self.assertEqual(shows_count_before, shows_count_after, "Não deve criar um novo show ao mudar de fase.")

        prop.refresh_from_db()
        self.assertEqual(prop.phase, CommercialProposal.Phase.FECHADO)
        self.assertEqual(prop.show.id, show_inicial.id)
        self.assertEqual(prop.show.status, 'CONFIRMADO')
        self.assertEqual(prop.show.title, 'Show Corporativo Atualizado')
        self.assertEqual(prop.show.show_time, time(19, 30))

    # 6. Mudança para Desistência retirando o evento da Agenda e preservando o histórico
    def test_6_mudanca_para_desistencia_retira_da_agenda(self):
        self.client.login(username="produtor_adv", password="senha")
        prop = CommercialProposal.objects.create(
            band=self.band_adv,
            name="Show Cancelado Posteriormente",
            date=date(2026, 11, 5),
            time=time(22, 0),
            contact="11955550001",
            origin="Direct",
            fee=Decimal("25000.00"),
            phase=CommercialProposal.Phase.RESERVA,
            created_by=self.produtor_adv
        )
        show = Show.objects.create(
            band=self.band_adv,
            title=prop.name,
            date=prop.date,
            show_time=prop.time,
            status='PRE_RESERVADO'
        )
        prop.show = show
        prop.save()

        # Altera para DESISTENCIA
        edit_url = reverse('commercial_edit', args=[self.band_adv.slug, prop.id])
        data = {
            'name': 'Show Cancelado Posteriormente',
            'date': '2026-11-05',
            'time': '22:00',
            'contact': '(11) 95555-0001',
            'origin': 'Direct',
            'fee': '25.000,00',
            'phase': 'DESISTENCIA'
        }
        res = self.client.post(edit_url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)

        prop.refresh_from_db()
        self.assertEqual(prop.phase, CommercialProposal.Phase.DESISTENCIA)
        self.assertEqual(prop.show.status, 'CANCELADO')

        # Na aba Desistências do Comercial ele continua existindo
        res_list = self.client.get(reverse('commercial_index', args=[self.band_adv.slug]))
        self.assertIn('Show Cancelado Posteriormente', res_list.content.decode('utf-8'))

    # 7. Reativação de Desistência sem criar um segundo show
    def test_7_reativacao_de_desistencia_sem_duplicar(self):
        self.client.login(username="produtor_adv", password="senha")
        show = Show.objects.create(
            band=self.band_adv,
            title="Show Reativado",
            date=date(2026, 12, 20),
            show_time=time(21, 0),
            status='CANCELADO'
        )
        prop = CommercialProposal.objects.create(
            band=self.band_adv,
            show=show,
            name="Show Reativado",
            date=date(2026, 12, 20),
            time=time(21, 0),
            contact="11944440001",
            origin="Email",
            fee=Decimal("40000.00"),
            phase=CommercialProposal.Phase.DESISTENCIA,
            created_by=self.produtor_adv
        )

        total_shows_antes = Show.objects.filter(band=self.band_adv).count()

        # Reativa para FECHADO
        edit_url = reverse('commercial_edit', args=[self.band_adv.slug, prop.id])
        data = {
            'name': 'Show Reativado',
            'date': '2026-12-20',
            'time': '21:00',
            'contact': '(11) 94444-0001',
            'origin': 'Email',
            'fee': '40.000,00',
            'phase': 'FECHADO'
        }
        res = self.client.post(edit_url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res.status_code, 200)

        total_shows_depois = Show.objects.filter(band=self.band_adv).count()
        self.assertEqual(total_shows_antes, total_shows_depois)

        prop.refresh_from_db()
        self.assertEqual(prop.phase, CommercialProposal.Phase.FECHADO)
        self.assertEqual(prop.show.id, show.id)
        self.assertEqual(prop.show.status, 'CONFIRMADO')

    # 8. Aviso de conflito na mesma data, desconsiderando o próprio show na edição
    def test_8_aviso_conflito_de_agenda(self):
        self.client.login(username="produtor_adv", password="senha")
        conflict_url = reverse('commercial_check_conflict', args=[self.band_adv.slug])

        # Cria um show existente na data 2026-08-10
        existing_show = Show.objects.create(
            band=self.band_adv,
            title="Show de Aniversário",
            date=date(2026, 8, 10),
            show_time=time(20, 0),
            status='CONFIRMADO'
        )

        # Consulta conflito para 2026-08-10 -> deve indicar conflito
        res1 = self.client.get(f"{conflict_url}?date=2026-08-10")
        data1 = res1.json()
        self.assertTrue(data1['has_conflict'])
        self.assertIn('Atenção: Já existe um show para essa data', data1['message'])

        # Consulta para data livre -> sem conflito
        res2 = self.client.get(f"{conflict_url}?date=2026-08-11")
        self.assertFalse(res2.json()['has_conflict'])

        # Na edição do próprio show/proposta, deve desconsiderar o próprio show
        prop = CommercialProposal.objects.create(
            band=self.band_adv,
            show=existing_show,
            name="Show de Aniversário",
            date=date(2026, 8, 10),
            time=time(20, 0),
            contact="11933330001",
            origin="Direto",
            fee=Decimal("10000.00"),
            phase=CommercialProposal.Phase.FECHADO,
            created_by=self.produtor_adv
        )
        res3 = self.client.get(f"{conflict_url}?date=2026-08-10&proposal_id={prop.id}")
        self.assertFalse(res3.json()['has_conflict'], "Ao editar o próprio show, não deve acusar conflito com ele mesmo.")

    # 9. Upload, acesso protegido e exclusão individual de anexos
    def test_9_upload_acesso_protegido_e_exclusao_anexos(self):
        self.client.login(username="produtor_adv", password="senha")
        fake_pdf = SimpleUploadedFile("contrato_minuta.pdf", b"%PDF-1.4 Test Content", content_type="application/pdf")

        create_url = reverse('commercial_create', args=[self.band_adv.slug])
        data = {
            'name': 'Show com Minuta',
            'date': '2026-10-01',
            'time': '20:00',
            'contact': '(11) 92222-0001',
            'origin': 'Site',
            'fee': '10.000,00',
            'phase': 'RESERVA',
            'documents': [fake_pdf]
        }
        res_post = self.client.post(create_url, data, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_post.status_code, 200)

        prop = CommercialProposal.objects.get(name='Show com Minuta')
        self.assertEqual(prop.documents.count(), 1)
        doc = prop.documents.first()
        self.assertEqual(doc.original_name, 'contrato_minuta.pdf')

        # Download protegido por produtor autorizado
        dl_url = reverse('download_commercial_document', args=[self.band_adv.slug, doc.id])
        res_dl = self.client.get(dl_url)
        self.assertEqual(res_dl.status_code, 200)

        # Exclusão individual do anexo
        del_doc_url = reverse('commercial_delete_document', args=[self.band_adv.slug, prop.id, doc.id])
        res_del = self.client.post(del_doc_url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_del.status_code, 200)
        self.assertTrue(res_del.json()['ok'])
        self.assertEqual(prop.documents.count(), 0)

    # 10. Exclusão atômica da solicitação, dos anexos e do show vinculado
    def test_10_exclusao_atomica_solicitacao_show_e_anexos(self):
        self.client.login(username="produtor_adv", password="senha")
        fake_pdf = SimpleUploadedFile("anexo.pdf", b"%PDF-1.4 Teste", content_type="application/pdf")
        
        show = Show.objects.create(
            band=self.band_adv,
            title="Show Para Deletar",
            date=date(2026, 11, 1),
            show_time=time(22, 0),
            status='PRE_RESERVADO'
        )
        prop = CommercialProposal.objects.create(
            band=self.band_adv,
            show=show,
            name="Show Para Deletar",
            date=date(2026, 11, 1),
            time=time(22, 0),
            contact="11911110001",
            origin="Email",
            fee=Decimal("15000.00"),
            phase=CommercialProposal.Phase.RESERVA,
            created_by=self.produtor_adv
        )
        doc = CommercialProposalDocument.objects.create(
            proposal=prop,
            file=fake_pdf,
            original_name="anexo.pdf",
            uploaded_by=self.produtor_adv
        )

        show_id = show.id
        doc_id = doc.id
        prop_id = prop.id

        # Exclui a solicitação via POST
        delete_url = reverse('commercial_delete', args=[self.band_adv.slug, prop.id])
        res = self.client.post(delete_url)
        self.assertEqual(res.status_code, 302)

        # Confirma que a solicitação, o show e o anexo foram todos excluídos
        self.assertFalse(CommercialProposal.objects.filter(id=prop_id).exists())
        self.assertFalse(Show.objects.filter(id=show_id).exists())
        self.assertFalse(CommercialProposalDocument.objects.filter(id=doc_id).exists())
