import uuid
import logging
from decimal import Decimal
from django.shortcuts import render, redirect
from django.views import View
from django.http import HttpResponseRedirect
from django.db import transaction
from core.models import SignupOrder, SystemSettings
from core.forms_checkout import SignupOrderForm
from core.services.payments.checkout import create_asaas_checkout_for_signup_order
from core.services.payments.asaas.client import AsaasClient

logger = logging.getLogger(__name__)


def normalize_plan_and_cycle(raw_plan: str, raw_cycle: str):
    """
    Normaliza os parâmetros de plano e ciclo de forma tolerante.
    """
    p = (raw_plan or '').strip().upper()
    c = (raw_cycle or '').strip().upper()

    if 'BASIC' in p or 'BÁSIC' in p:
        plan = 'BASICO'
    else:
        plan = 'AVANCADO'

    if 'ANUAL' in c or 'YEAR' in c:
        cycle = 'ANUAL'
    else:
        cycle = 'MENSAL'

    return plan, cycle


class CheckoutView(View):
    template_name = 'core/checkout.html'

    def get(self, request):
        raw_plan = request.GET.get('plano') or request.GET.get('plan') or 'AVANCADO'
        raw_cycle = request.GET.get('ciclo') or request.GET.get('cycle') or 'MENSAL'

        plan_type, billing_cycle = normalize_plan_and_cycle(raw_plan, raw_cycle)

        # Preço canônico calculado pelo backend - nunca confiado no frontend
        canonical_price = SystemSettings.get_canonical_plan_price(plan_type, billing_cycle)

        initial_token = f"bp-ord-{uuid.uuid4().hex[:14]}"
        form = SignupOrderForm(initial={
            'plan_type': plan_type,
            'billing_cycle': billing_cycle,
            'idempotency_token': initial_token,
        })

        context = {
            'form': form,
            'plan_type': plan_type,
            'billing_cycle': billing_cycle,
            'amount': canonical_price,
            'is_annual': (billing_cycle == 'ANUAL'),
            'plan_display': 'Avançado' if plan_type == 'AVANCADO' else 'Básico',
            'cycle_display': 'Anual' if billing_cycle == 'ANUAL' else 'Mensal',
        }
        return render(request, self.template_name, context)

    def post(self, request):
        form = SignupOrderForm(request.POST)

        raw_plan = request.POST.get('plan_type') or request.GET.get('plano') or 'AVANCADO'
        raw_cycle = request.POST.get('billing_cycle') or request.GET.get('ciclo') or 'MENSAL'
        plan_type, billing_cycle = normalize_plan_and_cycle(raw_plan, raw_cycle)

        # Preço canônico rigorosamente determinado pelo backend
        canonical_price = SystemSettings.get_canonical_plan_price(plan_type, billing_cycle)

        if not form.is_valid():
            context = {
                'form': form,
                'plan_type': plan_type,
                'billing_cycle': billing_cycle,
                'amount': canonical_price,
                'is_annual': (billing_cycle == 'ANUAL'),
                'plan_display': 'Avançado' if plan_type == 'AVANCADO' else 'Básico',
                'cycle_display': 'Anual' if billing_cycle == 'ANUAL' else 'Mensal',
                'errors': form.errors,
            }
            return render(request, self.template_name, context)

        # Dados validados
        cd = form.cleaned_data
        band_name = cd['band_name']
        responsible_name = cd['responsible_name']
        email = cd['email']
        phone = cd.get('phone') or ''
        cpf_cnpj = cd.get('cpf_cnpj') or ''
        postal_code = cd.get('postal_code') or ''
        address = cd.get('address') or ''
        address_number = cd.get('address_number') or ''
        complement = cd.get('complement') or ''
        province = cd.get('province') or ''
        city = cd.get('city') or ''
        state = cd.get('state') or ''
        idempotency_token = (cd.get('idempotency_token') or '').strip()

        # Se o formulário possuir token de idempotência válido, reaproveita-o; senão gera novo determinístico
        if idempotency_token and idempotency_token.startswith('bp-ord-'):
            ext_ref = idempotency_token[:64]
        else:
            ext_ref = f"bp-ord-{uuid.uuid4().hex[:14]}"

        # Proteção estrita de concorrência e idempotência contra duplo-clique / repost
        with transaction.atomic():
            signup_order, created = SignupOrder.objects.get_or_create(
                external_reference=ext_ref,
                defaults={
                    'gateway_provider': 'ASAAS',
                    'band_name': band_name,
                    'responsible_name': responsible_name,
                    'email': email,
                    'phone': phone,
                    'cpf_cnpj': cpf_cnpj,
                    'postal_code': postal_code,
                    'address': address,
                    'address_number': address_number,
                    'complement': complement,
                    'province': province,
                    'city': city,
                    'state': state,
                    'plan_type': plan_type,
                    'billing_cycle': billing_cycle,
                    'amount': canonical_price,
                    'status': 'PENDENTE',
                }
            )

        if created:
            logger.info(
                "SignupOrder %s criado com sucesso para banda '%s' (Plano: %s %s, R$ %.2f)",
                ext_ref, band_name, plan_type, billing_cycle, canonical_price
            )
        else:
            logger.info(
                "SignupOrder %s já existia (repost/duplo clique detectado). Reutilizando pedido existente.",
                ext_ref
            )

        # Se a ordem já foi paga anteriormente
        if signup_order.status == 'PAGO':
            context = {
                'form': form,
                'plan_type': plan_type,
                'billing_cycle': billing_cycle,
                'amount': canonical_price,
                'is_annual': (billing_cycle == 'ANUAL'),
                'plan_display': 'Avançado' if plan_type == 'AVANCADO' else 'Básico',
                'cycle_display': 'Anual' if billing_cycle == 'ANUAL' else 'Mensal',
                'gateway_error': "Este pedido já foi aprovado e a conta foi ativada. Verifique seu e-mail.",
            }
            return render(request, self.template_name, context)

        # Inicia sessão de checkout no Asaas ou recupera link existente
        payment_method = cd.get('payment_method', 'CREDIT_CARD')
        success, checkout_url, res_data, err_msg = create_asaas_checkout_for_signup_order(
            signup_order,
            payment_method=payment_method
        )

        if not success or not checkout_url:
            logger.error("Falha ao gerar link de pagamento para SignupOrder %s: %s", ext_ref, err_msg)
            context = {
                'form': form,
                'plan_type': plan_type,
                'billing_cycle': billing_cycle,
                'amount': canonical_price,
                'is_annual': (billing_cycle == 'ANUAL'),
                'plan_display': 'Avançado' if plan_type == 'AVANCADO' else 'Básico',
                'cycle_display': 'Anual' if billing_cycle == 'ANUAL' else 'Mensal',
                'gateway_error': err_msg or "Não foi possível gerar a página segura de pagamento no momento. Tente novamente em alguns instantes.",
            }
            return render(request, self.template_name, context)

        # Redireciona com sucesso para a URL segura de pagamento do Asaas
        return HttpResponseRedirect(checkout_url)

