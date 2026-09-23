import logging
import re
from django.shortcuts import render, redirect
from django.views import View
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model, authenticate, login as auth_login
from django.urls import reverse
from core.models import BandActivationToken, SignupOrder, UserBandMembership
from core.services.payments.activation import verify_activation_token

logger = logging.getLogger(__name__)
User = get_user_model()


class ActivateAccountView(View):
    template_name = 'core/activate_account.html'

    def get(self, request, token):
        is_valid, error_code, activation = verify_activation_token(token)

        context = {
            'token': token,
            'is_valid': is_valid,
            'error_code': error_code,
            'activation': activation,
            'band': activation.band if activation else None,
            'token_type': activation.token_type if activation else BandActivationToken.TokenType.NEW_ACCOUNT,
            'target_user': activation.target_user if activation else None,
            'is_authenticated_as_target': (
                request.user.is_authenticated and activation and activation.target_user and request.user == activation.target_user
            ),
        }
        return render(request, self.template_name, context)

    def post(self, request, token):
        is_valid, error_code, activation = verify_activation_token(token)

        if not is_valid or not activation:
            if activation and error_code == 'TOKEN_JA_UTILIZADO':
                band = activation.band
                if request.user.is_authenticated and band and request.user.has_access_to_band(band):
                    return redirect('selecionar_banda')
            return render(request, self.template_name, {
                'token': token,
                'is_valid': False,
                'error_code': error_code,
                'activation': activation,
                'band': activation.band if activation else None,
            })

        band = activation.band
        if not band:
            return render(request, self.template_name, {
                'token': token,
                'is_valid': False,
                'error_code': 'BAND_NAO_ENCONTRADA',
                'activation': activation,
                'band': None,
            })

        # =========================================================================
        # FLUXO LINK_BAND: Vincular nova banda à conta de usuário existente
        # =========================================================================
        if activation.token_type == BandActivationToken.TokenType.LINK_BAND:
            target_user = activation.target_user
            if not target_user:
                return render(request, self.template_name, {
                    'token': token,
                    'is_valid': False,
                    'error_code': 'TARGET_USER_NAO_ENCONTRADO',
                    'activation': activation,
                    'band': band,
                })

            # Verifica autenticação
            authenticated_user = None
            if request.user.is_authenticated:
                if request.user == target_user:
                    authenticated_user = request.user
                else:
                    # Usuário está logado, mas em outra conta diferente do target_user!
                    return render(request, self.template_name, {
                        'token': token,
                        'is_valid': True,
                        'activation': activation,
                        'band': band,
                        'token_type': activation.token_type,
                        'target_user': target_user,
                        'errors': [
                            f"Você está conectado como '{request.user.username}', mas este convite pertence à conta '{target_user.username}'. Faça logout ou entre com a conta correta."
                        ],
                    })
            else:
                # Deslogado: validar credenciais informadas no form
                login_identifier = (request.POST.get('login_identifier') or '').strip()
                password = request.POST.get('password') or ''

                if not login_identifier:
                    return render(request, self.template_name, {
                        'token': token,
                        'is_valid': True,
                        'activation': activation,
                        'band': band,
                        'token_type': activation.token_type,
                        'target_user': target_user,
                        'errors': ["Informe seu Login ou E-mail habitual."],
                        'form_login_identifier': login_identifier,
                    })

                if not password:
                    return render(request, self.template_name, {
                        'token': token,
                        'is_valid': True,
                        'activation': activation,
                        'band': band,
                        'token_type': activation.token_type,
                        'target_user': target_user,
                        'errors': ["Informe sua senha de acesso."],
                        'form_login_identifier': login_identifier,
                    })

                # Tenta autenticar por username ou por email
                auth_user = authenticate(request, username=login_identifier, password=password)
                if not auth_user and '@' in login_identifier:
                    user_by_email = User.objects.filter(email__iexact=login_identifier).first()
                    if user_by_email:
                        auth_user = authenticate(request, username=user_by_email.username, password=password)

                if not auth_user or auth_user != target_user:
                    return render(request, self.template_name, {
                        'token': token,
                        'is_valid': True,
                        'activation': activation,
                        'band': band,
                        'token_type': activation.token_type,
                        'target_user': target_user,
                        'errors': ["Login ou senha incorretos para esta conta. Verifique suas credenciais."],
                        'form_login_identifier': login_identifier,
                    })

                # Autentica na sessão
                auth_login(request, auth_user)
                authenticated_user = auth_user

            # Execução atômica e idempotente do vínculo
            with transaction.atomic():
                act = BandActivationToken.objects.select_for_update().get(pk=activation.pk)
                if act.used_at is not None:
                    # Token já consumido: se usuário já tem acesso, redireciona com sucesso
                    if authenticated_user.has_access_to_band(band):
                        return redirect('selecionar_banda')
                    return render(request, self.template_name, {
                        'token': token,
                        'is_valid': False,
                        'error_code': 'TOKEN_JA_UTILIZADO',
                        'activation': activation,
                        'band': band,
                    })

                if timezone.now() > act.expires_at:
                    return render(request, self.template_name, {
                        'token': token,
                        'is_valid': False,
                        'error_code': 'TOKEN_EXPIRADO',
                        'activation': activation,
                        'band': band,
                    })

                # 1. Cria ou ativa UserBandMembership como EMPRESARIO (titular da nova assinatura/banda)
                membership, created = UserBandMembership.objects.get_or_create(
                    user=authenticated_user,
                    band=band,
                    defaults={'role': 'EMPRESARIO', 'is_active': True}
                )
                fields_to_update = []
                if not membership.is_active:
                    membership.is_active = True
                    fields_to_update.append('is_active')
                if membership.role != 'EMPRESARIO':
                    membership.role = 'EMPRESARIO'
                    fields_to_update.append('role')
                if fields_to_update:
                    membership.save(update_fields=fields_to_update)

                # 2. Se o usuário legado estiver com CPF em branco, preenche com responsible_cpf do pedido
                signup_order = act.signup_order
                if signup_order and getattr(signup_order, 'responsible_cpf', None):
                    resp_cpf = re.sub(r'\D', '', signup_order.responsible_cpf)
                    if resp_cpf and len(resp_cpf) == 11 and not authenticated_user.cpf:
                        # Confere se o CPF não pertence a outro usuário
                        if not User.objects.filter(cpf=resp_cpf).exclude(pk=authenticated_user.pk).exists():
                            authenticated_user.cpf = resp_cpf
                            authenticated_user.save(update_fields=['cpf'])
                            logger.info("CPF preenchido para usuario legado %s via LINK_BAND", authenticated_user.username)

                # 3. Se usuário não tiver user.band preenchido, define esta como default
                if not authenticated_user.band_id:
                    authenticated_user.band = band
                    authenticated_user.save(update_fields=['band'])

                # 4. Vincula signup_order.activated_user caso esteja vago
                if signup_order and not signup_order.activated_user:
                    signup_order.activated_user = authenticated_user
                    signup_order.save(update_fields=['activated_user'])

                # 5. Marca token como utilizado
                act.used_at = timezone.now()
                act.save(update_fields=['used_at'])

                logger.info(
                    "Banda '%s' (slug=%s) vinculada com sucesso ao usuario existente '%s' (user_id=%s)",
                    band.name, band.slug, authenticated_user.username, authenticated_user.id
                )

            # Redireciona para selecionar banda ou renderiza confirmação
            request.session['active_band_id'] = band.id
            active_count = authenticated_user.get_active_memberships().count()

            return render(request, self.template_name, {
                'success': True,
                'link_success': True,
                'band': band,
                'username': authenticated_user.username,
                'active_count': active_count,
                'redirect_url': reverse('selecionar_banda') if active_count >= 2 else f"/{band.slug}/painel/",
            })

        # =========================================================================
        # FLUXO NEW_ACCOUNT: Primeiro acesso e criação de novo usuário
        # =========================================================================
        username = (request.POST.get('username') or '').strip()
        password = request.POST.get('password') or ''
        confirm_password = request.POST.get('confirm_password') or ''

        errors = []

        # 1. Validação de Username
        if not username:
            errors.append("O campo Login é obrigatório.")
        elif User.objects.filter(username__iexact=username).exists():
            errors.append("Este login já está em uso. Escolha outro.")

        # 2. Validação de Senha
        if not password:
            errors.append("O campo Senha é obrigatório.")
        elif not confirm_password:
            errors.append("Confirme sua senha.")
        elif password != confirm_password:
            errors.append("As senhas não coincidem.")

        if errors:
            return render(request, self.template_name, {
                'token': token,
                'is_valid': True,
                'activation': activation,
                'band': band,
                'token_type': activation.token_type,
                'errors': errors,
                'form_username': username,
            })

        # 3. Criação atômica do User, Membership e liquidação do Token de Ativação
        with transaction.atomic():
            act = BandActivationToken.objects.select_for_update().get(pk=activation.pk)

            if act.used_at is not None:
                return render(request, self.template_name, {
                    'token': token,
                    'is_valid': False,
                    'error_code': 'TOKEN_JA_UTILIZADO',
                    'activation': activation,
                    'band': band,
                })

            if timezone.now() > act.expires_at:
                return render(request, self.template_name, {
                    'token': token,
                    'is_valid': False,
                    'error_code': 'TOKEN_EXPIRADO',
                    'activation': activation,
                    'band': band,
                })

            # Lock e verificação explícita do SignupOrder
            signup_order = None
            if act.signup_order_id:
                signup_order = SignupOrder.objects.select_for_update().get(pk=act.signup_order_id)
                if signup_order.activated_user:
                    act.used_at = timezone.now()
                    act.save(update_fields=['used_at'])
                    return render(request, self.template_name, {
                        'success': True,
                        'band': band,
                        'username': signup_order.activated_user.username,
                        'login_url': f"/{band.slug}/login/",
                    })

            # Extrair responsible_cpf do pedido para associar ao novo User
            user_cpf = None
            if signup_order and getattr(signup_order, 'responsible_cpf', None):
                raw_cpf = re.sub(r'\D', '', signup_order.responsible_cpf)
                if len(raw_cpf) == 11:
                    user_cpf = raw_cpf

            # Criar User como EMPRESARIO (titular da assinatura) vinculado à Band
            user = User.objects.create_user(
                username=username,
                email=act.email,
                password=password,
                band=band,
                cpf=user_cpf,
                role='EMPRESARIO',
                first_name=act.responsible_name or ''
            )

            # Criar OBRIGATORIAMENTE UserBandMembership para suportar multilogin desde a 1ª banda
            UserBandMembership.objects.get_or_create(
                user=user,
                band=band,
                defaults={'role': 'EMPRESARIO', 'is_active': True}
            )

            # Vincular usuário inicial ao SignupOrder
            if signup_order:
                signup_order.activated_user = user
                signup_order.save(update_fields=['activated_user'])

            # Marcar o token como utilizado
            act.used_at = timezone.now()
            act.save(update_fields=['used_at'])

            logger.info(
                "Conta criada com sucesso via token de ativação para usuario '%s' na banda '%s' (slug=%s)",
                username, band.name, band.slug
            )

        # 4. Renderizar página de sucesso
        return render(request, self.template_name, {
            'success': True,
            'band': band,
            'username': username,
            'login_url': f"/{band.slug}/login/",
        })
