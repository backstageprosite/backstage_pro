import logging
from typing import Dict, Any, Optional
from django.db import transaction
from core.models import BandSubscription, GatewayPaymentMethod

logger = logging.getLogger(__name__)


def extract_card_metadata_from_webhook(payload: Dict[str, Any]) -> Dict[str, Optional[str]]:
    result = {
        'credit_card_token': None,
        'card_brand': None,
        'card_last4': None,
    }

    if not isinstance(payload, dict):
        return result

    payment_data = payload.get('payment') if isinstance(payload.get('payment'), dict) else payload

    cc_data = payment_data.get('creditCard')
    if not isinstance(cc_data, dict):
        cc_data = {}

    token = (
        payment_data.get('creditCardToken')
        or cc_data.get('creditCardToken')
        or cc_data.get('token')
    )
    if token and isinstance(token, str) and token.strip():
        result['credit_card_token'] = token.strip()

    brand = (
        payment_data.get('creditCardBrand')
        or cc_data.get('creditCardBrand')
        or cc_data.get('brand')
    )
    if brand and isinstance(brand, str) and brand.strip():
        result['card_brand'] = brand.strip()

    raw_num = (
        cc_data.get('creditCardNumber')
        or cc_data.get('cardNumber')
        or cc_data.get('last4')
        or payment_data.get('creditCardNumber')
    )
    if raw_num is not None:
        raw_str = str(raw_num).strip()
        if raw_str:
            result['card_last4'] = raw_str[-4:] if len(raw_str) >= 4 else raw_str

    return result


def replace_active_gateway_payment_method(
    subscription: BandSubscription,
    credit_card_token: str,
    card_brand: Optional[str] = None,
    card_last4: Optional[str] = None,
    expiration_month: Optional[str] = None,
    expiration_year: Optional[str] = None,
    gateway_customer_id: Optional[str] = None,
    provider: str = 'ASAAS'
) -> GatewayPaymentMethod:
    if not subscription or not getattr(subscription, 'id', None):
        raise ValueError("subscription_invalida: Assinatura obrigatoria para registrar metodo de pagamento.")

    if not credit_card_token or not isinstance(credit_card_token, str) or not credit_card_token.strip():
        raise ValueError("credit_card_token_invalido: Token de cartao obrigatorio.")

    plain_token = credit_card_token.strip()
    provider_norm = (provider or 'ASAAS').strip().upper()

    normalized_last4 = None
    if card_last4:
        last4_str = str(card_last4).strip()
        normalized_last4 = last4_str[-4:] if len(last4_str) >= 4 else last4_str

    normalized_month = str(expiration_month).strip() if expiration_month else None
    normalized_year = str(expiration_year).strip() if expiration_year else None
    normalized_brand = str(card_brand).strip() if card_brand else None

    with transaction.atomic():
        sub_locked = BandSubscription.objects.select_for_update().get(id=subscription.id)

        customer_id = (
            gateway_customer_id
            or sub_locked.gateway_customer_id
            or ''
        ).strip()

        active_pm = GatewayPaymentMethod.objects.filter(
            subscription=sub_locked,
            gateway_provider=provider_norm,
            is_active=True
        ).first()

        if active_pm and active_pm.encrypted_token:
            try:
                active_token = active_pm.get_decrypted_token()
                if active_token == plain_token:
                    logger.info(
                        'Metodo de pagamento ativo ja possui o mesmo token para a assinatura %s. Idempotencia garantida.',
                        sub_locked.id
                    )
                    updated_fields = []
                    if normalized_brand and active_pm.card_brand != normalized_brand:
                        active_pm.card_brand = normalized_brand
                        updated_fields.append('card_brand')
                    if normalized_last4 and active_pm.card_last4 != normalized_last4:
                        active_pm.card_last4 = normalized_last4
                        updated_fields.append('card_last4')
                    if normalized_month and active_pm.expiration_month != normalized_month:
                        active_pm.expiration_month = normalized_month
                        updated_fields.append('expiration_month')
                    if normalized_year and active_pm.expiration_year != normalized_year:
                        active_pm.expiration_year = normalized_year
                        updated_fields.append('expiration_year')
                    if customer_id and active_pm.gateway_customer_id != customer_id:
                        active_pm.gateway_customer_id = customer_id
                        updated_fields.append('gateway_customer_id')

                    if updated_fields:
                        active_pm.save(update_fields=updated_fields + ['updated_at'])
                    return active_pm
            except Exception as e:
                logger.warning(
                    'Falha ao validar token do metodo ativo para idempotencia (sub=%s): %s',
                    sub_locked.id, str(e)
                )

        GatewayPaymentMethod.objects.filter(
            subscription=sub_locked,
            gateway_provider=provider_norm,
            is_active=True
        ).update(is_active=False)

        new_pm = GatewayPaymentMethod(
            subscription=sub_locked,
            gateway_provider=provider_norm,
            gateway_customer_id=customer_id,
            card_brand=normalized_brand,
            card_last4=normalized_last4,
            expiration_month=normalized_month,
            expiration_year=normalized_year,
            is_active=True
        )
        new_pm.set_token(plain_token)
        new_pm.save()

        logger.info(
            'Novo GatewayPaymentMethod %s criado com sucesso para a subscription %s (provider=%s).',
            new_pm.id, sub_locked.id, provider_norm
        )
        return new_pm
