import logging
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.contrib.auth import get_user_model
from core.models import SignupOrder
from core.services.payments.base import AsaasConfig

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = 'Repara de forma segura o vínculo activated_user no SignupOrder de teste na homologação.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--order-id',
            type=int,
            default=1,
            help='ID do SignupOrder na homologação a ser reparado (padrão: 1).'
        )

    def handle(self, *args, **options):
        # 1. Travas estritas de ambiente: exclusivamente staging + sandbox
        django_env = getattr(settings, 'DJANGO_ENV', '').strip().lower()
        config = AsaasConfig.from_settings()

        if django_env not in ['staging', 'homologacao']:
            raise CommandError('Este comando so pode ser executado no ambiente de homologacao (DJANGO_ENV=staging).')

        if config.environment != 'sandbox':
            raise CommandError('Este comando so pode ser executado no ambiente de homologacao com Asaas Sandbox.')

        order_id = options.get('order_id', 1)
        order = SignupOrder.objects.filter(pk=order_id).first()

        if not order:
            raise CommandError(f'SignupOrder ID {order_id} nao encontrado.')

        band = order.band
        if not band:
            raise CommandError(f'SignupOrder ID {order_id} nao possui Band vinculada.')

        if order.activated_user:
            self.stdout.write(self.style.SUCCESS(
                f'SignupOrder ID {order.id} ja possui activated_user={order.activated_user.username} (ID: {order.activated_user.id}). Nenhuma acao necessaria.'
            ))
            return

        # 2. Localizar de forma inequívoca o usuário do teste
        matching_users = User.objects.filter(band=band, role='PRODUTOR')
        if matching_users.count() == 0:
            raise CommandError(f'Nenhum usuario Produtor encontrado na Band {band.name} (ID: {band.id}).')

        if matching_users.count() > 1:
            # Tentar filtro refinado por email se houver mais de um produtor
            by_email = matching_users.filter(email__iexact=order.email)
            if by_email.count() == 1:
                user_to_bind = by_email.first()
            else:
                raise CommandError(
                    f'Ambiguidade: encontrados {matching_users.count()} usuarios Produtores na Band {band.name}. Operacao abortada para seguranca.'
                )
        else:
            user_to_bind = matching_users.first()

        # 3. Vincular de forma atômica
        order.activated_user = user_to_bind
        order.save(update_fields=['activated_user'])

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=================================================='))
        self.stdout.write(self.style.SUCCESS('REPARO DE ATIVACAO EXECUTADO COM SUCESSO'))
        self.stdout.write(self.style.SUCCESS('=================================================='))
        self.stdout.write(f'SignupOrder ID:   {order.id}')
        self.stdout.write(f'Band:             {band.name} (slug: {band.slug})')
        self.stdout.write(f'Activated User:   {user_to_bind.username} (ID: {user_to_bind.id}, email: {user_to_bind.email})')
        self.stdout.write(self.style.SUCCESS('=================================================='))
