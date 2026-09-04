import logging
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.contrib.auth import get_user_model
from core.models import SignupOrder
from core.services.payments.base import AsaasConfig
from core.services.payments.activation import reissue_activation_token

logger = logging.getLogger(__name__)
User = get_user_model()


class Command(BaseCommand):
    help = 'Gera link seguro de teste para ativação de conta do cliente na homologação.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--order-id',
            type=int,
            default=1,
            help='ID do SignupOrder na homologação para gerar o link de teste (padrão: 1).'
        )

    def handle(self, *args, **options):
        # 1. Travas estritas de ambiente: exclusivamente staging + sandbox
        django_env = getattr(settings, 'DJANGO_ENV', '').strip().lower()
        config = AsaasConfig.from_settings()

        if django_env != 'staging':
            raise CommandError('Este comando so pode ser executado no ambiente de homologacao (DJANGO_ENV=staging).')

        if config.environment != 'sandbox':
            raise CommandError('Este comando so pode ser executado no ambiente de homologacao com Asaas Sandbox.')

        order_id = options.get('order_id', 1)
        order = SignupOrder.objects.filter(pk=order_id).first()

        if not order:
            raise CommandError(f'SignupOrder ID {order_id} nao encontrado.')

        if order.status != 'PAGO':
            raise CommandError(f'SignupOrder ID {order_id} possui status {order.status} (esperado: PAGO).')

        band = order.band
        if not band:
            raise CommandError(f'SignupOrder ID {order_id} nao possui Band vinculada.')

        # 2. Verificar se já existe conta inicial ativada para esta contratação
        if order.activated_user:
            raise CommandError(
                f'O SignupOrder ID {order.id} ja possui uma conta inicial ativada ({order.activated_user.username}).'
            )

        # 3. Emitir novo token de ativação (invalidando anteriores de forma limpa)
        activation, raw_token = reissue_activation_token(
            band=band,
            signup_order=order,
            valid_hours=48
        )

        homolog_domain = 'https://backstage-pro-web-homologacao.up.railway.app'
        activation_url = f'{homolog_domain}/ativar-conta/{raw_token}/'

        # 4. Saída sanitizada contendo o link de teste para homologação
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=================================================='))
        self.stdout.write(self.style.SUCCESS('LINK DE ATIVACAO GERADO COM SUCESSO (HOMOLOGACAO)'))
        self.stdout.write(self.style.SUCCESS('=================================================='))
        self.stdout.write(f'AMBIENTE:            homologacao')
        self.stdout.write(f'ASAAS:               sandbox')
        self.stdout.write(f'SignupOrder ID:      {order.id}')
        self.stdout.write(f'Band ID / Slug:      {band.id} / {band.slug}')
        self.stdout.write(f'Banda:               {band.name}')
        self.stdout.write(f'Responsavel:         {order.responsible_name}')
        self.stdout.write(f'E-mail:              {order.email}')
        self.stdout.write(f'Validade:            48 horas ({activation.expires_at.strftime("%Y-%m-%d %H:%M:%S")})')
        self.stdout.write('')
        self.stdout.write(self.style.WARNING('URL DE ATIVACAO:'))
        self.stdout.write(self.style.SUCCESS(activation_url))
        self.stdout.write('')
        self.stdout.write(self.style.NOTICE('Orientacao: Abra a URL acima no navegador para definir Login e Senha.'))
        self.stdout.write(self.style.SUCCESS('=================================================='))
