import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import Band, User, Show, CommercialProposal, Notification
from core.services.commercial_sync import (
    link_show_to_commercial,
    sync_proposal_to_show,
    sync_show_to_proposal,
    map_phase_to_show_status,
    map_show_status_to_phase
)

class CommercialSyncBidirectionalTests(TestCase):
    def setUp(self):
        self.band = Band.objects.create(
            name="Banda Sincronia",
            slug="banda-sincronia",
            plan_type=Band.PlanType.AVANCADO,
            is_active=True
        )
        self.produtor = User.objects.create_user(
            username="produtor_sync",
            email="prod_sync@teste.com",
            password="senha",
            role="PRODUTOR",
            band=self.band
        )
        self.integrante = User.objects.create_user(
            username="integrante_sync",
            email="int_sync@teste.com",
            password="senha",
            role="INTEGRANTE",
            band=self.band
        )
        self.client = Client()
        self.client.login(username="produtor_sync", password="senha")

    def test_1_show_sem_vinculo_botao_outline(self):
        """1. Show sem vínculo comercial exibe botão outline azul sem ícone de check."""
        show = Show.objects.create(
            band=self.band,
            title="Show Independente",
            date=datetime.date(2026, 11, 10),
            show_time=datetime.time(21, 0),
            status=Show.STATUS_CONFIRMADO
        )
        resp = self.client.get(reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context.get('is_linked_commercial'))
        html = resp.content.decode('utf-8')
        self.assertIn('btn-outline-primary', html)
        self.assertIn('id="btnComercialLink"', html)
        # O botão não vinculado deve conter 'Comercial' sem o ícone de check dentro dele
        btn_start = html.find('id="btnComercialLink"')
        btn_end = html.find('</button>', btn_start)
        btn_html = html[btn_start:btn_end]
        self.assertNotIn('fa-check', btn_html)

    def test_2_clique_comercial_cria_vinculo(self):
        """2. Chamar endpoint de vínculo cria o CommercialProposal e retorna JSON."""
        show = Show.objects.create(
            band=self.band,
            title="Show Para Vincular",
            date=datetime.date(2026, 11, 12),
            show_time=datetime.time(22, 0),
            venue="Teatro Municipal",
            fee=Decimal("15000.00"),
            contractor_name="João Contratante",
            contractor_phone="11999998888",
            status=Show.STATUS_CONFIRMADO
        )
        url = reverse('show_link_commercial', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        resp = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get('ok'))
        self.assertTrue(data.get('linked'))

        # Confere se proposal foi criada
        proposal = CommercialProposal.objects.filter(show=show).first()
        self.assertIsNotNone(proposal)
        self.assertEqual(proposal.name, "Show Para Vincular")
        self.assertEqual(proposal.date, datetime.date(2026, 11, 12))
        self.assertEqual(proposal.time, datetime.time(22, 0))
        self.assertEqual(proposal.location, "Teatro Municipal")
        self.assertEqual(proposal.fee, Decimal("15000.00"))
        self.assertEqual(proposal.contact_name, "João Contratante")
        self.assertEqual(proposal.contact, "11999998888")
        self.assertEqual(proposal.phase, CommercialProposal.Phase.FECHADO)

    def test_3_e_4_pos_vinculo_e_recarregamento_persiste_azul_preenchido(self):
        """3 e 4. Após vínculo, botão fica azul preenchido com check e persiste no reload."""
        show = Show.objects.create(
            band=self.band,
            title="Show Já Vinculado",
            date=datetime.date(2026, 11, 15),
            status=Show.STATUS_PRE_RESERVADO
        )
        CommercialProposal.objects.create(
            band=self.band,
            show=show,
            name=show.title,
            date=show.date,
            phase=CommercialProposal.Phase.RESERVA,
            created_by=self.produtor
        )

        resp = self.client.get(reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id}))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context.get('is_linked_commercial'))
        html = resp.content.decode('utf-8')
        self.assertIn('btn-primary', html)
        self.assertIn('<i class="fa-solid fa-check me-1"></i> Comercial', html)

    def test_5_chamada_duplicada_nao_duplica_proposal(self):
        """5. Chamadas repetidas de vínculo não duplicam a CommercialProposal."""
        show = Show.objects.create(
            band=self.band,
            title="Show Idempotente",
            date=datetime.date(2026, 11, 20),
            status=Show.STATUS_CONFIRMADO
        )
        prop1, created1 = link_show_to_commercial(show, user=self.produtor)
        self.assertTrue(created1)
        prop2, created2 = link_show_to_commercial(show, user=self.produtor)
        self.assertFalse(created2)
        self.assertEqual(prop1.id, prop2.id)
        self.assertEqual(CommercialProposal.objects.filter(show=show).count(), 1)

    def test_6_e_7_edicao_comercial_atualiza_agenda(self):
        """6 e 7. Editar data e horário no Comercial atualiza Show na Agenda."""
        show = Show.objects.create(
            band=self.band,
            title="Show Sinc",
            date=datetime.date(2026, 10, 1),
            show_time=datetime.time(20, 0),
            status=Show.STATUS_CONFIRMADO
        )
        proposal = CommercialProposal.objects.create(
            band=self.band,
            show=show,
            name="Show Sinc",
            date=show.date,
            time=show.show_time,
            phase=CommercialProposal.Phase.FECHADO,
            created_by=self.produtor
        )

        edit_url = reverse('commercial_edit', kwargs={'band_slug': self.band.slug, 'pk': proposal.id})
        payload = {
            'name': 'Show Sinc Editado',
            'date': '2026-10-02',
            'time': '22:30',
            'contact_name': 'Contato Atualizado',
            'contact': '11988887777',
            'location': 'Novo Espaço',
            'fee': '18000.00',
            'phase': 'FECHADO',
        }
        resp = self.client.post(edit_url, payload)
        self.assertEqual(resp.status_code, 200)

        show.refresh_from_db()
        self.assertEqual(show.title, 'Show Sinc Editado')
        self.assertEqual(show.date, datetime.date(2026, 10, 2))
        self.assertEqual(show.show_time, datetime.time(22, 30))
        self.assertEqual(show.contractor_name, 'Contato Atualizado')
        self.assertEqual(show.contractor_phone, '11988887777')
        self.assertEqual(show.venue, 'Novo Espaço')
        self.assertEqual(show.fee, Decimal('18000.00'))

    def test_8_edicao_agenda_atualiza_comercial(self):
        """8. Editar campos compartilhados na Agenda atualiza CommercialProposal correspondente."""
        show = Show.objects.create(
            band=self.band,
            title="Show Agenda",
            date=datetime.date(2026, 10, 5),
            show_time=datetime.time(19, 0),
            status=Show.STATUS_CONFIRMADO,
            fee=Decimal("10000.00"),
            venue="Clube 1",
            contractor_name="Contratante A",
            contractor_phone="11911112222"
        )
        proposal = CommercialProposal.objects.create(
            band=self.band,
            show=show,
            name=show.title,
            date=show.date,
            time=show.show_time,
            location=show.venue,
            fee=show.fee,
            contact_name=show.contractor_name,
            contact=show.contractor_phone,
            origin="Instagram",
            phase=CommercialProposal.Phase.FECHADO,
            created_by=self.produtor
        )

        edit_url = reverse('shows_edit', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        payload = {
            'title': 'Show Agenda Modificado',
            'date': '2026-10-06',
            'show_time': '21:30',
            'status': 'CONFIRMADO',
            'payment_status': 'PENDENTE',
            'fee': '14500.00',
            'venue': 'Clube 2',
            'contractor_name': 'Contratante B',
            'contractor_phone': '11933334444',
            'documents-TOTAL_FORMS': '0',
            'documents-INITIAL_FORMS': '0',
        }
        resp = self.client.post(edit_url, payload)
        self.assertEqual(resp.status_code, 302)

        proposal.refresh_from_db()
        self.assertEqual(proposal.name, 'Show Agenda Modificado')
        self.assertEqual(proposal.date, datetime.date(2026, 10, 6))
        self.assertEqual(proposal.time, datetime.time(21, 30))
        self.assertEqual(proposal.fee, Decimal('14500.00'))
        self.assertEqual(proposal.location, 'Clube 2')
        self.assertEqual(proposal.contact_name, 'Contratante B')
        self.assertEqual(proposal.contact, '11933334444')
        # Preserva campo exclusivo do comercial
        self.assertEqual(proposal.origin, 'Instagram')

    def test_9_e_10_transicoes_status_comercial_para_agenda(self):
        """9 e 10. RESERVA -> PRE_RESERVADO e FECHADO -> CONFIRMADO."""
        show = Show.objects.create(
            band=self.band,
            title="Show Status",
            date=datetime.date(2026, 10, 10),
            status=Show.STATUS_PRE_RESERVADO
        )
        proposal = CommercialProposal.objects.create(
            band=self.band,
            show=show,
            name=show.title,
            date=show.date,
            phase=CommercialProposal.Phase.RESERVA,
            created_by=self.produtor
        )

        # Atualiza para FECHADO no comercial
        proposal.phase = CommercialProposal.Phase.FECHADO
        proposal.save()
        sync_proposal_to_show(proposal, actor=self.produtor)
        show.refresh_from_db()
        self.assertEqual(show.status, Show.STATUS_CONFIRMADO)

        # Atualiza para DESISTENCIA no comercial
        proposal.phase = CommercialProposal.Phase.DESISTENCIA
        proposal.save()
        sync_proposal_to_show(proposal, actor=self.produtor)
        show.refresh_from_db()
        self.assertEqual(show.status, Show.STATUS_CANCELADO)

        # Atualiza de volta para RESERVA no comercial
        proposal.phase = CommercialProposal.Phase.RESERVA
        proposal.save()
        sync_proposal_to_show(proposal, actor=self.produtor)
        show.refresh_from_db()
        self.assertEqual(show.status, Show.STATUS_PRE_RESERVADO)

    def test_11_transicoes_status_agenda_para_comercial(self):
        """11. Alteração de status pela Agenda atualiza Comercial."""
        show = Show.objects.create(
            band=self.band,
            title="Show Agenda Status",
            date=datetime.date(2026, 10, 12),
            status=Show.STATUS_PRE_RESERVADO
        )
        proposal = CommercialProposal.objects.create(
            band=self.band,
            show=show,
            name=show.title,
            date=show.date,
            phase=CommercialProposal.Phase.RESERVA,
            created_by=self.produtor
        )

        # Muda para CONFIRMADO na Agenda
        show.status = Show.STATUS_CONFIRMADO
        show.save()
        sync_show_to_proposal(show, actor=self.produtor)
        proposal.refresh_from_db()
        self.assertEqual(proposal.phase, CommercialProposal.Phase.FECHADO)

        # Muda para CANCELADO na Agenda
        show.status = Show.STATUS_CANCELADO
        show.save()
        sync_show_to_proposal(show, actor=self.produtor)
        proposal.refresh_from_db()
        self.assertEqual(proposal.phase, CommercialProposal.Phase.DESISTENCIA)

    def test_12_e_13_campos_exclusivos_preservados(self):
        """12 e 13. Campos exclusivos do Comercial e da Agenda permanecem intactos na sincronia."""
        show = Show.objects.create(
            band=self.band,
            title="Show Campos Exclusivos",
            date=datetime.date(2026, 10, 15),
            status=Show.STATUS_CONFIRMADO,
            city="Belo Horizonte",
            departure_location="Aeroporto de Congonhas",
            internal_notes="Notas de produção secretas",
            band_notes="Notas da banda"
        )
        proposal = CommercialProposal.objects.create(
            band=self.band,
            show=show,
            name="Show Comercial Especial",
            date=show.date,
            origin="Indicação VIP",
            phase=CommercialProposal.Phase.FECHADO,
            created_by=self.produtor
        )

        # Sincroniza Show -> Proposal
        sync_show_to_proposal(show, actor=self.produtor)
        proposal.refresh_from_db()
        self.assertEqual(proposal.origin, "Indicação VIP")

        # Sincroniza Proposal -> Show
        sync_proposal_to_show(proposal, actor=self.produtor)
        show.refresh_from_db()
        self.assertEqual(show.city, "Belo Horizonte")
        self.assertEqual(show.departure_location, "Aeroporto de Congonhas")
        self.assertEqual(show.internal_notes, "Notas de produção secretas")
        self.assertEqual(show.band_notes, "Notas da banda")

    def test_14_show_sem_vinculo_nao_cria_comercial_automaticamente(self):
        """14. Shows criados diretamente na Agenda não criam registro no Comercial."""
        initial_count = CommercialProposal.objects.count()
        show = Show.objects.create(
            band=self.band,
            title="Show Só Agenda",
            date=datetime.date(2026, 10, 18),
            status=Show.STATUS_CONFIRMADO
        )
        self.assertEqual(CommercialProposal.objects.count(), initial_count)
        self.assertFalse(CommercialProposal.objects.filter(show=show).exists())

    def test_15_nao_ocorre_loop_ou_recursao(self):
        """15. Prevenção de loop/recursão em chamadas cruzadas de sincronia."""
        show = Show.objects.create(
            band=self.band,
            title="Show Anti Loop",
            date=datetime.date(2026, 10, 20),
            status=Show.STATUS_CONFIRMADO
        )
        proposal = CommercialProposal.objects.create(
            band=self.band,
            show=show,
            name=show.title,
            date=show.date,
            phase=CommercialProposal.Phase.FECHADO,
            created_by=self.produtor
        )

        # Executa sincronia de ambos os lados em sequência
        sync_proposal_to_show(proposal)
        sync_show_to_proposal(show)
        sync_proposal_to_show(proposal)

        show.refresh_from_db()
        proposal.refresh_from_db()
        self.assertEqual(show.title, "Show Anti Loop")
        self.assertEqual(proposal.name, "Show Anti Loop")

    def test_16_e_17_regras_bp_pend_46_preservadas_na_sincronia(self):
        """16 e 17. Regras da BP-PEND-46 válidas em transições e horários sem duplicação de notificação."""
        show = Show.objects.create(
            band=self.band,
            title="Show BP 46",
            date=datetime.date(2026, 10, 25),
            show_time=datetime.time(20, 0),
            status=Show.STATUS_PRE_RESERVADO
        )
        proposal = CommercialProposal.objects.create(
            band=self.band,
            show=show,
            name=show.title,
            date=show.date,
            time=show.show_time,
            phase=CommercialProposal.Phase.RESERVA,
            created_by=self.produtor
        )

        # 1. Alterar horário enquanto em RESERVA -> NÃO deve gerar notificação
        edit_url = reverse('commercial_edit', kwargs={'band_slug': self.band.slug, 'pk': proposal.id})
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(edit_url, {
                'name': proposal.name,
                'date': proposal.date.strftime('%Y-%m-%d'),
                'time': '21:30',
                'phase': 'RESERVA'
            })
        show.refresh_from_db()
        self.assertEqual(show.show_time, datetime.time(21, 30))
        self.assertEqual(Notification.objects.filter(related_show_id=show.id).count(), 0)

        # 2. Transição RESERVA -> FECHADO com alteração de horário simultânea -> apenas SHOW_CONFIRMED
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(edit_url, {
                'name': proposal.name,
                'date': proposal.date.strftime('%Y-%m-%d'),
                'time': '22:00',
                'phase': 'FECHADO'
            })
        show.refresh_from_db()
        self.assertEqual(show.status, Show.STATUS_CONFIRMADO)
        self.assertEqual(show.show_time, datetime.time(22, 0))
        notifs = Notification.objects.filter(related_show_id=show.id)
        # 2 destinatários (produtor + integrante), evento SHOW_CONFIRMED
        self.assertEqual(notifs.count(), 2)
        self.assertEqual(set(notifs.values_list('event_type', flat=True)), {'SHOW_CONFIRMED'})

        # 3. Alteração posterior de horário com o show já CONFIRMADO -> gera SHOW_START_TIME_CHANGED
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(edit_url, {
                'name': proposal.name,
                'date': proposal.date.strftime('%Y-%m-%d'),
                'time': '23:15',
                'phase': 'FECHADO'
            })
        show.refresh_from_db()
        self.assertEqual(show.show_time, datetime.time(23, 15))
        new_notifs = Notification.objects.filter(related_show_id=show.id, event_type='SHOW_START_TIME_CHANGED')
        self.assertEqual(new_notifs.count(), 2)
