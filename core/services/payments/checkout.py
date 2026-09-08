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
      installment: {'maxInstallmentCount': 5}
      O cliente pode pagar à vista via PIX ou em 1x até 5x no cartão sem juros.
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
        if method == 'PIX':
            # BP-PEND-28: Anual + PIX é exclusivamente à vista (DETACHED sem installment)
            payload: Dict[str, Any] = {
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
            # Anual com Cartão (ou ambos quando não especificado): parcelamento em até 5x
            billing_types = ['CREDIT_CARD'] if method == 'CREDIT_CARD' else ['PIX', 'CREDIT_CARD']
            payload = {
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
                    'maxInstallmentCount': 5
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

    # BP-PEND-26 / BP-PEND-27: Utilizar 'customer': '<cus_id>' e NUNCA enviar 'customerData'.
    # O Asaas rejeita checkouts com 'customerData' quando dados de endereço não são fornecidos.
    if signup_order.gateway_customer_id:
        payload['customer'] = signup_order.gateway_customer_id

    return payload


def get_or_create_asaas_customer_for_signup_order(
    signup_order: SignupOrder,
    client: AsaasClient
) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Garante a existência de um Customer completo (identificação + endereço) no Asaas
    antes da criação do Checkout hospedado.
    
    Estratégia de Idempotência e Reconciliação:
    1. Se PAYMENTS_LIVE_ENABLED=False (modo mock/desabilitado), bloqueia requisições externas.
    2. Constrói o payload com dados cadastrais e endereço completo:
       - name, cpfCnpj, email, mobilePhone
       - postalCode, address, addressNumber, complement, province, city, state
       - externalReference determinístico
    3. Se signup_order.gateway_customer_id já estiver preenchido localmente:
       - Consulta o customer no Asaas via GET /v3/customers/{id}
       - Se os dados de endereço estiverem ausentes ou divergentes, atualiza via PUT /v3/customers/{id}
       - Reutiliza o mesmo Customer, evitando duplicidades.
    4. Se gateway_customer_id não estiver preenchido:
       - Consulta GET /v3/customers?externalReference={ref} para verificar se já existe remotamente.
       - Se existir, atualiza via PUT /v3/customers/{id} se necessário e salva o ID na ordem.
       - Se não existir, executa POST /v3/customers com os dados completos.
    5. Em caso de timeout/erro de rede durante o POST, faz reconciliação por externalReference.
    
    Retorna (sucesso: bool, customer_id: Optional[str], erro: Optional[str]).
    """
    import re

    # Se PAYMENTS_LIVE_ENABLED=False (modo mock/desabilitado), não fazer chamadas de rede externas
    if not client.config.live_payments_enabled:
        logger.warning(
            "Operação Asaas 'create_customer' bloqueada pelo safety gate (PAYMENTS_LIVE_ENABLED=False)."
        )
        return False, None, "Operação financeira externa 'create_customer' está desabilitada (PAYMENTS_LIVE_ENABLED=False)."

    # Normalizações
    norm_cpf_cnpj = re.sub(r'\D', '', signup_order.cpf_cnpj or '')
    norm_phone = re.sub(r'\D', '', signup_order.phone or '')
    if len(norm_phone) in (12, 13) and norm_phone.startswith('55'):
        norm_phone = norm_phone[2:]
    norm_cep = re.sub(r'\D', '', signup_order.postal_code or '')

    customer_ext_ref = f"bp-cust-{signup_order.external_reference}"[:64]

    customer_payload: Dict[str, Any] = {
        'name': signup_order.responsible_name,
        'email': signup_order.email,
        'externalReference': customer_ext_ref,
        'notificationDisabled': True,
    }
    if norm_cpf_cnpj:
        customer_payload['cpfCnpj'] = norm_cpf_cnpj
    if norm_phone:
        customer_payload['mobilePhone'] = norm_phone
    if norm_cep:
        customer_payload['postalCode'] = norm_cep
    if signup_order.address:
        customer_payload['address'] = signup_order.address
    if signup_order.address_number:
        customer_payload['addressNumber'] = signup_order.address_number
    if signup_order.complement:
        customer_payload['complement'] = signup_order.complement
    if signup_order.province:
        customer_payload['province'] = signup_order.province
    if signup_order.city:
        customer_payload['city'] = signup_order.city
    if signup_order.state:
        customer_payload['state'] = signup_order.state.upper()

    def _sync_customer_address_if_needed(cust_id: str, existing_cust_data: Optional[Dict[str, Any]] = None) -> bool:
        """Atualiza o Customer no Asaas se dados essenciais de endereço ou notificação estiverem faltando."""
        data = existing_cust_data or client.get_customer(cust_id)
        if not data:
            return True

        # Checa se os campos de endereço já estão preenchidos de forma compatível
        needs_update = False
        check_fields = [
            ('postalCode', norm_cep),
            ('address', signup_order.address),
            ('addressNumber', signup_order.address_number),
            ('province', signup_order.province),
            ('city', signup_order.city),
            ('state', (signup_order.state or '').upper()),
        ]
        for field_name, local_val in check_fields:
            if local_val and str(data.get(field_name) or '').strip() != str(local_val).strip():
                needs_update = True
                break

        # BP-PEND-36: Garantir que as notificações do Asaas estejam desativadas no customer
        if data.get('notificationDisabled') is not True:
            needs_update = True

        if needs_update:
            logger.info("Atualizando dados cadastrais/endereço do Customer Asaas %s...", cust_id)
            upd_res = client.update_customer(cust_id, customer_payload)
            if isinstance(upd_res, tuple) and len(upd_res) == 2:
                upd_ok, upd_data = upd_res
            else:
                upd_ok, upd_data = bool(upd_res), upd_res
            if not upd_ok:
                logger.warning("Falha ao atualizar dados do customer %s: %s", cust_id, upd_data)
                return False
        return True

    # Caso A: Customer já persistido localmente no SignupOrder
    if signup_order.gateway_customer_id:
        cus_id = signup_order.gateway_customer_id
        _sync_customer_address_if_needed(cus_id)
        return True, cus_id, None

    # Caso B: Verificar se já existe remotamente via externalReference
    try:
        existing_customers = client.get_customers_by_external_reference(customer_ext_ref)
        if existing_customers and isinstance(existing_customers, list) and len(existing_customers) > 0:
            cus_id = existing_customers[0].get('id')
            if cus_id:
                signup_order.gateway_customer_id = cus_id
                signup_order.save(update_fields=['gateway_customer_id', 'updated_at'])
                logger.info("Customer Asaas existente %s reutilizado via externalReference %s", cus_id, customer_ext_ref)
                _sync_customer_address_if_needed(cus_id, existing_customers[0])
                return True, cus_id, None
    except Exception as e:
        logger.warning("Falha ao consultar customer por externalReference %s no Asaas: %s", customer_ext_ref, str(e))

    # Caso C: Criar customer via POST /v3/customers
    try:
        success, res_data = client.create_customer(customer_payload)
    except Exception as exc:
        logger.warning(
            "Exceção ao criar customer para ordem %s: %s. Tentando reconciliação via externalReference.",
            signup_order.external_reference, str(exc)
        )
        # Reconciliação em caso de timeout de rede
        try:
            recon_customers = client.get_customers_by_external_reference(customer_ext_ref)
            if recon_customers and isinstance(recon_customers, list) and len(recon_customers) > 0:
                cus_id = recon_customers[0].get('id')
                if cus_id:
                    signup_order.gateway_customer_id = cus_id
                    signup_order.save(update_fields=['gateway_customer_id', 'updated_at'])
                    logger.info("Customer Asaas %s recuperado após timeout via externalReference %s", cus_id, customer_ext_ref)
                    _sync_customer_address_if_needed(cus_id, recon_customers[0])
                    return True, cus_id, None
        except Exception as recon_exc:
            logger.warning("Falha na reconciliação pós-timeout do customer %s: %s", customer_ext_ref, str(recon_exc))

        return False, None, f"Erro de comunicação ao criar customer: {exc}"

    if not success:
        err_msg = res_data.get('message') or res_data.get('error') or "Falha ao criar cliente no gateway."
        logger.error("Falha retornada pelo AsaasClient ao criar Customer: %s", res_data)
        return False, None, str(err_msg)

    cus_id = res_data.get('id')
    if not cus_id:
        return False, None, "Resposta do Asaas não conteve ID do cliente."

    signup_order.gateway_customer_id = cus_id
    signup_order.save(update_fields=['gateway_customer_id', 'updated_at'])
    logger.info("Customer Asaas criado com sucesso: %s para ordem %s", cus_id, signup_order.external_reference)
    return True, cus_id, None


def create_asaas_checkout_for_signup_order(
    signup_order: SignupOrder,
    client: Optional[AsaasClient] = None,
    payment_method: Optional[str] = None
) -> Tuple[bool, Optional[str], Optional[Dict[str, Any]], Optional[str]]:
    """
    Cria uma sessão de Checkout no Asaas reutilizando exclusivamente o método canônico AsaasClient.create_checkout().
    Possui proteção de idempotência remota contra time-out de rede / retentativas.
    
    Garante antes a existência/criação do Customer no Asaas (BP-PEND-26/27) para vincular
    o Checkout ao cliente sem exigir dados de endereço no formulário local.
    
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

    # BP-PEND-26 / BP-PEND-27: Garantir que o Customer Asaas exista antes de construir o checkout
    cust_ok, cust_id, cust_err = get_or_create_asaas_customer_for_signup_order(signup_order, client)
    if not cust_ok:
        logger.error("Falha ao resolver customer Asaas para ordem %s: %s", signup_order.external_reference, cust_err)
        return False, None, {"error": "customer_creation_failed", "message": cust_err}, cust_err

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

