import logging
from decimal import Decimal
from typing import Dict, Any, Tuple, Optional
from django.utils import timezone
from core.models import SignupOrder
from core.services.payments.asaas.client import AsaasClient
from core.services.email_service import get_canonical_base_url

logger = logging.getLogger(__name__)


def build_checkout_payload(
    signup_order: SignupOrder,
    base_site_url: str,
    payment_method: Optional[str] = None
) -> Dict[str, Any]:
    """
    Constrói rigorosamente o payload de checkout compatível com Asaas para PIX + Cartão de Crédito.
    
    Regras comerciais e suporte técnico Asaas:
    - MENSAL COM CARTÃO (R$ 19,90 / R$ 49,90):
      billingTypes: ['CREDIT_CARD']
      chargeTypes: ['RECURRENT']
      subscription: {'cycle': 'MONTHLY', 'nextDueDate': ...}
      
    - MENSAL COM PIX (R$ 19,90 / R$ 49,90):
      billingTypes: ['PIX']
      chargeTypes: ['DETACHED']
      Emite a cobrança avulsa do primeiro ciclo com QR Code / Copia e Cola. Ao ser quitada,
      provisiona a BandSubscription com auto_renew=False e preference='PIX'.
      Os ciclos subsequentes são gerados automaticamente pelo check_subscription_due_dates
      7 dias antes do vencimento com tolerância de 4 dias.
      
    - ANUAL COM CARTÃO / PIX (R$ 199,90 / R$ 499,90):
      billingTypes: ['PIX', 'CREDIT_CARD'] (ou filtrado por payment_method)
      chargeTypes: ['DETACHED', 'INSTALLMENT']
      installment: {'maxInstallmentCount': 12}
      O cliente pode pagar à vista via PIX ou em 1x até 12x no cartão.
    """
    plan_label = 'Avançado' if signup_order.plan_type == 'AVANCADO' else 'Básico'
    is_annual = (signup_order.billing_cycle == 'ANUAL')

    # Determina o método escolhido
    method = (payment_method or '').strip().upper() if payment_method else None

    callback_urls = {
        'successUrl': f"{base_site_url}/",
        'cancelUrl': f"{base_site_url}/",
        'expiredUrl': f"{base_site_url}/"
    }

    item_name = f"Backstage Pro {plan_label}"

    if is_annual:
        item_desc = "Assinatura anual Backstage Pro (vigência de 12 meses)"
        billing_types = ['PIX'] if method == 'PIX' else (['CREDIT_CARD'] if method == 'CREDIT_CARD' else ['PIX', 'CREDIT_CARD'])
        payload: Dict[str, Any] = {
            'billingTypes': billing_types,
            'chargeTypes': ['DETACHED', 'INSTALLMENT'],
            'minutesToExpire': 60,
            'externalReference': signup_order.external_reference,
            'items': [
                {
                    'name': item_name,
                    'description': item_desc,
                    'quantity': 1,
                    'value': float(signup_order.amount)
                }
            ],
            'installment': {
                'maxInstallmentCount': 12
            },
            'callback': callback_urls
        }
    else:
        # Mensal
        if method == 'PIX':
            item_desc = "Assinatura mensal Backstage Pro (Ciclo inicial via PIX)"
            payload = {
                'billingTypes': ['PIX'],
                'chargeTypes': ['DETACHED'],
                'minutesToExpire': 60,
                'externalReference': signup_order.external_reference,
                'items': [
                    {
                        'name': item_name,
                        'description': item_desc,
                        'quantity': 1,
                        'value': float(signup_order.amount)
                    }
                ],
                'callback': callback_urls
            }
        else:
            item_desc = "Assinatura mensal Backstage Pro"
            now_dt = timezone.localtime(timezone.now())
            next_due_str = now_dt.strftime('%Y-%m-%d %H:%M:%S')
            payload = {
                'billingTypes': ['CREDIT_CARD'],
                'chargeTypes': ['RECURRENT'],
                'minutesToExpire': 60,
                'externalReference': signup_order.external_reference,
                'items': [
                    {
                        'name': item_name,
                        'description': item_desc,
                        'quantity': 1,
                        'value': float(signup_order.amount)
                    }
                ],
                'subscription': {
                    'cycle': 'MONTHLY',
                    'nextDueDate': next_due_str
                },
                'callback': callback_urls
            }

    # BP-PEND-26: Pré-preencher identificação no checkout hospedado do Asaas via customerData
    # Não enviar customer e customerData simultaneamente.
    # O cliente/comprador é o responsável/produtor (não o nome da banda).
    import re
    norm_cpf_cnpj = re.sub(r'\D', '', signup_order.cpf_cnpj or '')
    norm_phone = re.sub(r'\D', '', signup_order.phone or '')
    if len(norm_phone) in (12, 13) and norm_phone.startswith('55'):
        norm_phone = norm_phone[2:]

    customer_data = {
        'name': signup_order.responsible_name,
        'email': signup_order.email,
    }
    if norm_cpf_cnpj:
        customer_data['cpfCnpj'] = norm_cpf_cnpj
    if norm_phone:
        customer_data['phone'] = norm_phone

    payload['customerData'] = customer_data

    # Se já existir customer cadastrado e não houver customerData (ou conforme regra estrita:
    # "NÃO enviar customer junto com customerData"):
    # payload['customer'] NÃO é enviado quando customerData é fornecido.
    if signup_order.gateway_customer_id and 'customerData' not in payload:
        payload['customer'] = signup_order.gateway_customer_id

    return payload


def create_asaas_checkout_for_signup_order(
    signup_order: SignupOrder,
    client: Optional[AsaasClient] = None,
    payment_method: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """
    Cria uma sessão de Checkout no Asaas reutilizando exclusivamente o método canônico AsaasClient.create_checkout().
    Possui proteção de idempotência remota contra time-out de rede / retentativas.
    
    Retorna uma tupla:
        (sucesso: bool, checkout_url: Optional[str], resposta_asaas: Optional[dict], erro: Optional[str])
    """
    if not signup_order:
        return False, None, None, "signup_order_obrigatorio"

    if signup_order.status != 'PENDENTE':
        return False, None, None, f"Status inválido para checkout: {signup_order.status}"

    client = client or AsaasClient()
    config = client.config

    if not config.is_configured():
        return False, None, None, "Gateway de pagamento não configurado."

    # Idempotência Nível 1.5: Se o checkout remoto já existe para esta ordem, recupera e reutiliza
    if signup_order.gateway_checkout_id:
        try:
            payments = client.get_payments_by_checkout(signup_order.gateway_checkout_id)
            if payments:
                invoice_url = payments[0].get('invoiceUrl') or payments[0].get('bankSlipUrl')
                if invoice_url:
                    return True, invoice_url, {'id': signup_order.gateway_checkout_id, 'paymentLink': invoice_url}, None
        except Exception as e:
            logger.warning("Falha ao reconciliar checkout existente %s: %s", signup_order.gateway_checkout_id, str(e))

    base_site_url = get_canonical_base_url().rstrip('/')
    checkout_payload = build_checkout_payload(signup_order, base_site_url, payment_method=payment_method)

    # Chamada delegada 100% ao AsaasClient canônico
    try:
        success, res_data = client.create_checkout(checkout_payload)
    except Exception as exc:
        # Se ocorreu exceção de conexão/timeout de rede após o envio
        logger.warning(
            "Exceção de rede durante criação de checkout para ordem %s: %s. Tentando reconciliação.",
            signup_order.external_reference, str(exc)
        )
        success = False
        res_data = {"error": "network_exception", "message": str(exc)}

    if not success:
        err_msg = res_data.get('message') or res_data.get('error') or "Falha ao criar checkout no gateway."
        logger.error("Falha retornada pelo AsaasClient ao criar Checkout: %s", res_data)
        return False, None, res_data, str(err_msg)

    checkout_id = res_data.get('id')
    checkout_url = (
        res_data.get('paymentLink')
        or res_data.get('url')
        or res_data.get('link')
        or res_data.get('checkoutUrl')
    )

    if checkout_id:
        signup_order.gateway_checkout_id = checkout_id
        update_fields = ['gateway_checkout_id', 'updated_at']
        cust_from_res = res_data.get('customer')
        if cust_from_res and not signup_order.gateway_customer_id:
            signup_order.gateway_customer_id = str(cust_from_res)
            update_fields.append('gateway_customer_id')
        signup_order.save(update_fields=update_fields)

    return True, checkout_url, res_data, None

