from django.test import TestCase
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta
from django.db.models import ProtectedError

from core.models import (
    Band, Show, Integrante, RoomList, Room, RoomListParticipant,
    LodgingTemplate, TemplateRoom, TemplateParticipant
)

class RoomListModelsTest(TestCase):
    def setUp(self):
        self.band1 = Band.objects.create(name="Banda 1", slug="banda-1")
        self.band2 = Band.objects.create(name="Banda 2", slug="banda-2")

        self.show1 = Show.objects.create(band=self.band1, title="Show 1")
        self.show2 = Show.objects.create(band=self.band2, title="Show 2")

        self.integrante1 = Integrante.objects.create(band=self.band1, name="Int 1", role="Musico", category="MUSICO")
        self.integrante2 = Integrante.objects.create(band=self.band1, name="Int 2", role="Musico", category="MUSICO")
        self.integrante_b2 = Integrante.objects.create(band=self.band2, name="Int B2", role="Musico", category="MUSICO")

    def test_01_criacao_valida(self):
        """1. Criação válida de RoomList"""
        rl = RoomList.objects.create(
            band=self.band1,
            show=self.show1,
            hotel_name="Hotel Test",
            city="Cidade Test"
        )
        self.assertEqual(RoomList.objects.count(), 1)
        self.assertEqual(rl.status, RoomList.StatusChoices.RASCUNHO)
        self.assertEqual(rl.content_revision, 1)

    def test_02_roomlist_sem_show_invalida(self):
        """2. RoomList sem Show é inválida"""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RoomList.objects.create(
                    band=self.band1,
                    hotel_name="Hotel Test",
                    city="Cidade Test"
                )

    def test_03_banda_diferente_do_show_rejeitada(self):
        """3. Banda da RoomList diferente da banda do Show é inválida"""
        rl = RoomList(
            band=self.band2,
            show=self.show1,  # Show 1 é da banda 1
            hotel_name="Hotel Test",
            city="Cidade Test"
        )
        with self.assertRaisesMessage(ValidationError, "RoomList.band deve ser a mesma banda do Show."):
            rl.clean()

    def test_04_mais_de_uma_roomlist_no_mesmo_show(self):
        """4. Mais de uma RoomList no mesmo Show é permitida"""
        RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H2", city="C2")
        self.assertEqual(RoomList.objects.filter(show=self.show1).count(), 2)

    def test_05_exclusao_show_com_roomlist_protegida(self):
        """5. Exclusão do Show com RoomList é protegida"""
        RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        with self.assertRaises(ProtectedError):
            self.show1.delete()

    def test_06_checkout_anterior_ou_igual_checkin_rejeitado(self):
        """6. Check-out anterior ou igual ao check-in é rejeitado"""
        now = timezone.now()
        rl = RoomList(
            band=self.band1, show=self.show1, hotel_name="H1", city="C1",
            check_in=now, check_out=now - timedelta(days=1)
        )
        with self.assertRaisesMessage(ValidationError, "Check-out deve ser posterior ao check-in"):
            rl.clean()

        rl.check_out = now
        with self.assertRaisesMessage(ValidationError, "Check-out deve ser posterior ao check-in"):
            rl.clean()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RoomList.objects.create(
                    band=self.band1, show=self.show1, hotel_name="H1", city="C1",
                    check_in=now, check_out=now
                )

    def test_07_checkin_checkout_nulos_em_rascunho(self):
        """7. Check-in ou check-out nulos são permitidos em rascunho"""
        rl = RoomList(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        rl.clean()  # Não deve lançar exceção
        rl.save()
        self.assertIsNone(rl.check_in)

    def test_08_content_revision_menor_que_1_rejeitado(self):
        """8. content_revision menor que 1 é rejeitado"""
        # Testando constraint do banco
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RoomList.objects.create(
                    band=self.band1, show=self.show1, hotel_name="H1", city="C1",
                    content_revision=0
                )

    def test_09_last_sent_revision_maior_que_content_revision_rejeitado(self):
        """9. last_sent_revision maior que content_revision é rejeitado"""
        # 8 e 9 testam as CheckConstraints
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RoomList.objects.create(
                    band=self.band1, show=self.show1, hotel_name="H1", city="C1",
                    content_revision=2, last_sent_revision=3
                )

    def test_10_was_sent(self):
        """10. Detecção de was_sent"""
        rl = RoomList(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        self.assertFalse(rl.was_sent)

        rl.last_sent_to_hotel_at = timezone.now()
        rl.last_sent_revision = 1
        self.assertTrue(rl.was_sent)

    def test_11_needs_resend(self):
        """11. Detecção de needs_resend"""
        rl = RoomList(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        rl.last_sent_to_hotel_at = timezone.now()
        rl.last_sent_revision = 1
        rl.content_revision = 1
        self.assertFalse(rl.needs_resend)

        rl.content_revision = 2
        self.assertTrue(rl.needs_resend)

    def test_12_capacidade_zero_rejeitada(self):
        """12. Capacidade zero ou negativa é rejeitada"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Room.objects.create(room_list=rl, number_or_name="101", type=Room.RoomTypeChoices.INDIVIDUAL, capacity=0)

    def test_13_quarto_duplicado_mesma_roomlist_rejeitado(self):
        """13. Quarto duplicado na mesma RoomList é rejeitado"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        Room.objects.create(room_list=rl, number_or_name="101", type=Room.RoomTypeChoices.INDIVIDUAL, capacity=1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Room.objects.create(room_list=rl, number_or_name="101", type=Room.RoomTypeChoices.CASAL, capacity=2)

    def test_14_mesmo_quarto_roomlists_diferentes_permitido(self):
        """14. Mesmo número de quarto em RoomLists diferentes é permitido"""
        rl1 = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        rl2 = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H2", city="C2")
        Room.objects.create(room_list=rl1, number_or_name="101", type=Room.RoomTypeChoices.INDIVIDUAL, capacity=1)
        Room.objects.create(room_list=rl2, number_or_name="101", type=Room.RoomTypeChoices.INDIVIDUAL, capacity=1)
        self.assertEqual(Room.objects.filter(number_or_name="101").count(), 2)

    def test_15_integrante_de_outra_banda_rejeitado(self):
        """15. Integrante de outra banda é rejeitado"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        p = RoomListParticipant(
            room_list=rl, original_integrante=self.integrante_b2,
            snapshot_name="Int B2"
        )
        with self.assertRaisesMessage(ValidationError, "integrante original deve pertencer à mesma banda"):
            p.clean()

    def test_16_quarto_de_outra_roomlist_rejeitado(self):
        """16. Quarto de outra RoomList é rejeitado para o participante"""
        rl1 = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        rl2 = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H2", city="C2")
        r2 = Room.objects.create(room_list=rl2, number_or_name="101", type=Room.RoomTypeChoices.INDIVIDUAL, capacity=1)

        p = RoomListParticipant(
            room_list=rl1, original_integrante=self.integrante1, room=r2,
            snapshot_name="Int 1"
        )
        with self.assertRaisesMessage(ValidationError, "quarto escolhido deve pertencer à mesma Room List"):
            p.clean()

    def test_17_integrante_duplicado_na_mesma_roomlist_rejeitado(self):
        """17. Integrante duplicado na mesma RoomList é rejeitado"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        RoomListParticipant.objects.create(room_list=rl, original_integrante=self.integrante1, snapshot_name="Int 1")
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RoomListParticipant.objects.create(room_list=rl, original_integrante=self.integrante1, snapshot_name="Int 1 Clone")

    def test_18_mesmo_integrante_roomlists_diferentes_permitido(self):
        """18. Mesmo integrante em RoomLists diferentes é permitido"""
        rl1 = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        rl2 = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H2", city="C2")
        RoomListParticipant.objects.create(room_list=rl1, original_integrante=self.integrante1, snapshot_name="Int 1")
        RoomListParticipant.objects.create(room_list=rl2, original_integrante=self.integrante1, snapshot_name="Int 1")
        self.assertEqual(RoomListParticipant.objects.filter(original_integrante=self.integrante1).count(), 2)

    def test_19_exclusao_integrante_mantem_roomlistparticipant(self):
        """19. Exclusão do Integrante mantém RoomListParticipant"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        p = RoomListParticipant.objects.create(
            room_list=rl, original_integrante=self.integrante1,
            snapshot_name="Int 1", snapshot_role="Musico"
        )
        self.integrante1.delete()
        p.refresh_from_db()
        self.assertIsNone(p.original_integrante)
        self.assertEqual(p.snapshot_name, "Int 1")

    def test_20_snapshots_permanecem(self):
        """20. Snapshots permanecem após edição ou exclusão da origem"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        p = RoomListParticipant.objects.create(
            room_list=rl, original_integrante=self.integrante1,
            snapshot_name="Int 1", snapshot_role="Musico"
        )
        self.integrante1.name = "Nome Editado"
        self.integrante1.save()
        p.refresh_from_db()
        self.assertEqual(p.snapshot_name, "Int 1")  # não muda

    def test_21_somente_um_lodgingtemplate_por_banda(self):
        """21. Uma banda pode ter somente um LodgingTemplate"""
        LodgingTemplate.objects.create(band=self.band1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                LodgingTemplate.objects.create(band=self.band1)

    def test_22_bandas_diferentes_podem_ter_seus_proprios_templates(self):
        """22. Bandas diferentes podem ter seus próprios templates"""
        LodgingTemplate.objects.create(band=self.band1)
        LodgingTemplate.objects.create(band=self.band2)
        self.assertEqual(LodgingTemplate.objects.count(), 2)

    def test_23_template_participant_outra_banda_rejeitado(self):
        """23. TemplateParticipant de outra banda é rejeitado"""
        lt = LodgingTemplate.objects.create(band=self.band1)
        tr = TemplateRoom.objects.create(template=lt, type=Room.RoomTypeChoices.INDIVIDUAL, capacity=1)
        tp = TemplateParticipant(
            template=lt, room=tr, original_integrante=self.integrante_b2
        )
        with self.assertRaisesMessage(ValidationError, "Integrante deve pertencer à banda do template"):
            tp.clean()

    def test_24_templateroom_de_outro_template_rejeitado(self):
        """24. TemplateRoom de outro template é rejeitado"""
        lt1 = LodgingTemplate.objects.create(band=self.band1)
        lt2 = LodgingTemplate.objects.create(band=self.band2)
        tr2 = TemplateRoom.objects.create(template=lt2, type=Room.RoomTypeChoices.INDIVIDUAL, capacity=1)

        tp = TemplateParticipant(
            template=lt1, room=tr2, original_integrante=self.integrante1
        )
        with self.assertRaisesMessage(ValidationError, "TemplateRoom deve pertencer ao mesmo LodgingTemplate"):
            tp.clean()

    def test_25_participante_duplicado_mesmo_template_rejeitado(self):
        """25. Participante duplicado no mesmo template é rejeitado"""
        lt = LodgingTemplate.objects.create(band=self.band1)
        tr = TemplateRoom.objects.create(template=lt, type=Room.RoomTypeChoices.INDIVIDUAL, capacity=1)
        TemplateParticipant.objects.create(template=lt, room=tr, original_integrante=self.integrante1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                TemplateParticipant.objects.create(template=lt, room=tr, original_integrante=self.integrante1)

    def test_26_exclusao_integrante_remove_templateparticipant(self):
        """26. Exclusão do integrante remove ou invalida corretamente sua entrada não histórica no template"""
        lt = LodgingTemplate.objects.create(band=self.band1)
        tr = TemplateRoom.objects.create(template=lt, type=Room.RoomTypeChoices.INDIVIDUAL, capacity=1)
        TemplateParticipant.objects.create(template=lt, room=tr, original_integrante=self.integrante1)

        self.integrante1.delete()
        self.assertEqual(TemplateParticipant.objects.count(), 0)

    def test_27_exclusoes_em_cascata_dos_filhos(self):
        """27. Exclusões em cascata dos filhos ocorrem apenas quando o pai é efetivamente removido"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        r = Room.objects.create(room_list=rl, number_or_name="101", type=Room.RoomTypeChoices.INDIVIDUAL, capacity=1)
        RoomListParticipant.objects.create(room_list=rl, room=r, original_integrante=self.integrante1, snapshot_name="Int 1")

        rl.delete()
        self.assertEqual(Room.objects.count(), 0)
        self.assertEqual(RoomListParticipant.objects.count(), 0)

    def test_28_constraints_diretamente_no_banco(self):
        """28. Constraints também são exercitadas diretamente no banco quando aplicável"""
        # test_08, test_09, test_12, test_13, test_17, test_25 já testaram as constraints do banco via IntegrityError
        # Aqui, apenas afirmamos que sim.
        pass

    def test_29_last_sent_rev_sem_data_rejeitado(self):
        """29. last_sent_revision preenchida sem last_sent_to_hotel_at (DB Constraint)"""
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                RoomList.objects.create(
                    band=self.band1, show=self.show1, hotel_name="H1", city="C1",
                    content_revision=2, last_sent_revision=1
                )

    def test_30_band_roomlist_protect(self):
        """30. Exclusão de Banda com RoomList é bloqueada (PROTECT)"""
        RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        with self.assertRaises(ProtectedError):
            self.band1.delete()

    def test_31_band_template_cascade(self):
        """31. Exclusão de Banda com apenas LodgingTemplate remove o template (CASCADE)"""
        LodgingTemplate.objects.create(band=self.band1)
        self.assertEqual(LodgingTemplate.objects.count(), 1)
        self.band1.delete()
        self.assertEqual(LodgingTemplate.objects.count(), 0)

    def test_32_clean_content_revision(self):
        """32. Clean() exige content_revision >= 1"""
        rl = RoomList(band=self.band1, show=self.show1, hotel_name="H1", city="C1", content_revision=0)
        with self.assertRaisesMessage(ValidationError, "A revisão de conteúdo deve ser maior ou igual a 1."):
            rl.full_clean()

    def test_33_clean_last_sent_revision_maior(self):
        """33. Clean() rejeita last_sent_revision > content_revision"""
        now = timezone.now()
        rl = RoomList(
            band=self.band1, show=self.show1, hotel_name="H1", city="C1",
            content_revision=1, last_sent_revision=2, last_sent_to_hotel_at=now
        )
        with self.assertRaisesMessage(ValidationError, "A revisão enviada não pode ser maior que a revisão atual de conteúdo."):
            rl.full_clean()

    def test_34_clean_room_capacity(self):
        """34. Clean() exige capacity > 0 em Room"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        r = Room(room_list=rl, number_or_name="101", type=Room.RoomTypeChoices.CASAL, capacity=0)
        with self.assertRaisesMessage(ValidationError, "A capacidade do quarto deve ser maior que zero."):
            r.full_clean()

    def test_35_clean_template_room_capacity(self):
        """35. Clean() exige capacity > 0 em TemplateRoom"""
        t = LodgingTemplate.objects.create(band=self.band1)
        r = TemplateRoom(template=t, type=Room.RoomTypeChoices.CASAL, capacity=0)
        with self.assertRaisesMessage(ValidationError, "A capacidade do quarto modelo deve ser maior que zero."):
            r.full_clean()

    def test_36_clean_last_sent_revision_sem_data_rejeitado(self):
        """36. Clean() rejeita last_sent_revision preenchida sem data"""
        rl = RoomList(
            band=self.band1, show=self.show1, hotel_name="H1", city="C1",
            content_revision=2, last_sent_revision=1, last_sent_to_hotel_at=None
        )
        with self.assertRaisesMessage(ValidationError, "Se last_sent_revision existir, last_sent_to_hotel_at também deve existir."):
            rl.full_clean()

    def test_37_clean_room_strip(self):
        """37. Room.clean() faz strip de number_or_name"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        r = Room(room_list=rl, number_or_name=" 101 ", type=Room.RoomTypeChoices.CASAL, capacity=2)
        r.full_clean()
        self.assertEqual(r.number_or_name, "101")

    def test_38_exclusao_room_set_null(self):
        """38. Exclusão de Room aplica SET_NULL em RoomListParticipant.room"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        r = Room.objects.create(room_list=rl, number_or_name="101", type=Room.RoomTypeChoices.CASAL, capacity=2)
        p = RoomListParticipant.objects.create(
            room_list=rl, room=r, snapshot_name="Teste"
        )
        self.assertEqual(p.room, r)
        r.delete()
        p.refresh_from_db()
        self.assertIsNone(p.room)

    def test_39_dois_participants_orig_nulo(self):
        """39. Dois participantes históricos com original_integrante nulo são permitidos"""
        rl = RoomList.objects.create(band=self.band1, show=self.show1, hotel_name="H1", city="C1")
        RoomListParticipant.objects.create(room_list=rl, snapshot_name="T1")
        RoomListParticipant.objects.create(room_list=rl, snapshot_name="T2")
        self.assertEqual(RoomListParticipant.objects.filter(room_list=rl).count(), 2)
