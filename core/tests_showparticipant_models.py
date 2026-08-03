from django.test import TestCase
from django.db import IntegrityError
from django.core.exceptions import ValidationError

from core.models import Band, Show, Integrante, ShowParticipant

class ShowParticipantModelsTest(TestCase):
    def setUp(self):
        self.band1 = Band.objects.create(name="Banda 1", slug="banda-1")
        self.band2 = Band.objects.create(name="Banda 2", slug="banda-2")

        self.show1 = Show.objects.create(band=self.band1, title="Show 1")
        self.show2 = Show.objects.create(band=self.band2, title="Show 2")

        self.integrante1 = Integrante.objects.create(band=self.band1, name="Int 1", role="Musico", category="MUSICO")
        self.integrante2 = Integrante.objects.create(band=self.band1, name="Int 2", role="Musico", category="MUSICO")
        self.integrante_b2 = Integrante.objects.create(band=self.band2, name="Int B2", role="Musico", category="MUSICO")

    def test_01_criacao_valida(self):
        """1. Criação válida de ShowParticipant"""
        participant = ShowParticipant.objects.create(
            show=self.show1,
            integrante=self.integrante1,
            order=1
        )
        participant.full_clean()
        self.assertEqual(ShowParticipant.objects.count(), 1)
        self.assertEqual(participant.show, self.show1)
        self.assertEqual(participant.integrante, self.integrante1)

        # Test default is_active value on Integrante
        self.assertTrue(self.integrante1.is_active)

    def test_02_bloqueio_cross_band(self):
        """2. Bloqueio ao tentar escalar integrante de uma banda no show de outra"""
        participant = ShowParticipant(
            show=self.show1,
            integrante=self.integrante_b2
        )
        with self.assertRaises(ValidationError) as cm:
            participant.full_clean()
        self.assertIn("O integrante escalado deve pertencer à mesma banda do show.", cm.exception.message_dict.get('integrante', []))

    def test_03_unicidade_por_show(self):
        """3. Bloqueio ao tentar escalar o mesmo integrante mais de uma vez no mesmo show"""
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)
        with self.assertRaises(IntegrityError):
            ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)

    def test_04_escalar_multiplos_integrantes_no_mesmo_show(self):
        """4. Permitir escalar diferentes integrantes no mesmo show"""
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante2)
        self.assertEqual(ShowParticipant.objects.filter(show=self.show1).count(), 2)

    def test_05_integrante_em_multiplos_shows(self):
        """5. Permitir que o mesmo integrante seja escalado em shows diferentes da mesma banda"""
        show1_b = Show.objects.create(band=self.band1, title="Show 1B")
        ShowParticipant.objects.create(show=self.show1, integrante=self.integrante1)
        ShowParticipant.objects.create(show=show1_b, integrante=self.integrante1)
        self.assertEqual(ShowParticipant.objects.filter(integrante=self.integrante1).count(), 2)
