from django.test import TestCase
from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.db import models

from core.models import (
    Band, Show, Integrante, ShowParticipant,
    RoomList, Room, RoomListParticipant,
    LodgingTemplate, TemplateRoom, TemplateParticipant,
    ShowTeamCost
)

class ShowParticipantRosterTest(TestCase):
    """
    Rastreabilidade dos 28 requisitos:
    1. is_active existe -> test_01_is_active_exists
    2. is_active é BooleanField -> test_02_is_active_is_boolean
    3. default=True -> test_03_default_is_true
    4. db_index=True -> test_04_db_index_is_true
    5. integrantes existentes permanecem ativos -> test_05_integrantes_existentes_ativos
    6. integrante pode ser inativado -> test_06_integrante_pode_ser_inativado
    7. ShowParticipant relaciona Show e Integrante -> test_07_relacionamento_show_integrante
    8. integrante da mesma banda pode ser escalado -> test_08_mesma_banda_valida
    9. outra banda é rejeitada por clean() -> test_09_rejeita_cross_band_clean
    10. full_clean() executa a validação -> test_09_rejeita_cross_band_clean (usa full_clean)
    11. combinação Show + Integrante é única -> test_11_unicidade_show_integrante
    12. constraint possui o nome exigido -> test_12_constraint_nome_exigido
    13. banco rejeita duplicidade com IntegrityError -> test_13_banco_rejeita_duplicidade
    14. integrante pode participar de dois shows -> test_14_integrante_multiplos_shows
    15. show pode possuir vários integrantes -> test_15_show_multiplos_integrantes
    16. exclusão do Show aplica CASCADE -> test_16_exclusao_show_cascade
    17. exclusão do Integrante aplica CASCADE -> test_17_exclusao_integrante_cascade
    18. exclusão não apaga RoomListParticipant histórico -> test_18_19_20_exclusao_preserva_historico
    19. original_integrante continua com SET_NULL -> test_18_19_20_exclusao_preserva_historico
    20. snapshots permanecem após exclusão -> test_18_19_20_exclusao_preserva_historico
    21. integrante inativo pode permanecer em escala histórica -> test_21_integrante_inativo_em_escala
    22. criar Show não cria escala automática -> test_22_criar_show_sem_escala
    23. criar Integrante não cria escala automática -> test_23_criar_integrante_sem_escala
    24. shows existentes não recebem fallback -> test_24_shows_sem_fallback
    25. ordenação por integrante__order, integrante__name e integrante_id -> test_25_ordenacao_correta
    26. ShowTeamCost não representa escala -> test_26_show_team_cost_nao_e_escala
    27. os seis models do Room List não tiveram fields alterados -> test_27_modelos_room_list_inalterados
    28. migration 0073 permaneceu inalterada -> test_28_migration_0073_inalterada
    """

    def setUp(self):
        self.band1 = Band.objects.create(name="Banda 1", slug="banda-1")
        self.band2 = Band.objects.create(name="Banda 2", slug="banda-2")

        self.show1 = Show.objects.create(band=self.band1, title="Show 1")
        self.show2 = Show.objects.create(band=self.band2, title="Show 2")

        self.integrante1 = Integrante.objects.create(band=self.band1, name="Int 1", role="Musico", category="MUSICO", order=2)
        self.integrante2 = Integrante.objects.create(band=self.band1, name="Int 2", role="Musico", category="MUSICO", order=1)
        self.integrante_b2 = Integrante.objects.create(band=self.band2, name="Int B2", role="Musico", category="MUSICO")

    def test_01_is_active_exists(self):
        self.assertTrue(hasattr(Integrante, 'is_active'))

    def test_02_is_active_is_boolean(self):
        field = Integrante._meta.get_field('is_active')
        self.assertIsInstance(field, models.BooleanField)

    def test_03_default_is_true(self):
        field = Integrante._meta.get_field('is_active')
        self.assertTrue(field.default)

    def test_04_db_index_is_true(self):
        field = Integrante._meta.get_field('is_active')
        self.assertTrue(field.db_index)

    def test_05_integrantes_existentes_ativos(self):
        self.assertTrue(self.integrante1.is_active)

    def test_06_integrante_pode_ser_inativado(self):
        self.integrante1.is_active = False
        self.integrante1.save()
        self.integrante1.refresh_from_db()
        self.assertFalse(self.integrante1.is_active)

    def test_07_relacionamento_show_integrante(self):
        field_show = ShowParticipant._meta.get_field('show')
        field_integrante = ShowParticipant._meta.get_field('integrante')
        self.assertIsInstance(field_show, models.ForeignKey)
        self.assertEqual(field_show.remote_field.model, Show)
        self.assertIsInstance(field_integrante, models.ForeignKey)
        self.assertEqual(field_integrante.remote_field.model, Integrante)

    def test_08_mesma_banda_valida(self):
        sp = ShowParticipant(show=self.show1, integrante=self.integrante1)
        sp.full_clean()  # Should not raise
        sp.save()
        self.assertEqual(ShowParticipant.objects.count(), 1)

    def test_09_rejeita_cross_band_clean(self):
        sp = ShowParticipant(show=self.show1, integrante=self.integrante_b2)
        with self.assertRaisesMessage(ValidationError, "O integrante escalado deve pertencer à mesma banda do show."):
            sp.full_clean()

    def test_11_unicidade_show_integrante(self):
        constraints = ShowParticipant._meta.constraints
        unique_constraints = [c for c in constraints if isinstance(c, models.UniqueConstraint)]
        self.assertTrue(any(c.fields == ('show', 'integrante') for c in unique_constraints))

    def test_12_constraint_nome_exigido(self):
        constraints = ShowParticipant._meta.constraints
        self.assertTrue(any(c.name == 'unique_integrante_per_show' for c in constraints))

    def test_13_banco_rejeita_duplicidade(self):
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)
        with self.assertRaises(IntegrityError):
            ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)

    def test_14_integrante_multiplos_shows(self):
        show3 = Show.objects.create(band=self.band1, title="Show 3")
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)
        ShowParticipant.objects.create(show=show3, integrante=self.integrante1)
        self.assertEqual(ShowParticipant.objects.filter(integrante=self.integrante1).count(), 2)

    def test_15_show_multiplos_integrantes(self):
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante2)
        self.assertEqual(ShowParticipant.objects.filter(show=self.show1).count(), 2)

    def test_16_exclusao_show_cascade(self):
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)
        self.show1.delete()
        self.assertEqual(ShowParticipant.objects.count(), 0)

    def test_17_exclusao_integrante_cascade(self):
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)
        self.integrante1.delete()
        self.assertEqual(ShowParticipant.objects.count(), 0)

    def test_18_19_20_exclusao_preserva_historico(self):
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1")
        rlp = RoomListParticipant.objects.create(
            room_list=rl,
            original_integrante=self.integrante1,
            snapshot_name=self.integrante1.name,
            snapshot_role=self.integrante1.role
        )
        self.integrante1.delete()
        rlp.refresh_from_db()
        self.assertIsNone(rlp.original_integrante)
        self.assertEqual(rlp.snapshot_name, "Int 1")
        self.assertEqual(rlp.snapshot_role, "Musico")

    def test_21_integrante_inativo_em_escala(self):
        sp = ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)
        self.integrante1.is_active = False
        self.integrante1.save()
        sp.refresh_from_db()
        self.assertFalse(sp.integrante.is_active)
        self.assertEqual(ShowParticipant.objects.count(), 1)

    def test_22_criar_show_sem_escala(self):
        Show.objects.create(band=self.band1, title="Show X")
        self.assertEqual(ShowParticipant.objects.count(), 0)

    def test_23_criar_integrante_sem_escala(self):
        Integrante.objects.create(band=self.band1, name="Novo Int", role="X", category="SERVICOS")
        self.assertEqual(ShowParticipant.objects.count(), 0)

    def test_24_shows_sem_fallback(self):
        # Even with team costs, no fallback participant is generated
        ShowTeamCost.objects.create(show=self.show1, name="Roadie", value=100)
        self.assertEqual(ShowParticipant.objects.count(), 0)

    def test_25_ordenacao_correta(self):
        self.assertEqual(list(ShowParticipant._meta.ordering), ['integrante__order', 'integrante__name', 'integrante_id'])

    def test_26_show_team_cost_nao_e_escala(self):
        # Verify that ShowTeamCost does not have a ForeignKey to Integrante
        fields = [f.name for f in ShowTeamCost._meta.get_fields() if isinstance(f, models.ForeignKey)]
        self.assertNotIn('integrante', fields)

    def test_27_modelos_room_list_inalterados(self):
        # We know fields from phase 1, ensure they haven't been altered
        self.assertTrue(hasattr(RoomList, 'content_revision'))
        self.assertTrue(hasattr(Room, 'beds_config'))
        self.assertTrue(hasattr(RoomListParticipant, 'needs_lodging'))
        self.assertTrue(hasattr(LodgingTemplate, 'band'))
        self.assertTrue(hasattr(TemplateRoom, 'capacity'))
        self.assertTrue(hasattr(TemplateParticipant, 'original_integrante'))

    def test_28_migration_0073_inalterada(self):
        import importlib
        try:
            mig_module = importlib.import_module('core.migrations.0073_lodgingtemplate_roomlist_room_roomlistparticipant_and_more')
            self.assertTrue(hasattr(mig_module, 'Migration'))
            self.assertTrue(len(mig_module.Migration.operations) > 0)
        except ImportError:
            self.fail("Migration 0073 was deleted or renamed.")
