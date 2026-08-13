"""
Testes dos Serviços da Room List — Fase 2.1 (Com Errata Gate 1D)

Organização:
  - TestValidations: Gate A — exceções, validate_band_access, validate_room_capacity_for_type (parametrizado)
  - TestPendingIssues: Gate A — get_pending_issues, PendingIssuesReport
  - TestCreateRoomList: Gate B — create_room_list, sync_room_list_participants_from_show, rollbacks
  - TestRoomListLifecycle: Gate C — update, publish, reopen, archive, mark_sent, delete
  - TestRoomCommands: Gate D — create_room, update_room, delete_room
  - TestParticipantCommands: Gate E — assign, unassign
  - TestApplyTemplate: Gate F — apply_template_to_room_list
  - TestVisibilityQueries: Gate G — get_room_list_for_band, get_visible_room_list_for_user
"""

import datetime
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    Band,
    Integrante,
    LodgingTemplate,
    Room,
    RoomList,
    RoomListParticipant,
    Show,
    ShowParticipant,
    TemplateParticipant,
    TemplateRoom,
    User,
)
from core.services.room_list_services import (
    ActiveRoomListExistsError,
    BandAccessDeniedError,
    DuplicateRoomNumberError,
    PendingIssuesReport,
    PublicationBlockedError,
    RoomCapacityTypeMismatchError,
    RoomListArchivedError,
    RoomListNotFoundError,
    RoomListPublishedError,
    RoomListServiceError,
    RoomOverCapacityError,
    apply_template_to_room_list,
    archive_room_list,
    create_or_replace_lodging_template,
    delete_lodging_template,
    assign_participant_to_room,
    create_room,
    create_room_list,
    delete_room,
    delete_room_list,
    get_pending_issues,
    get_room_list_for_band,
    get_visible_room_list_for_user,
    mark_room_list_as_sent,
    publish_room_list,
    reopen_room_list,
    sync_room_list_participants_from_show,
    unassign_participant,
    update_room,
    update_room_list,
    validate_band_access,
    validate_room_capacity_for_type,
)


class RoomListServiceTestBase(TestCase):
    """Base com setUp compartilhado para todos os testes de serviço."""

    def setUp(self):
        self.band = Band.objects.create(name="Banda Teste", slug="banda-teste")
        self.band2 = Band.objects.create(name="Banda 2", slug="banda-2")

        self.user = User.objects.create_user(
            username="produtor", password="test123",
            role="PRODUTOR", band=self.band,
        )
        self.user_integrante = User.objects.create_user(
            username="integrante_user", password="test123",
            role="INTEGRANTE", band=self.band,
        )
        self.user_band2 = User.objects.create_user(
            username="produtor_b2", password="test123",
            role="PRODUTOR", band=self.band2,
        )

        self.show = Show.objects.create(
            band=self.band, title="Show Teste", date=datetime.date(2026, 12, 1),
        )
        self.show_band2 = Show.objects.create(
            band=self.band2, title="Show B2",
        )

        self.integrante1 = Integrante.objects.create(
            band=self.band, name="Int 1", role="Vocal",
            category="MUSICO", cpf="111.111.111-11", order=1,
        )
        self.integrante2 = Integrante.objects.create(
            band=self.band, name="Int 2", role="Guitarra",
            category="MUSICO", cpf="222.222.222-22", order=2,
        )
        self.integrante_inactive = Integrante.objects.create(
            band=self.band, name="Int Inativo", role="Baixo",
            category="MUSICO", order=3, is_active=False,
        )
        self.integrante_b2 = Integrante.objects.create(
            band=self.band2, name="Int B2", role="Vocal",
            category="MUSICO", order=1,
        )

        self.sp1 = ShowParticipant.objects.create(
            show=self.show, integrante=self.integrante1, order=1,
        )
        self.sp2 = ShowParticipant.objects.create(
            show=self.show, integrante=self.integrante2, order=2,
        )
        self.sp_inactive = ShowParticipant.objects.create(
            show=self.show, integrante=self.integrante_inactive, order=3,
        )

    def _create_rl(self, **overrides):
        """Helper para criar Room List de teste rapidamente."""
        defaults = dict(
            show_id=self.show.pk, band_id=self.band.pk, user=self.user,
            hotel_name="Hotel Teste", city="São Paulo",
        )
        defaults.update(overrides)
        return create_room_list(**defaults)

    def _create_rl_with_room(self, room_type='DUPLO', capacity=2, name="Quarto 101"):
        """Helper que cria RL + 1 quarto."""
        rl = self._create_rl()
        room = create_room(
            room_list_id=rl.pk, room_type=room_type,
            capacity=capacity, number_or_name=name, user=self.user,
        )
        return rl, room


# ============================================================
# Gate A — Validações e exceções
# ============================================================

class TestValidations(RoomListServiceTestBase):
    """Testes de validate_band_access e validate_room_capacity_for_type."""

    def test_validate_band_access_valid(self):
        """Produtor da banda correta passa sem exceção."""
        validate_band_access(self.user, self.band)

    def test_validate_band_access_wrong_band(self):
        """Produtor de outra banda é rejeitado."""
        with self.assertRaises(BandAccessDeniedError):
            validate_band_access(self.user, self.band2)

    def test_validate_band_access_non_produtor(self):
        """Integrante não pode executar operações de produtor."""
        with self.assertRaises(BandAccessDeniedError):
            validate_band_access(self.user_integrante, self.band)

    def test_validate_band_access_superuser_non_produtor(self):
        """Superusuário que não é produtor passa (is_produtor = True internamente)."""
        self.user.is_superuser = True
        self.user.role = "INTEGRANTE"
        self.user.save()
        # Não deve lançar exceção
        validate_band_access(self.user, self.band)

    def test_validate_band_access_inactive_user(self):
        """Usuário inativo é rejeitado."""
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(BandAccessDeniedError):
            validate_band_access(self.user, self.band)

    def test_validate_room_capacity_parametrized(self):
        """Teste parametrizado para capacidades inferiores, exatas e superiores (Gate 1D)."""
        valid_cases = [
            ('INDIVIDUAL', 1),
            ('CASAL', 2),
            ('DUPLO', 2),
            ('TRIPLO', 3),
            ('QUADRUPLO', 4),
            ('PERSONALIZADO', 1),
            ('PERSONALIZADO', 5),
            ('PERSONALIZADO', 10),
        ]
        for rtype, cap in valid_cases:
            with self.subTest(rtype=rtype, cap=cap, expected="valid"):
                validate_room_capacity_for_type(rtype, cap)

        invalid_cases = [
            ('INDIVIDUAL', 0),
            ('INDIVIDUAL', 2),  # superior
            ('CASAL', 1),       # inferior
            ('CASAL', 3),       # superior
            ('DUPLO', 1),       # inferior
            ('DUPLO', 3),       # superior
            ('TRIPLO', 2),      # inferior
            ('TRIPLO', 4),      # superior
            ('QUADRUPLO', 3),   # inferior
            ('QUADRUPLO', 5),   # superior
            ('PERSONALIZADO', 0),
            ('PERSONALIZADO', -1),
            ('PERSONALIZADO', 1.5),
            ('PERSONALIZADO', True),
            ('PERSONALIZADO', "3"),
            ('PERSONALIZADO', None),
        ]
        for rtype, cap in invalid_cases:
            with self.subTest(rtype=rtype, cap=cap, expected="invalid"):
                with self.assertRaises(RoomCapacityTypeMismatchError):
                    validate_room_capacity_for_type(rtype, cap)

    def test_validate_room_capacity_unknown_type(self):
        """Teste para tipo de quarto desconhecido (rejeitado)."""
        with self.assertRaises(RoomCapacityTypeMismatchError):
            validate_room_capacity_for_type('DESCONHECIDO', 1)

    def test_validate_room_list_for_publication_wrapper(self):
        """validate_room_list_for_publication deve ser um wrapper público para get_pending_issues."""
        from core.services.room_list_services import validate_room_list_for_publication
        rl = self._create_rl()
        issues = validate_room_list_for_publication(rl)
        self.assertIsInstance(issues, PendingIssuesReport)


# ============================================================
# Gate A — Pendências
# ============================================================

class TestPendingIssues(RoomListServiceTestBase):
    """Testes de get_pending_issues e PendingIssuesReport."""

    def test_publication_clean(self):
        """Room List sem pendências retorna relatório limpo."""
        rl = self._create_rl()
        room = create_room(rl.pk, 'PERSONALIZADO', 5, "Suite", self.user)
        for p in rl.participants.all():
            assign_participant_to_room(p.pk, room.pk, self.user)
        rl.refresh_from_db()
        report = get_pending_issues(rl)
        self.assertFalse(report.has_blocking)

    def test_publication_blocked_participant_without_room(self):
        """Participante sem quarto com needs_lodging=True é bloqueante."""
        rl = self._create_rl()
        report = get_pending_issues(rl)
        self.assertTrue(report.has_blocking)
        categories = [i.category for i in report.blocking_issues]
        self.assertIn('no_room', categories)

    def test_publication_blocked_over_capacity(self):
        """Quarto acima da capacidade é bloqueante."""
        rl = self._create_rl()
        room = create_room(rl.pk, 'PERSONALIZADO', 1, "Suite 1", self.user)
        p1 = rl.participants.first()
        assign_participant_to_room(p1.pk, room.pk, self.user)
        p2 = rl.participants.exclude(pk=p1.pk).first()
        RoomListParticipant.objects.filter(pk=p2.pk).update(room=room)
        rl.refresh_from_db()
        report = get_pending_issues(rl)
        categories = [i.category for i in report.blocking_issues]
        self.assertIn('over_capacity', categories)

    def test_publication_blocked_capacity_type_mismatch(self):
        """Quarto com capacidade incompatível com tipo é bloqueante."""
        rl = self._create_rl()
        room = create_room(rl.pk, 'INDIVIDUAL', 1, "Q1", self.user)
        Room.objects.filter(pk=room.pk).update(capacity=3)
        rl.refresh_from_db()
        report = get_pending_issues(rl)
        categories = [i.category for i in report.blocking_issues]
        self.assertIn('capacity_type_mismatch', categories)

    def test_publication_blocked_duplicate_room_number(self):
        """Número de quarto duplicado na mesma Room List gera pendência bloqueante defensiva."""
        from unittest.mock import MagicMock
        mock_rl = MagicMock()
        mock_rl.id = 1
        mock_qs = MagicMock()
        mock_qs.select_related.return_value = []
        mock_rl.participants.filter.return_value = mock_qs

        r1 = MagicMock(pk=101, room_list_id=1, number_or_name="Q101", type="DUPLO", capacity=2)
        r2 = MagicMock(pk=102, room_list_id=1, number_or_name="Q101", type="DUPLO", capacity=2)
        r1.participants.count.return_value = 0
        r2.participants.count.return_value = 0
        mock_rl.rooms.all.return_value = [r1, r2]

        report = get_pending_issues(mock_rl)
        categories = [i.category for i in report.blocking_issues]
        self.assertIn('duplicate_room_number', categories)

    def test_publication_blocked_invalid_capacity(self):
        """Quarto PERSONALIZADO com capacidade <= 0 ou tipo desconhecido gera pendência bloqueante."""
        from unittest.mock import MagicMock
        mock_rl = MagicMock()
        mock_rl.id = 1
        mock_qs = MagicMock()
        mock_qs.select_related.return_value = []
        mock_rl.participants.filter.return_value = mock_qs

        r1 = MagicMock(pk=101, room_list_id=1, number_or_name="Q1", type="PERSONALIZADO", capacity=0)
        r2 = MagicMock(pk=102, room_list_id=1, number_or_name="Q2", type="DESCONHECIDO", capacity=2)
        r1.participants.count.return_value = 0
        r2.participants.count.return_value = 0
        mock_rl.rooms.all.return_value = [r1, r2]

        report = get_pending_issues(mock_rl)
        categories = [i.category for i in report.blocking_issues]
        self.assertIn('invalid_capacity', categories)
        self.assertIn('unknown_room_type', categories)

    def test_publication_blocked_room_wrong_list(self):
        """Participante alocado em quarto de outra Room List gera pendência bloqueante defensiva."""
        from unittest.mock import MagicMock
        mock_rl = MagicMock()
        mock_rl.id = 1
        mock_rl.rooms.all.return_value = []

        mock_qs = MagicMock()
        mock_p = MagicMock(pk=1)
        mock_p.snapshot_name = "P1"
        mock_p.room = MagicMock(room_list_id=999) # Outra Room List
        mock_qs.select_related.return_value = [mock_p]
        mock_rl.participants.filter.return_value = mock_qs

        report = get_pending_issues(mock_rl)
        categories = [i.category for i in report.blocking_issues]
        self.assertIn('room_wrong_list', categories)

    def test_publication_warning_inactive(self):
        """Integrante inativo gera warning, não bloqueio."""
        rl = self._create_rl()
        report = get_pending_issues(rl)
        warning_cats = [i.category for i in report.warning_issues]
        self.assertIn('inactive_integrante', warning_cats)

    def test_publication_warning_removed(self):
        """Integrante removido gera warning."""
        rl = self._create_rl()
        self.integrante1.delete()
        rl.refresh_from_db()
        report = get_pending_issues(rl)
        warning_cats = [i.category for i in report.warning_issues]
        self.assertIn('removed_integrante', warning_cats)

    def test_pending_issues_report_properties(self):
        """PendingIssuesReport separa blocking e warning corretamente."""
        from core.services.room_list_services import PendingIssue
        report = PendingIssuesReport(issues=[
            PendingIssue('no_room', 'blocking', 'desc', 1, 'RoomListParticipant'),
            PendingIssue('inactive_integrante', 'warning', 'desc', 2, 'RoomListParticipant'),
        ])
        self.assertTrue(report.has_blocking)
        self.assertEqual(len(report.blocking_issues), 1)
        self.assertEqual(len(report.warning_issues), 1)


# ============================================================
# Gate B — Criação e sincronização
# ============================================================

class TestCreateRoomList(RoomListServiceTestBase):
    """Testes de create_room_list e sync_room_list_participants_from_show."""

    def test_create_success(self):
        """Criação bem-sucedida com dados válidos."""
        rl = self._create_rl()
        self.assertEqual(rl.hotel_name, "Hotel Teste")
        self.assertEqual(rl.show, self.show)
        self.assertEqual(rl.band, self.band)
        self.assertEqual(rl.status, RoomList.StatusChoices.RASCUNHO)
        self.assertEqual(rl.content_revision, 1)

    def test_create_populates_participants(self):
        """Participantes são populados a partir da escala do show."""
        rl = self._create_rl()
        participants = rl.participants.all()
        self.assertEqual(participants.count(), 3)
        names = set(p.snapshot_name for p in participants)
        self.assertEqual(names, {"Int 1", "Int 2", "Int Inativo"})

    def test_create_duplicate_active_raises(self):
        """Segunda Room List ativa para o mesmo show é rejeitada."""
        self._create_rl()
        with self.assertRaises(ActiveRoomListExistsError):
            self._create_rl()

    def test_create_room_list_invalid_participant_rolls_back(self):
        """Se algum participante for inválido na criação, a transação sofre rollback integral."""
        # Integrante com nome em branco para falhar no full_clean() do participante snapshot_name
        invalid_int = Integrante.objects.create(
            band=self.band, name="", role="X", category="MUSICO", order=99
        )
        ShowParticipant.objects.create(show=self.show, integrante=invalid_int, order=99)
        with self.assertRaises(ValidationError):
            self._create_rl()
        self.assertFalse(RoomList.objects.filter(show=self.show).exists())

    def test_sync_adds_new_participants(self):
        """Sincronização adiciona novos integrantes da escala."""
        rl = self._create_rl()
        initial_count = rl.participants.count()

        new_integrante = Integrante.objects.create(
            band=self.band, name="Novo Int", role="Tecladista",
            category="MUSICO", order=4,
        )
        ShowParticipant.objects.create(
            show=self.show, integrante=new_integrante, order=4,
        )

        rl, added = sync_room_list_participants_from_show(rl.pk, self.user)
        self.assertEqual(added, 1)
        self.assertEqual(rl.participants.count(), initial_count + 1)

    def test_sync_failure_rolls_back_all(self):
        """Falha de validação no sync provoca rollback integral dos novos participantes."""
        rl = self._create_rl()
        initial_count = rl.participants.count()

        invalid_int = Integrante.objects.create(
            band=self.band, name="", role="X", category="MUSICO", order=99
        )
        ShowParticipant.objects.create(show=self.show, integrante=invalid_int, order=99)

        with self.assertRaises(ValidationError):
            sync_room_list_participants_from_show(rl.pk, self.user)

        rl.refresh_from_db()
        self.assertEqual(rl.participants.count(), initial_count)

    def test_sync_reject_different_bands(self):
        """Sync rejeita Show/RoomList com bandas diferentes sem alteração parcial."""
        rl = self._create_rl()
        initial_count = rl.participants.count()
        rev_before = rl.content_revision
        
        # Mudar a banda do show para causar inconsistência
        self.show.band = self.band2
        self.show.save()
        
        with self.assertRaisesRegex(
            RoomListServiceError,
            "Vínculo entre Show e Room List inconsistente",
        ):
            sync_room_list_participants_from_show(rl.pk, self.user_band2)
            
        rl.refresh_from_db()
        self.assertEqual(rl.participants.count(), initial_count)
        self.assertEqual(rl.content_revision, rev_before)


# ============================================================
# Gate C — Ciclo de vida
# ============================================================

class TestRoomListLifecycle(RoomListServiceTestBase):
    """Testes de update, publish, reopen, archive, mark_sent, delete."""

    def test_update_success(self):
        """Atualização bem-sucedida de dados do hotel."""
        rl = self._create_rl()
        rl = update_room_list(rl.pk, self.user, hotel_name="Hotel B", city="RJ")
        self.assertEqual(rl.hotel_name, "Hotel B")
        self.assertEqual(rl.city, "RJ")

    def test_update_increments_revision(self):
        """Atualização incrementa content_revision somente se houver mudança real."""
        rl = self._create_rl()
        rev = rl.content_revision
        rl = update_room_list(rl.pk, self.user, hotel_name="H2")
        self.assertEqual(rl.content_revision, rev + 1)

    def test_update_room_list_invalid_rolls_back_without_revision(self):
        """Update inválido que falha no full_clean() não incrementa revision nem altera banco."""
        rl = self._create_rl()
        rev_before = rl.content_revision
        with self.assertRaises(ValidationError):
            update_room_list(rl.pk, self.user, hotel_name="")  # hotel_name em branco invalida
        rl.refresh_from_db()
        self.assertEqual(rl.content_revision, rev_before)

    def test_publish_success(self):
        """Publicação bem-sucedida de Room List sem pendências."""
        rl = self._create_rl()
        room = create_room(rl.pk, 'PERSONALIZADO', 10, "Suite", self.user)
        for p in rl.participants.all():
            assign_participant_to_room(p.pk, room.pk, self.user)
        rl = publish_room_list(rl.pk, self.user)
        self.assertEqual(rl.status, RoomList.StatusChoices.PUBLICADA)
        self.assertIsNotNone(rl.published_at)

    def test_reopen_no_revision_increment(self):
        """Reabertura de status não incrementa content_revision."""
        rl = self._create_rl()
        room = create_room(rl.pk, 'PERSONALIZADO', 10, "S", self.user)
        for p in rl.participants.all():
            assign_participant_to_room(p.pk, room.pk, self.user)
        publish_room_list(rl.pk, self.user)
        rev = RoomList.objects.get(pk=rl.pk).content_revision
        rl = reopen_room_list(rl.pk, self.user)
        self.assertEqual(rl.status, RoomList.StatusChoices.RASCUNHO)
        self.assertEqual(rl.content_revision, rev)

    def test_update_room_list_noop(self):
        """Atualização sem mudanças (no-op) não altera updated_at nem content_revision."""
        rl = self._create_rl()
        old_rev = rl.content_revision
        old_updated = rl.updated_at
        
        # update com os mesmos dados
        rl_updated = update_room_list(rl.pk, self.user, hotel_name="Hotel Teste")
        self.assertEqual(rl_updated.content_revision, old_rev)
        self.assertEqual(rl_updated.updated_at, old_updated)

    def test_archive_room_list_transitions(self):
        """archive_room_list transita corretamente e não altera revision."""
        # RASCUNHO -> ARQUIVADA
        rl1 = self._create_rl()
        old_rev1 = rl1.content_revision
        rl_archived1 = archive_room_list(rl1.pk, self.user)
        self.assertEqual(rl_archived1.status, RoomList.StatusChoices.ARQUIVADA)
        self.assertEqual(rl_archived1.content_revision, old_rev1)
        
        # PUBLICADA -> ARQUIVADA
        rl2 = self._create_rl()
        room = create_room(rl2.pk, 'PERSONALIZADO', 10, "Suite", self.user)
        for p in rl2.participants.all():
            assign_participant_to_room(p.pk, room.pk, self.user)
        rl2 = publish_room_list(rl2.pk, self.user)
        old_rev2 = rl2.content_revision
        rl_archived2 = archive_room_list(rl2.pk, self.user)
        self.assertEqual(rl_archived2.status, RoomList.StatusChoices.ARQUIVADA)
        self.assertEqual(rl_archived2.content_revision, old_rev2)
        
        # ARQUIVADA -> ARQUIVADA
        with self.assertRaises(RoomListArchivedError):
            archive_room_list(rl2.pk, self.user)
        rl2.refresh_from_db()
        self.assertEqual(rl2.content_revision, old_rev2)

    def test_mark_room_list_as_sent(self):
        """mark_room_list_as_sent salva last_sent_revision sem alterar content_revision."""
        rl = self._create_rl()
        room = create_room(rl.pk, 'PERSONALIZADO', 10, "Suite", self.user)
        for p in rl.participants.all():
            assign_participant_to_room(p.pk, room.pk, self.user)
        rl = publish_room_list(rl.pk, self.user)
        
        old_rev = rl.content_revision
        rl_sent = mark_room_list_as_sent(rl.pk, self.user)
        self.assertEqual(rl_sent.last_sent_revision, old_rev)
        self.assertEqual(rl_sent.content_revision, old_rev)

    def test_delete_room_list_allowed_in_draft(self):
        """delete_room_list é permitido apenas em RASCUNHO, completado com subTest."""
        rl_draft = self._create_rl()
        delete_room_list(rl_draft.pk, self.user)
        self.assertFalse(RoomList.objects.filter(pk=rl_draft.pk).exists())
        
        rl_published = self._create_rl()
        room = create_room(rl_published.pk, 'PERSONALIZADO', 10, "Suite", self.user)
        for p in rl_published.participants.all():
            assign_participant_to_room(p.pk, room.pk, self.user)
        publish_room_list(rl_published.pk, self.user)
        
        rl_archived = self._create_rl(show_id=self.show_band2.pk, band_id=self.band2.pk, user=self.user_band2)
        archive_room_list(rl_archived.pk, self.user_band2)
        
        invalid_statuses = [
            (rl_published, RoomList.StatusChoices.PUBLICADA, self.user),
            (rl_archived, RoomList.StatusChoices.ARQUIVADA, self.user_band2),
        ]
        
        for rl_invalid, status, run_user in invalid_statuses:
            with self.subTest(status=status):
                with self.assertRaises(RoomListServiceError):
                    delete_room_list(rl_invalid.pk, run_user)

    def test_publish_no_increment_and_needs_resend(self):
        """Publicar não incrementa revisão, e last_sent_revision < content_revision sinaliza reenvio."""
        rl = self._create_rl()
        room = create_room(rl.pk, 'PERSONALIZADO', 10, "Suite", self.user)
        for p in rl.participants.all():
            assign_participant_to_room(p.pk, room.pk, self.user)
        
        rl.refresh_from_db()
        old_rev = rl.content_revision
        rl = publish_room_list(rl.pk, self.user)
        self.assertEqual(rl.content_revision, old_rev)
        
        mark_room_list_as_sent(rl.pk, self.user)
        rl = reopen_room_list(rl.pk, self.user)
        rl = update_room_list(rl.pk, self.user, hotel_name="Novo Hotel") # incrementa rev
        
        self.assertTrue(rl.needs_resend)


# ============================================================
# Gate D — Quartos
# ============================================================

class TestRoomCommands(RoomListServiceTestBase):
    """Testes de create_room, update_room, delete_room."""

    def test_create_room_success(self):
        """Criação de quarto com dados válidos."""
        rl = self._create_rl()
        room = create_room(rl.pk, 'DUPLO', 2, "Quarto 101", self.user)
        self.assertEqual(room.room_list_id, rl.pk)
        self.assertEqual(room.capacity, 2)
        self.assertEqual(room.type, 'DUPLO')

    def test_create_room_invalid_rolls_back_without_revision(self):
        """Criação de quarto inválido sofre rollback sem alterar revision."""
        rl = self._create_rl()
        rev_before = rl.content_revision
        with self.assertRaises(ValidationError):
            create_room(rl.pk, 'DUPLO', 2, "   ", self.user)  # nome em branco falha no full_clean
        rl.refresh_from_db()
        self.assertEqual(rl.content_revision, rev_before)
        self.assertEqual(rl.rooms.count(), 0)

    def test_update_room_no_change_no_revision(self):
        """Atualização idempotente com mesmos valores não incrementa content_revision e não altera updated_at."""
        rl, room = self._create_rl_with_room(room_type='DUPLO', capacity=2, name="Q101")
        rev_before = RoomList.objects.get(pk=rl.pk).content_revision
        updated_before = room.updated_at
        room = update_room(room.pk, rl.pk, self.user, number_or_name="Q101", capacity=2)
        room.refresh_from_db()
        self.assertEqual(room.updated_at, updated_before)
        rl.refresh_from_db()
        self.assertEqual(rl.content_revision, rev_before)

    def test_delete_room_success(self):
        """Exclusão de quarto bem-sucedida."""
        rl, room = self._create_rl_with_room()
        room_id = room.pk
        delete_room(room_id, rl.pk, self.user)
        self.assertFalse(Room.objects.filter(pk=room_id).exists())

    def test_create_room_unknown_integrity_error(self):
        """IntegrityError desconhecido em create_room é relançado sem tradução."""
        from django.db import IntegrityError
        from unittest.mock import patch
        rl = self._create_rl()
        with patch('core.models.Room.save', side_effect=IntegrityError("DB Error")):
            with self.assertRaises(IntegrityError):
                create_room(rl.pk, 'DUPLO', 2, "Q1", self.user)


# ============================================================
# Gate E — Participantes
# ============================================================

class TestParticipantCommands(RoomListServiceTestBase):
    """Testes de assign_participant_to_room e unassign_participant."""

    def test_assign_success(self):
        """Alocação de participante em quarto com vaga."""
        rl, room = self._create_rl_with_room()
        p1 = rl.participants.get(original_integrante=self.integrante1)
        p1 = assign_participant_to_room(p1.pk, room.pk, self.user)
        self.assertEqual(p1.room_id, room.pk)

    def test_assign_rejected_no_state_or_revision_change(self):
        """Alocação rejeitada (ex: quarto cheio) não altera estado nem revision."""
        rl = self._create_rl()
        room = create_room(rl.pk, 'INDIVIDUAL', 1, "Q1", self.user)
        p1 = rl.participants.get(original_integrante=self.integrante1)
        p2 = rl.participants.get(original_integrante=self.integrante2)
        assign_participant_to_room(p1.pk, room.pk, self.user)

        rev_before = RoomList.objects.get(pk=rl.pk).content_revision
        with self.assertRaises(RoomOverCapacityError):
            assign_participant_to_room(p2.pk, room.pk, self.user)

        rl.refresh_from_db()
        p2.refresh_from_db()
        self.assertIsNone(p2.room)
        self.assertEqual(rl.content_revision, rev_before)

    def test_assign_rejected_obsolete_state(self):
        """assign_participant_to_room rejeita alocação se o estado in-memory divergir."""
        rl, room = self._create_rl_with_room()
        p1 = rl.participants.get(original_integrante=self.integrante1)
        
        from unittest.mock import patch
        # Interceptamos apenas o rlp_fresh para retornar um room_id diferente do lock inicial
        with patch('core.services.room_list_services.RoomListParticipant.objects.get') as mock_get:
            mock_fresh = p1
            mock_fresh.room_id = 999 
            mock_get.return_value = mock_fresh
            with self.assertRaises(RoomListServiceError):
                assign_participant_to_room(p1.pk, room.pk, self.user)

    def test_assign_reject_source_room_different_list(self):
        """assign rejeita se o quarto de origem pertencer a outra Room List."""
        rl1, room1 = self._create_rl_with_room(name="R1")
        rl2 = self._create_rl(show_id=self.show_band2.pk, band_id=self.band2.pk, user=self.user_band2, hotel_name="Outro")
        room2 = create_room(rl2.pk, 'DUPLO', 2, "R2", self.user_band2)
        
        p1 = rl1.participants.get(original_integrante=self.integrante1)
        p1 = assign_participant_to_room(p1.pk, room1.pk, self.user)
        
        rl1.refresh_from_db()
        rev_before = rl1.content_revision
        
        # Simula estado in-memory indicando quarto de outra lista
        from unittest.mock import patch
        with patch('core.services.room_list_services.RoomListParticipant.objects.get') as mock_get:
            mock_fresh = p1
            mock_fresh.room_id = room2.pk
            mock_get.return_value = mock_fresh
            with self.assertRaises(RoomListServiceError):
                assign_participant_to_room(p1.pk, room1.pk, self.user)
                
        rl1.refresh_from_db()
        self.assertEqual(rl1.content_revision, rev_before)

    def test_unassign_success_and_idempotent(self):
        """unassign_participant limpa o quarto e é idempotente se repetido."""
        rl, room = self._create_rl_with_room()
        p1 = rl.participants.get(original_integrante=self.integrante1)
        p1 = assign_participant_to_room(p1.pk, room.pk, self.user)
        
        p1 = unassign_participant(p1.pk, self.user)
        self.assertIsNone(p1.room)
        rev = RoomList.objects.get(pk=rl.pk).content_revision
        
        p1_again = unassign_participant(p1.pk, self.user)
        self.assertIsNone(p1_again.room)
        self.assertEqual(RoomList.objects.get(pk=rl.pk).content_revision, rev)


# ============================================================
# Gate F — Template
# ============================================================

class TestApplyTemplate(RoomListServiceTestBase):
    """Testes de apply_template_to_room_list."""

    def setUp(self):
        super().setUp()
        self.template = LodgingTemplate.objects.create(band=self.band)
        self.t_room1 = TemplateRoom.objects.create(
            template=self.template, type='DUPLO', capacity=2, order=1,
        )
        self.t_room2 = TemplateRoom.objects.create(
            template=self.template, type='INDIVIDUAL', capacity=1, order=2,
        )

    def test_apply_template_success(self):
        """Aplicação do template cria quartos e aloca participantes."""
        rl = self._create_rl()
        rl = apply_template_to_room_list(rl.pk, self.user)
        self.assertEqual(rl.rooms.count(), 2)

    def test_apply_template_invalid_capacity_rolls_back(self):
        """Template com capacidade incompatível causa rollback integral sem persistência parcial."""
        # Adicionar quarto com capacidade inválida para o tipo no template
        TemplateRoom.objects.create(
            template=self.template, type='INDIVIDUAL', capacity=3, order=3,
        )
        rl = self._create_rl()
        with self.assertRaises(RoomCapacityTypeMismatchError):
            apply_template_to_room_list(rl.pk, self.user)

        rl.refresh_from_db()
        self.assertEqual(rl.rooms.count(), 0)
        self.assertEqual(rl.participants.filter(room__isnull=False).count(), 0)

    def test_apply_template_allocates_scaled_ignores_off_scale(self):
        """Aloca participantes escalados e ignora os não escalados no template."""
        TemplateParticipant.objects.create(template=self.template, room=self.t_room1, original_integrante=self.integrante1)
        TemplateParticipant.objects.create(template=self.template, room=self.t_room1, original_integrante=self.integrante_b2)
        
        rl = self._create_rl()
        rl = apply_template_to_room_list(rl.pk, self.user)
        
        p1 = rl.participants.get(original_integrante=self.integrante1)
        self.assertIsNotNone(p1.room)
        self.assertFalse(rl.participants.filter(original_integrante=self.integrante_b2).exists())

    def test_apply_template_allocating_over_capacity(self):
        """Template tentando alocar 3 participantes em quarto DUPLO gera erro sem alterar revision."""
        TemplateParticipant.objects.create(template=self.template, room=self.t_room1, original_integrante=self.integrante1)
        TemplateParticipant.objects.create(template=self.template, room=self.t_room1, original_integrante=self.integrante2)
        TemplateParticipant.objects.create(template=self.template, room=self.t_room1, original_integrante=self.integrante_inactive)
        
        rl = self._create_rl()
        rev_before = rl.content_revision
        
        with self.assertRaises(RoomOverCapacityError):
            apply_template_to_room_list(rl.pk, self.user)
            
        rl.refresh_from_db()
        self.assertEqual(rl.rooms.count(), 0)
        self.assertEqual(rl.participants.filter(room__isnull=False).count(), 0)
        self.assertEqual(rl.content_revision, rev_before)

    def test_apply_template_full_clean_failure(self):
        """Falha no full_clean de um participante do template impede bulk_create e não altera revision."""
        TemplateParticipant.objects.create(template=self.template, room=self.t_room1, original_integrante=self.integrante1)
        
        rl = self._create_rl()
        rev_before = rl.content_revision
        
        p1 = rl.participants.get(original_integrante=self.integrante1)
        p1.snapshot_name = ""
        p1.save(update_fields=['snapshot_name'])

        from unittest.mock import patch
        with patch('core.services.room_list_services.Room.objects.bulk_create') as mock_bulk:
            with self.assertRaises(ValidationError):
                apply_template_to_room_list(rl.pk, self.user)
            mock_bulk.assert_not_called()
            
        rl.refresh_from_db()
        self.assertEqual(rl.rooms.count(), 0)
        self.assertEqual(rl.participants.filter(room__isnull=False).count(), 0)
        self.assertEqual(rl.content_revision, rev_before)


# ============================================================
# Gate G — Consultas e visibilidade
# ============================================================

class TestVisibilityQueries(RoomListServiceTestBase):
    """Testes de get_room_list_for_band e get_visible_room_list_for_user."""

    def test_get_room_list_valid(self):
        """Obter Room List da banda correta."""
        rl = self._create_rl()
        result = get_room_list_for_band(rl.pk, self.band)
        self.assertEqual(result.pk, rl.pk)

    def test_visible_produtor_sees_draft(self):
        """Produtor vê Room List em rascunho."""
        rl = self._create_rl()
        result = get_visible_room_list_for_user(rl.pk, self.user)
        self.assertEqual(result.pk, rl.pk)



import datetime
import unittest
import threading
import concurrent.futures
from django.db import connection, OperationalError, close_old_connections
from django.test import TransactionTestCase

class RoomListServicesPostgreSQLConcurrencyTests(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if connection.vendor != "postgresql":
            return

    def setUp(self):
        if connection.vendor != "postgresql":
            self.skipTest("Testes de concorrência requerem PostgreSQL")
            
        from core.models import Band, Show, Integrante, User, ShowParticipant
        self.band = Band.objects.create(name="Banda Conc", slug="banda-conc")
        self.user = User.objects.create_user(username="produtor_conc", email="c@c.com", role="PRODUTOR", band=self.band)
        self.show = Show.objects.create(band=self.band, title="Show Conc", date=datetime.date(2026, 12, 1))
        
        self.int1 = Integrante.objects.create(band=self.band, name="Int1", role="Role", category="MUSICO", order=1)
        self.int2 = Integrante.objects.create(band=self.band, name="Int2", role="Role", category="MUSICO", order=2)
        
        self.sp1 = ShowParticipant.objects.create(show=self.show, integrante=self.int1, order=1)
        self.sp2 = ShowParticipant.objects.create(show=self.show, integrante=self.int2, order=2)

    def tearDown(self):
        pass

    def execute_concurrently(self, func1, func2):
        barrier = threading.Barrier(2)
        
        def worker(func):
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return func()
            finally:
                close_old_connections()
                
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        f1 = executor.submit(worker, func1)
        f2 = executor.submit(worker, func2)
        
        done, not_done = concurrent.futures.wait([f1, f2], timeout=15)
        
        if not_done:
            for f in not_done:
                f.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            self.fail("Timeout esperando os workers concluirem.")
            
        executor.shutdown(wait=True)
            
        try:
            res1 = f1.result(timeout=0)
        except Exception as e:
            res1 = e
            
        try:
            res2 = f2.result(timeout=0)
        except Exception as e:
            res2 = e
            
        return res1, res2

    def test_concurrent_create_room_list_same_show(self):
        from core.services.room_list_services import create_room_list, ActiveRoomListExistsError
        from core.models import User, RoomList
        
        user_id = self.user.pk
        show_id = self.show.pk
        band_id = self.band.pk
        
        def task1():
            user = User.objects.get(pk=user_id)
            res = create_room_list(show_id=show_id, band_id=band_id, user=user, hotel_name="H1", city="C1")
            return ("OK", res.pk)
            
        def task2():
            user = User.objects.get(pk=user_id)
            res = create_room_list(show_id=show_id, band_id=band_id, user=user, hotel_name="H2", city="C2")
            return ("OK", res.pk)
            
        r1, r2 = self.execute_concurrently(task1, task2)
        
        results = [r1, r2]
        successes = [r for r in results if isinstance(r, tuple) and r[0] == "OK"]
        errors = [r for r in results if isinstance(r, ActiveRoomListExistsError)]
        
        for r in results:
            if isinstance(r, Exception) and not isinstance(r, ActiveRoomListExistsError):
                self.fail(f"Erro inesperado: {r}")
                
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        
        self.assertEqual(RoomList.objects.filter(show_id=show_id).count(), 1)
        rl = RoomList.objects.get(show_id=show_id)
        self.assertEqual(rl.participants.count(), 2)

    def test_concurrent_assign_last_slot(self):
        from core.services.room_list_services import create_room_list, create_room, assign_participant_to_room, RoomOverCapacityError
        from core.models import User, RoomListParticipant, Room, RoomList
        
        rl = create_room_list(show_id=self.show.pk, band_id=self.band.pk, user=self.user, hotel_name="H", city="C")
        room = create_room(room_list_id=rl.pk, room_type='PERSONALIZADO', capacity=1, number_or_name="Q1", user=self.user)
        
        p1 = rl.participants.get(original_integrante=self.int1)
        p2 = rl.participants.get(original_integrante=self.int2)
        
        rl.refresh_from_db()
        initial_revision = rl.content_revision
        
        user_id = self.user.pk
        p1_id = p1.pk
        p2_id = p2.pk
        room_id = room.pk
        
        def task1():
            user = User.objects.get(pk=user_id)
            res = assign_participant_to_room(p1_id, room_id, user)
            return ("OK", res.pk)
            
        def task2():
            user = User.objects.get(pk=user_id)
            res = assign_participant_to_room(p2_id, room_id, user)
            return ("OK", res.pk)
            
        r1, r2 = self.execute_concurrently(task1, task2)
        
        results = [r1, r2]
        successes = [r for r in results if isinstance(r, tuple) and r[0] == "OK"]
        errors = [r for r in results if isinstance(r, RoomOverCapacityError)]
        
        for r in results:
            if isinstance(r, Exception) and not isinstance(r, RoomOverCapacityError):
                self.fail(f"Erro inesperado: {r}")
                
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        
        room.refresh_from_db()
        self.assertEqual(room.participants.count(), 1)
        
        p1.refresh_from_db()
        p2.refresh_from_db()
        
        winner = p1 if p1.room_id == room.pk else p2
        loser = p1 if p1.room_id is None else p2
        
        self.assertEqual(winner.room_id, room.pk)
        self.assertIsNone(loser.room_id)
        
        rl.refresh_from_db()
        self.assertEqual(rl.content_revision, initial_revision + 1)
        
    def test_concurrent_move_same_participant(self):
        from core.services.room_list_services import create_room_list, create_room, assign_participant_to_room
        from core.models import User, RoomListParticipant, RoomList
        
        rl = create_room_list(show_id=self.show.pk, band_id=self.band.pk, user=self.user, hotel_name="H", city="C")
        room_orig = create_room(room_list_id=rl.pk, room_type='PERSONALIZADO', capacity=10, number_or_name="Q0", user=self.user)
        room_dest1 = create_room(room_list_id=rl.pk, room_type='PERSONALIZADO', capacity=10, number_or_name="Q1", user=self.user)
        room_dest2 = create_room(room_list_id=rl.pk, room_type='PERSONALIZADO', capacity=10, number_or_name="Q2", user=self.user)
        
        p = rl.participants.get(original_integrante=self.int1)
        assign_participant_to_room(p.pk, room_orig.pk, self.user)
        
        rl.refresh_from_db()
        initial_revision = rl.content_revision
        
        user_id = self.user.pk
        p_id = p.pk
        dest1_id = room_dest1.pk
        dest2_id = room_dest2.pk
        
        lock = threading.Lock()
        order_log = []
        
        def task1():
            user = User.objects.get(pk=user_id)
            res = assign_participant_to_room(p_id, dest1_id, user)
            with lock:
                order_log.append(dest1_id)
            return ("OK", res.pk)
            
        def task2():
            user = User.objects.get(pk=user_id)
            res = assign_participant_to_room(p_id, dest2_id, user)
            with lock:
                order_log.append(dest2_id)
            return ("OK", res.pk)
            
        r1, r2 = self.execute_concurrently(task1, task2)
        
        results = [r1, r2]
        successes = [r for r in results if isinstance(r, tuple) and r[0] == "OK"]
        
        for r in results:
            if isinstance(r, Exception):
                self.fail(f"Erro inesperado: {r}")
                
        self.assertEqual(len(successes), 2)
        self.assertEqual(len(order_log), 2)
        
        p.refresh_from_db()
        self.assertEqual(p.room_id, order_log[-1])
        
        rl.refresh_from_db()
        self.assertEqual(rl.content_revision, initial_revision + 2)
        
    def test_concurrent_apply_template(self):
        from core.services.room_list_services import create_room_list, apply_template_to_room_list, RoomListServiceError
        from core.models import User, RoomList, LodgingTemplate, TemplateRoom, TemplateParticipant
        
        rl = create_room_list(show_id=self.show.pk, band_id=self.band.pk, user=self.user, hotel_name="H", city="C")
        
        template = LodgingTemplate.objects.create(band=self.band)
        t_room = TemplateRoom.objects.create(template=template, type='DUPLO', capacity=2, order=1)
        TemplateParticipant.objects.create(template=template, room=t_room, original_integrante=self.int1)
        
        rl.refresh_from_db()
        initial_revision = rl.content_revision
        
        user_id = self.user.pk
        rl_id = rl.pk
        
        def task1():
            user = User.objects.get(pk=user_id)
            res = apply_template_to_room_list(rl_id, user)
            return ("OK", res.pk)
            
        def task2():
            user = User.objects.get(pk=user_id)
            res = apply_template_to_room_list(rl_id, user)
            return ("OK", res.pk)
            
        r1, r2 = self.execute_concurrently(task1, task2)
        
        results = [r1, r2]
        successes = [r for r in results if isinstance(r, tuple) and r[0] == "OK"]
        errors = [r for r in results if isinstance(r, RoomListServiceError)]
        
        for r in results:
            if isinstance(r, Exception) and not isinstance(r, RoomListServiceError):
                self.fail(f"Erro inesperado: {r}")
                
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(errors), 1)
        
        rl.refresh_from_db()
        self.assertEqual(rl.rooms.count(), 1)
        room = rl.rooms.first()
        self.assertEqual(room.participants.count(), 1)
        self.assertEqual(rl.content_revision, initial_revision + 1)
        
    def test_concurrent_publish_and_edit(self):
        from core.services.room_list_services import create_room_list, create_room, assign_participant_to_room, publish_room_list, update_room, RoomListPublishedError
        from core.models import User, RoomList, Room
        
        rl = create_room_list(show_id=self.show.pk, band_id=self.band.pk, user=self.user, hotel_name="H", city="C")
        room = create_room(room_list_id=rl.pk, room_type='PERSONALIZADO', capacity=10, number_or_name="Original", user=self.user)
        
        for p in rl.participants.all():
            assign_participant_to_room(p.pk, room.pk, self.user)
            
        rl.refresh_from_db()
        initial_revision = rl.content_revision
        
        user_id = self.user.pk
        rl_id = rl.pk
        room_id = room.pk
        
        def task1():
            user = User.objects.get(pk=user_id)
            res = publish_room_list(rl_id, user)
            return ("OK_PUB", res.pk)
            
        def task2():
            user = User.objects.get(pk=user_id)
            res = update_room(room_id, rl_id, user, number_or_name="Editado", capacity=2)
            return ("OK_UPD", res.pk)
            
        r1, r2 = self.execute_concurrently(task1, task2)
        
        rl.refresh_from_db()
        room.refresh_from_db()
        
        if isinstance(r1, tuple) and r1[0] == "OK_PUB" and isinstance(r2, RoomListPublishedError):
            self.assertEqual(rl.status, RoomList.StatusChoices.PUBLICADA)
            self.assertEqual(room.number_or_name, "Original")
            self.assertEqual(rl.content_revision, initial_revision)
        elif isinstance(r2, tuple) and r2[0] == "OK_UPD" and isinstance(r1, tuple) and r1[0] == "OK_PUB":
            self.assertEqual(rl.status, RoomList.StatusChoices.PUBLICADA)
            self.assertEqual(room.number_or_name, "Editado")
            self.assertEqual(rl.content_revision, initial_revision + 1)
        else:
            self.fail(f"Resultados inesperados: {r1}, {r2}")
            
    def test_concurrent_reopen_and_archive(self):
        from core.services.room_list_services import create_room_list, create_room, assign_participant_to_room, publish_room_list, reopen_room_list, archive_room_list, RoomListServiceError
        from core.models import User, RoomList
        
        rl = create_room_list(show_id=self.show.pk, band_id=self.band.pk, user=self.user, hotel_name="H", city="C")
        room = create_room(room_list_id=rl.pk, room_type='PERSONALIZADO', capacity=10, number_or_name="Original", user=self.user)
        for p in rl.participants.all():
            assign_participant_to_room(p.pk, room.pk, self.user)
            
        publish_room_list(rl.pk, self.user)
        
        rl.refresh_from_db()
        initial_revision = rl.content_revision
        
        user_id = self.user.pk
        rl_id = rl.pk
        
        def task1():
            user = User.objects.get(pk=user_id)
            res = reopen_room_list(rl_id, user)
            return ("OK_REO", res.pk)
            
        def task2():
            user = User.objects.get(pk=user_id)
            res = archive_room_list(rl_id, user)
            return ("OK_ARC", res.pk)
            
        r1, r2 = self.execute_concurrently(task1, task2)
        
        rl.refresh_from_db()
        
        if isinstance(r1, Exception):
            self.assertIsInstance(r1, RoomListServiceError)
            self.assertTrue(isinstance(r2, tuple) and r2[0] == "OK_ARC")
        elif isinstance(r2, Exception):
            self.fail(f"Archive não deveria falhar se reopen for primeiro. Resultados: {r1}, {r2}")
        else:
            self.assertTrue(isinstance(r1, tuple) and r1[0] == "OK_REO")
            self.assertTrue(isinstance(r2, tuple) and r2[0] == "OK_ARC")
            
        self.assertEqual(rl.status, RoomList.StatusChoices.ARQUIVADA)
        self.assertIsNotNone(rl.archived_at)
        self.assertEqual(rl.archived_by_id, user_id)
        self.assertEqual(rl.content_revision, initial_revision)
class TestLodgingTemplateServices(RoomListServiceTestBase):
    def test_create_initial_template(self):
        # criação inicial do modelo
        payload = [
            {
                "type": "INDIVIDUAL",
                "capacity": 1,
                "participants": [self.integrante1.pk]
            }
        ]
        template = create_or_replace_lodging_template(self.band.pk, payload, self.user)
        self.assertEqual(template.band, self.band)
        self.assertEqual(template.rooms.count(), 1)
        self.assertEqual(template.participants.count(), 1)

    def test_create_multiple_rooms_and_association(self):
        # criação de múltiplos quartos, associação dos integrantes
        payload = [
            {
                "type": "DUPLO",
                "capacity": 2,
                "participants": [
                    self.integrante1.pk,
                    self.integrante2.pk,
                ]
            },
            {
                "type": "INDIVIDUAL",
                "capacity": 1,
                "participants": [self.integrante_inactive.pk]
            }
        ]
        template = create_or_replace_lodging_template(self.band.pk, payload, self.user)
        self.assertEqual(template.rooms.count(), 2)
        self.assertEqual(template.participants.count(), 3)
        self.assertEqual(template.rooms.filter(type="DUPLO").first().participants.count(), 2)

    def test_replace_template(self):
        # substituição integral do modelo anterior e remoção dos filhos antigos
        payload1 = [
            {
                "type": "INDIVIDUAL",
                "capacity": 1,
                "participants": [self.integrante1.pk]
            }
        ]
        create_or_replace_lodging_template(self.band.pk, payload1, self.user)
        
        self.assertEqual(LodgingTemplate.objects.count(), 1)
        self.assertEqual(TemplateRoom.objects.count(), 1)
        self.assertEqual(TemplateParticipant.objects.count(), 1)
        
        payload2 = [
            {
                "type": "DUPLO",
                "capacity": 2,
                "participants": [
                    self.integrante2.pk,
                    self.integrante_inactive.pk
                ]
            }
        ]
        create_or_replace_lodging_template(self.band.pk, payload2, self.user)
        
        self.assertEqual(LodgingTemplate.objects.count(), 1)
        self.assertEqual(TemplateRoom.objects.count(), 1)
        self.assertEqual(TemplateParticipant.objects.count(), 2)

    def test_deterministic_order(self):
        # ordem determinística dos quartos
        payload = [
            {"type": "INDIVIDUAL", "capacity": 1, "participants": [self.integrante1.pk]},
            {"type": "DUPLO", "capacity": 2, "participants": [self.integrante2.pk]},
            {"type": "CASAL", "capacity": 2, "participants": [self.integrante_inactive.pk]},
        ]
        template = create_or_replace_lodging_template(self.band.pk, payload, self.user)
        rooms = list(template.rooms.order_by('order'))
        self.assertEqual(rooms[0].type, "INDIVIDUAL")
        self.assertEqual(rooms[1].type, "DUPLO")
        self.assertEqual(rooms[2].type, "CASAL")

    def test_active_producer_own_band(self):
        # produtor ativo da própria banda (already covered by initial tests)
        payload = [{"type": "INDIVIDUAL", "capacity": 1, "participants": []}]
        template = create_or_replace_lodging_template(self.band.pk, payload, self.user)
        self.assertIsNotNone(template)

    def test_no_permission(self):
        # integrante sem permissão, produtor de outra banda, usuário inativo, superusuário sem vínculo
        payload = [{"type": "INDIVIDUAL", "capacity": 1, "participants": []}]
        
        # integrante sem permissão
        member_user = User.objects.create(username="member", is_active=True, band=self.band)
        with self.assertRaises(BandAccessDeniedError):
            create_or_replace_lodging_template(self.band.pk, payload, member_user)
            
        # produtor de outra banda
        with self.assertRaises(BandAccessDeniedError):
            create_or_replace_lodging_template(self.band.pk, payload, self.user_band2)
            
        # usuário inativo
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(BandAccessDeniedError):
            create_or_replace_lodging_template(self.band.pk, payload, self.user)
        self.user.is_active = True
        self.user.save()
        
        # superusuário sem vínculo
        su = User.objects.create(username="superuser", is_active=True, is_superuser=True)
        with self.assertRaises(BandAccessDeniedError):
            create_or_replace_lodging_template(self.band.pk, payload, su)

    def test_invalid_participants(self):
        # integrante pertencente a outra banda, integrante inexistente, integrante repetido
        # outra banda
        payload_other_band = [{"type": "INDIVIDUAL", "capacity": 1, "participants": [self.integrante_b2.pk]}]
        with self.assertRaises(RoomListServiceError):
            create_or_replace_lodging_template(self.band.pk, payload_other_band, self.user)
            
        # inexistente
        payload_inexistent = [{"type": "INDIVIDUAL", "capacity": 1, "participants": [99999]}]
        with self.assertRaises(RoomListServiceError):
            create_or_replace_lodging_template(self.band.pk, payload_inexistent, self.user)
            
        # repetido
        payload_repeated = [
            {"type": "INDIVIDUAL", "capacity": 1, "participants": [self.integrante1.pk]},
            {"type": "DUPLO", "capacity": 2, "participants": [self.integrante1.pk]}
        ]
        with self.assertRaises(RoomListServiceError):
            create_or_replace_lodging_template(self.band.pk, payload_repeated, self.user)

    def test_invalid_capacity(self):
        # tipo e capacidade incompatíveis
        payload = [{"type": "INDIVIDUAL", "capacity": 2, "participants": []}]
        with self.assertRaises(RoomCapacityTypeMismatchError):
            create_or_replace_lodging_template(self.band.pk, payload, self.user)

    def test_empty_payload(self):
        # payload vazio
        with self.assertRaises(RoomListServiceError):
            create_or_replace_lodging_template(self.band.pk, [], self.user)

    def test_rollback_on_error(self):
        # erro durante substituição com rollback integral
        payload1 = [{"type": "INDIVIDUAL", "capacity": 1, "participants": [self.integrante1.pk]}]
        create_or_replace_lodging_template(self.band.pk, payload1, self.user)
        
        # Ensure it was created
        self.assertEqual(TemplateRoom.objects.count(), 1)
        
        payload_invalid = [{"type": "INDIVIDUAL", "capacity": 1, "participants": [99999]}]
        with self.assertRaises(Exception):
            create_or_replace_lodging_template(self.band.pk, payload_invalid, self.user)
            
        # Rollback means the old template is completely intact
        self.assertEqual(TemplateRoom.objects.count(), 1)
        t_room = TemplateRoom.objects.first()
        self.assertEqual(t_room.capacity, 1)

    def test_delete_template(self):
        # exclusão do modelo
        payload = [{"type": "INDIVIDUAL", "capacity": 1, "participants": []}]
        create_or_replace_lodging_template(self.band.pk, payload, self.user)
        self.assertEqual(LodgingTemplate.objects.count(), 1)
        
        res = delete_lodging_template(self.band.pk, self.user)
        self.assertTrue(res)
        self.assertEqual(LodgingTemplate.objects.count(), 0)

    def test_delete_when_not_exists(self):
        # exclusão quando o modelo não existe
        res = delete_lodging_template(self.band.pk, self.user)
        self.assertFalse(res)

    def test_delete_does_not_affect_existing_room_list(self):
        # excluir o modelo não altera Room Lists existentes
        payload = [{"type": "INDIVIDUAL", "capacity": 1, "participants": [self.integrante1.pk]}]
        create_or_replace_lodging_template(self.band.pk, payload, self.user)
        
        rl = create_room_list(show_id=self.show.pk, band_id=self.band.pk, user=self.user, hotel_name="H", city="C")
        apply_template_to_room_list(rl.pk, self.user)
        self.assertEqual(rl.rooms.count(), 1)
        self.assertEqual(rl.participants.count(), 3)
        
        delete_lodging_template(self.band.pk, self.user)
        
        self.assertEqual(LodgingTemplate.objects.count(), 0)
        self.assertEqual(rl.rooms.count(), 1)
        self.assertEqual(rl.participants.count(), 3)

    def test_sequential_replacements(self):
        # duas substituições sequenciais sem resíduos
        p1 = [{"type": "INDIVIDUAL", "capacity": 1, "participants": [self.integrante1.pk]}]
        create_or_replace_lodging_template(self.band.pk, p1, self.user)
        p2 = [{"type": "DUPLO", "capacity": 2, "participants": []}]
        create_or_replace_lodging_template(self.band.pk, p2, self.user)
        p3 = [{"type": "CASAL", "capacity": 2, "participants": [self.integrante2.pk]}]
        create_or_replace_lodging_template(self.band.pk, p3, self.user)
        
        self.assertEqual(TemplateRoom.objects.count(), 1)
        self.assertEqual(TemplateRoom.objects.first().type, "CASAL")

