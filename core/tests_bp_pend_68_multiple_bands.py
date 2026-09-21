import datetime
import re
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    Band,
    User,
    UserBandMembership,
    SignupOrder,
    BandActivationToken,
    EmailDelivery,
)
from core.services.payments.provisioning import process_checkout_paid_event
from core.services.payments.activation import create_band_activation_token, verify_activation_token


class RecurringBuyerMultipleBandsTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        # CPF canônico válido para testes
        self.valid_cpf_1 = "11144477735"  # CPF válido com dígitos verificadores
        self.valid_cpf_2 = "52998224725"  # Outro CPF válido
        self.invalid_cpf = "12345678900"

    def test_first_purchase_creates_new_account_and_membership(self):
        """
        1. Primeira compra:
           - Cria token NEW_ACCOUNT;
           - Ativa usuário;
           - Salva CPF normalizado;
           - Cria primeira UserBandMembership(role='PRODUTOR', is_active=True).
        """
        payload = {
            'checkout': {
                'id': 'chk_first_purchase_01',
                'externalReference': 'bp-ord-first-001',
                'customer': 'cus_first_001',
            },
            'payment': {
                'id': 'pay_first_001',
                'value': 49.90,
                'billingType': 'CREDIT_CARD',
            }
        }

        order = SignupOrder.objects.create(
            external_reference='bp-ord-first-001',
            gateway_checkout_id='chk_first_purchase_01',
            gateway_customer_id='cus_first_001',
            band_name='Banda Alfa',
            responsible_name='João Silva',
            responsible_cpf=self.valid_cpf_1,
            cpf_cnpj=self.valid_cpf_1,
            email='joao.silva@email.com',
            amount=Decimal('49.90'),
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            status='PENDENTE'
        )

        success, msg, band = process_checkout_paid_event(payload)
        self.assertTrue(success)
        self.assertIsNotNone(band)

        # Verifica token criado
        token_obj = BandActivationToken.objects.filter(band=band, signup_order=order).first()
        self.assertIsNotNone(token_obj)
        self.assertEqual(token_obj.token_type, BandActivationToken.TokenType.NEW_ACCOUNT)
        self.assertIsNone(token_obj.target_user)

        # Verifica e-mail ACCOUNT_ACTIVATION
        delivery = EmailDelivery.objects.filter(related_object_id=str(token_obj.pk)).first()
        self.assertIsNotNone(delivery)
        self.assertEqual(delivery.email_type, EmailDelivery.EmailType.ACCOUNT_ACTIVATION)

        # Ativa conta via POST na ActivateAccountView
        from core.services.payments.security import decrypt_activation_token
        raw_token = decrypt_activation_token(token_obj.encrypted_token)

        resp = self.client.post(reverse('activate_account', kwargs={'token': raw_token}), {
            'username': 'joaosilva',
            'password': 'Password@123',
            'confirm_password': 'Password@123',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Conta criada com sucesso")

        # Verifica User criado
        user = User.objects.filter(username='joaosilva').first()
        self.assertIsNotNone(user)
        self.assertEqual(user.cpf, self.valid_cpf_1)
        self.assertEqual(user.band, band)

        # Verifica criação obrigatória da UserBandMembership
        membership = UserBandMembership.objects.filter(user=user, band=band).first()
        self.assertIsNotNone(membership)
        self.assertEqual(membership.role, 'PRODUTOR')
        self.assertTrue(membership.is_active)

    def test_second_purchase_same_cpf_generates_link_band_and_no_second_user(self):
        """
        2. Segunda compra do mesmo CPF:
           - Não cria segundo User no webhook;
           - Gera token LINK_BAND com target_user apontando para o usuário existente;
           - Não envia ACCOUNT_ACTIVATION, e sim BAND_ADDED_TO_EXISTING_ACCOUNT.
        """
        band_1 = Band.objects.create(name="Banda 1", slug="banda-1")
        user = User.objects.create_user(
            username="joao_existente",
            email="joao@email.com",
            password="Password@123",
            cpf=self.valid_cpf_1,
            first_name="João",
            band=band_1
        )
        UserBandMembership.objects.create(user=user, band=band_1, role='PRODUTOR', is_active=True)

        user_count_before = User.objects.count()

        payload = {
            'checkout': {
                'id': 'chk_second_purchase_02',
                'externalReference': 'bp-ord-second-002',
                'customer': 'cus_second_002',
            },
            'payment': {
                'id': 'pay_second_002',
                'value': 49.90,
                'billingType': 'CREDIT_CARD',
            }
        }

        order_2 = SignupOrder.objects.create(
            external_reference='bp-ord-second-002',
            gateway_checkout_id='chk_second_purchase_02',
            band_name='Banda Beta',
            responsible_name='João Silva',
            responsible_cpf=self.valid_cpf_1,
            cpf_cnpj='12345678000195',  # CNPJ pagador diferente!
            email='joao@email.com',
            amount=Decimal('49.90'),
            plan_type='AVANCADO',
            billing_cycle='MENSAL',
            status='PENDENTE'
        )

        success, msg, band_2 = process_checkout_paid_event(payload)
        self.assertTrue(success)

        # Não criou segundo User
        self.assertEqual(User.objects.count(), user_count_before)

        # Token gerado é LINK_BAND com target_user
        token_obj = BandActivationToken.objects.filter(band=band_2, signup_order=order_2).first()
        self.assertIsNotNone(token_obj)
        self.assertEqual(token_obj.token_type, BandActivationToken.TokenType.LINK_BAND)
        self.assertEqual(token_obj.target_user, user)

        # E-mail enviado é BAND_ADDED_TO_EXISTING_ACCOUNT e NUNCA ACCOUNT_ACTIVATION
        self.assertFalse(EmailDelivery.objects.filter(email_type=EmailDelivery.EmailType.ACCOUNT_ACTIVATION, related_object_id=str(token_obj.pk)).exists())
        link_email = EmailDelivery.objects.filter(email_type=EmailDelivery.EmailType.BAND_ADDED_TO_EXISTING_ACCOUNT, related_object_id=str(token_obj.pk)).first()
        self.assertIsNotNone(link_email)

    def test_authenticated_user_confirms_link_band_creates_membership_and_two_bands(self):
        """
        3. Usuário autenticado confirma LINK_BAND:
           - Cria membership para a nova banda;
           - Mesma conta passa a ter duas bandas ativas;
           - Token é consumido.
        """
        band_1 = Band.objects.create(name="Banda 1", slug="banda-1")
        band_2 = Band.objects.create(name="Banda 2", slug="banda-2")
        user = User.objects.create_user(
            username="produtor_multi",
            email="multi@email.com",
            password="Password@123",
            cpf=self.valid_cpf_1,
            band=band_1
        )
        UserBandMembership.objects.create(user=user, band=band_1, role='PRODUTOR', is_active=True)

        token_obj, raw_token = create_band_activation_token(
            band=band_2,
            email=user.email,
            responsible_name="Produtor Multi",
            token_type=BandActivationToken.TokenType.LINK_BAND,
            target_user=user
        )

        # Login com o usuário correto
        self.client.login(username="produtor_multi", password="Password@123")

        # GET deve indicar que está autenticado como target
        resp_get = self.client.get(reverse('activate_account', kwargs={'token': raw_token}))
        self.assertEqual(resp_get.status_code, 200)
        self.assertContains(resp_get, "Confirmar e Adicionar Banda")

        # POST confirma vínculo
        resp_post = self.client.post(reverse('activate_account', kwargs={'token': raw_token}))
        self.assertEqual(resp_post.status_code, 200)
        self.assertContains(resp_post, "Banda Adicionada com Sucesso")

        # Membership criada
        membership_2 = UserBandMembership.objects.filter(user=user, band=band_2).first()
        self.assertIsNotNone(membership_2)
        self.assertTrue(membership_2.is_active)
        self.assertEqual(membership_2.role, 'PRODUTOR')

        # Usuário possui 2 bandas ativas no multilogin
        self.assertEqual(user.get_active_memberships().count(), 2)

        # Token foi marcado como consumido
        token_obj.refresh_from_db()
        self.assertIsNotNone(token_obj.used_at)

    def test_wrong_user_cannot_consume_link_band(self):
        """
        4. Usuário errado tenta consumir LINK_BAND:
           - Acesso negado;
           - Nenhuma membership criada para o usuário errado ou indevido.
        """
        band_1 = Band.objects.create(name="Banda 1", slug="banda-1")
        band_new = Band.objects.create(name="Banda Nova", slug="banda-nova")

        target_user = User.objects.create_user(
            username="target_user",
            email="target@email.com",
            password="Password@123",
            cpf=self.valid_cpf_1,
            band=band_1
        )
        intruder_user = User.objects.create_user(
            username="intruder_user",
            email="intruder@email.com",
            password="Password@123",
            cpf=self.valid_cpf_2
        )

        token_obj, raw_token = create_band_activation_token(
            band=band_new,
            email=target_user.email,
            responsible_name="Target",
            token_type=BandActivationToken.TokenType.LINK_BAND,
            target_user=target_user
        )

        # 4.1 Usuário intruso já logado tenta consumir
        self.client.login(username="intruder_user", password="Password@123")
        resp = self.client.post(reverse('activate_account', kwargs={'token': raw_token}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "este convite pertence à conta")
        self.assertFalse(UserBandMembership.objects.filter(band=band_new).exists())

        # 4.2 Deslogado informando credenciais erradas
        self.client.logout()
        resp_invalid_cred = self.client.post(reverse('activate_account', kwargs={'token': raw_token}), {
            'login_identifier': 'target_user',
            'password': 'SenhaErrada123',
        })
        self.assertEqual(resp_invalid_cred.status_code, 200)
        self.assertContains(resp_invalid_cred, "Login ou senha incorretos")
        self.assertFalse(UserBandMembership.objects.filter(band=band_new).exists())

    def test_same_cpf_different_email_demands_authentication_and_emails_target_user(self):
        """
        5. Mesmo CPF + e-mail diferente:
           - Não vincula silenciosamente no checkout;
           - Token LINK_BAND enviado para o e-mail da CONTA EXISTENTE;
           - Exige autenticação correta da conta existente para vincular.
        """
        band_existing = Band.objects.create(name="Banda Alpha", slug="banda-alpha")
        existing_user = User.objects.create_user(
            username="carlos_titular",
            email="carlos.original@empresa.com",
            password="Password@123",
            cpf=self.valid_cpf_1,
            band=band_existing
        )

        payload = {
            'checkout': {
                'id': 'chk_diff_email_03',
                'externalReference': 'bp-ord-diff-003',
            },
            'payment': {
                'id': 'pay_diff_003',
                'value': 19.90,
                'billingType': 'PIX',
            }
        }

        order = SignupOrder.objects.create(
            external_reference='bp-ord-diff-003',
            gateway_checkout_id='chk_diff_email_03',
            band_name='Banda Nova Diferente',
            responsible_name='Carlos',
            responsible_cpf=self.valid_cpf_1,
            email='carlos.outro@gmail.com',  # E-MAIL DIFERENTE na nova compra!
            amount=Decimal('19.90'),
            plan_type='BASICO',
            billing_cycle='MENSAL',
            status='PENDENTE'
        )

        success, msg, band_new = process_checkout_paid_event(payload)
        self.assertTrue(success)

        # O token deve ter sido criado com o e-mail cadastrado na conta existente por segurança
        token_obj = BandActivationToken.objects.filter(band=band_new, signup_order=order).first()
        self.assertEqual(token_obj.token_type, BandActivationToken.TokenType.LINK_BAND)
        self.assertEqual(token_obj.target_user, existing_user)
        self.assertEqual(token_obj.email, "carlos.original@empresa.com")

        # O e-mail da conta existente NÃO deve ter sido alterado
        existing_user.refresh_from_db()
        self.assertEqual(existing_user.email, "carlos.original@empresa.com")

        # Nenhuma membership antes de autenticar
        self.assertFalse(UserBandMembership.objects.filter(user=existing_user, band=band_new).exists())

        # Ao autenticar deslogado fornecendo login e senha corretos da conta existente:
        from core.services.payments.security import decrypt_activation_token
        raw_token = decrypt_activation_token(token_obj.encrypted_token)

        resp = self.client.post(reverse('activate_account', kwargs={'token': raw_token}), {
            'login_identifier': 'carlos_titular',
            'password': 'Password@123',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Banda Adicionada com Sucesso")
        self.assertTrue(UserBandMembership.objects.filter(user=existing_user, band=band_new).exists())

    def test_repetition_of_token_or_webhook_is_idempotent(self):
        """
        6. Repetição do token/webhook:
           - Não duplica bandas;
           - Não duplica memberships;
           - Reclique no token após consumo não gera erro 500 nem duplicação.
        """
        band = Band.objects.create(name="Banda Repeticao", slug="banda-rep")
        user = User.objects.create_user(
            username="user_rep",
            email="rep@teste.com",
            password="Password@123",
            cpf=self.valid_cpf_1,
            band=band
        )
        UserBandMembership.objects.create(user=user, band=band, role='PRODUTOR', is_active=True)

        token_obj, raw_token = create_band_activation_token(
            band=band,
            email=user.email,
            responsible_name="Rep",
            token_type=BandActivationToken.TokenType.LINK_BAND,
            target_user=user
        )

        self.client.login(username="user_rep", password="Password@123")

        # Primeiro clique: vincula
        resp1 = self.client.post(reverse('activate_account', kwargs={'token': raw_token}))
        self.assertEqual(resp1.status_code, 200)

        # Segundo clique repetido (já consumido):
        resp2 = self.client.post(reverse('activate_account', kwargs={'token': raw_token}))
        self.assertEqual(resp2.status_code, 302)  # Redireciona para /selecionar-banda/ de forma segura

        # Quantidade de memberships permanece estritamente 1
        self.assertEqual(UserBandMembership.objects.filter(user=user, band=band).count(), 1)
