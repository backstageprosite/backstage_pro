import logging
from django.shortcuts import render, redirect
from django.views import View
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
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
        }
        return render(request, self.template_name, context)

    def post(self, request, token):
        is_valid, error_code, activation = verify_activation_token(token)

        if not is_valid or not activation:
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
                'errors': errors,
                'form_username': username,
            })

        # 3. Criação atômica do User e liquidação do Token de Ativação
        with transaction.atomic():
            # Revalidação e Lock do activation token
            from core.models import BandActivationToken
            activation = BandActivationToken.objects.select_for_update().get(pk=activation.pk)

            if activation.used_at is not None:
                return render(request, self.template_name, {
                    'token': token,
                    'is_valid': False,
                    'error_code': 'TOKEN_JA_UTILIZADO',
                    'activation': activation,
                    'band': band,
                })

            if timezone.now() > activation.expires_at:
                return render(request, self.template_name, {
                    'token': token,
                    'is_valid': False,
                    'error_code': 'TOKEN_EXPIRADO',
                    'activation': activation,
                    'band': band,
                })

            # Verificar idempotência: se o usuário para este email/banda já foi criado
            existing_user = User.objects.filter(band=band, email__iexact=activation.email, role='PRODUTOR').first()
            if existing_user:
                activation.used_at = timezone.now()
                activation.save(update_fields=['used_at'])
                return render(request, self.template_name, {
                    'success': True,
                    'band': band,
                    'username': existing_user.username,
                    'login_url': f"/{band.slug}/login/",
                })

            # Criar User como PRODUTOR vinculado à Band
            user = User.objects.create_user(
                username=username,
                email=activation.email,
                password=password,
                band=band,
                role='PRODUTOR',
                first_name=activation.responsible_name or ''
            )

            # Marcar o token como utilizado
            activation.used_at = timezone.now()
            activation.save(update_fields=['used_at'])

            logger.info("Conta criada com sucesso via token de ativação para usuario '%s' na banda '%s' (slug=%s)", username, band.name, band.slug)

        # 4. Renderizar página de sucesso
        return render(request, self.template_name, {
            'success': True,
            'band': band,
            'username': username,
            'login_url': f"/{band.slug}/login/",
        })
