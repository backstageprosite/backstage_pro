import os
import uuid
import json
import logging
import urllib.request
import urllib.error
from decimal import Decimal
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.utils import timezone
from core.models import SignupOrder
from core.services.payments.base import AsaasConfig
from core.services.payments.asaas.client import AsaasClient

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Cria Checkout Recorrente no Asaas Sandbox para novo pedido ou para SignupOrder existente (--order-id).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--order-id',
            type=int,
            help='ID do SignupOrder existente para retentativa de criacao de Checkout no Sandbox.'
        )

    def handle(self, *args, **options):
        # 1. Trava estrita de seguranca: Executar exclusivamente em staging + sandbox
        django_env = getattr(settings, 'DJANGO_ENV', '').strip().lower()
        config = AsaasConfig.from_settings()

        if django_env != 'staging' or config.environment != 'sandbox':
            raise CommandError(
                'Este comando so pode ser executado no ambiente de homologacao com Asaas Sandbox.'
            )

        if not config.is_configured():
            raise CommandError('ASAAS_API_KEY nao configurada no ambiente de homologacao.')

        customer_id = 'cus_000009006807'
        order_id = options.get('order_id')

        # 2. Carregar pedido existente ou criar novo pedido
        if order_id:
            order = SignupOrder.objects.filter(pk=order_id).first()
            if not order:
                raise CommandError(f'SignupOrder ID {order_id} nao encontrado no banco da homologacao.')

            if order.gateway_checkout_id:
                raise CommandError('Este SignupOrder ja possui Checkout Asaas vinculado.')

            if order.status != 'PENDENTE':
                raise CommandError(f'SignupOrder ID {order_id} possui status {order.status} (esperado: PENDENTE).')

            if order.gateway_provider != 'ASAAS':
                raise CommandError(f'SignupOrder ID {order_id} possui gateway_provider {order.gateway_provider} (esperado: ASAAS).')

            if order.gateway_customer_id != customer_id:
                raise CommandError(f'SignupOrder ID {order_id} associado ao customer {order.gateway_customer_id} (esperado: {customer_id}).')

            self.stdout.write(self.style.NOTICE(f'Reutilizando SignupOrder existente (ID: {order.id}, Ref: {order.external_reference}).'))
        else:
            ext_ref = f'bp-homolog-{uuid.uuid4().hex[:12]}'
            order = SignupOrder.objects.create(
                band_name='Banda Teste Homologacao',
                responsible_name='Cliente Teste Sandbox',
                email='backstagepro-sandbox@example.com',
                cpf_cnpj='24.587.214/0001-44',
                phone='71999887766',
                plan_type='BASICO',
                billing_cycle='MENSAL',
                amount=Decimal('19.90'),
                status='PENDENTE',
                gateway_provider='ASAAS',
                gateway_customer_id=customer_id,
                external_reference=ext_ref
            )
            self.stdout.write(self.style.SUCCESS(f'Novo SignupOrder criado com sucesso (ID: {order.id}, Ref: {ext_ref}).'))

        # 3. Gerar data/hora dinamicamente para nextDueDate (formato: YYYY-MM-DD HH:MM:SS)
        now_dt = timezone.localtime(timezone.now())
        next_due_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')

        # 4. Montar payload do Checkout Sandbox com UTF-8 estrito
        homolog_url = 'https://backstage-pro-web-homologacao.up.railway.app/'
        checkout_payload = {
            'customer': customer_id,
            'billingTypes': ['CREDIT_CARD'],
            'chargeTypes': ['RECURRENT'],
            'minutesToExpire': 60,
            'externalReference': order.external_reference,
            'items': [
                {
                    'name': 'Backstage Pro Básico',
                    'description': 'Assinatura mensal Backstage Pro - Sandbox',
                    'quantity': 1,
                    'value': 19.90
                }
            ],
            'subscription': {
                'cycle': 'MONTHLY',
                'nextDueDate': next_due_str
            },
            'callback': {
                'successUrl': homolog_url,
                'cancelUrl': homolog_url,
                'expiredUrl': homolog_url
            }
        }

        client = AsaasClient(config=config)
        endpoint_url = f'{client.base_url}/checkouts'
        headers = client.get_headers()
        body_bytes = client.encode_payload(checkout_payload)

        req = urllib.request.Request(
            endpoint_url,
            data=body_bytes,
            headers=headers,
            method='POST'
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                res_data = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', errors='ignore')
            logger.error('Erro HTTP ao criar Checkout Asaas: %s - %s', e.code, err_body)
            raise CommandError(f'Falha na chamada Asaas Checkout (HTTP {e.code}): {err_body}')
        except Exception as e:
            logger.exception('Erro ao conectar na API Asaas: %s', str(e))
            raise CommandError(f'Falha de conexao com Asaas: {str(e)}')

        checkout_id = res_data.get('id')
        checkout_status = res_data.get('status', 'ACTIVE')
        checkout_link = res_data.get('paymentLink') or res_data.get('url') or res_data.get('link') or res_data.get('checkoutUrl')

        # 5. Salvar gateway_checkout_id no SignupOrder
        order.gateway_checkout_id = checkout_id
        order.save(update_fields=['gateway_checkout_id'])

        # 6. Saida sanitizada e segura
        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS('=================================================='))
        self.stdout.write(self.style.SUCCESS('CHECKOUT SANDBOX CRIADO COM SUCESSO'))
        self.stdout.write(self.style.SUCCESS('=================================================='))
        self.stdout.write(f'AMBIENTE: homologacao')
        self.stdout.write(f'ASAAS: sandbox')
        self.stdout.write(f'SignupOrder ID: {order.id}')
        self.stdout.write(f'external_reference: {order.external_reference}')
        self.stdout.write(f'checkout.id: {checkout_id}')
        self.stdout.write(f'checkout.status: {checkout_status}')
        if checkout_link:
            self.stdout.write(f'checkout.link: {checkout_link}')
        self.stdout.write(f'valor: R$ 19,90')
        self.stdout.write(f'plano: Basico')
        self.stdout.write(f'ciclo: Mensal')
        self.stdout.write(f'nextDueDate: {next_due_str}')
        self.stdout.write(self.style.SUCCESS('=================================================='))
