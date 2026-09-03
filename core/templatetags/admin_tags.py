from django import template
import hashlib

register = template.Library()

@register.filter
def band_color(band_name):
    if not band_name:
        return "bg-secondary bg-opacity-10 text-dark border border-secondary border-opacity-25"
        
    colors = [
        "bg-primary bg-opacity-10 text-dark border border-primary border-opacity-25",
        "bg-success bg-opacity-10 text-dark border border-success border-opacity-25",
        "bg-danger bg-opacity-10 text-dark border border-danger border-opacity-25",
        "bg-warning bg-opacity-10 text-dark border border-warning border-opacity-25",
        "bg-info bg-opacity-10 text-dark border border-info border-opacity-25",
        "bg-secondary bg-opacity-10 text-dark border border-secondary border-opacity-25",
        "bg-dark bg-opacity-10 text-dark border border-dark border-opacity-25",
    ]
    
    # Hash the string to always get the same color for the same band
    hash_val = int(hashlib.md5(str(band_name).lower().strip().encode('utf-8')).hexdigest(), 16)
    
    return colors[hash_val % len(colors)]

@register.filter
def whatsapp_clean(phone):
    """
    Cleans a phone number for use in WhatsApp API (wa.me).
    Removes all non-digit characters.
    Prepends '55' if it's not already there.
    """
    if not phone:
        return ""
    import re
    cleaned = re.sub(r'\D', '', str(phone))
    if not cleaned:
        return ""
    
    if not cleaned.startswith('55'):
        cleaned = '55' + cleaned
        
    return cleaned


@register.filter
def brl_currency(value):
    """
    Formata um valor numérico no padrão monetário brasileiro: R$ 8.000,00
    Funciona com Decimal, float e int.
    """
    if value is None:
        return ""
    from decimal import Decimal, InvalidOperation
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return "R$ 0,00"
    # Formata com duas casas decimais usando separador de milhar
    formatted = "{:,.2f}".format(d)          # ex: "8,000.00"  (locale C)
    formatted = formatted.replace(",", "X")   # ex: "8X000.00"
    formatted = formatted.replace(".", ",")   # ex: "8X000,00"
    formatted = formatted.replace("X", ".")   # ex: "8.000,00"
    return "R$ " + formatted


@register.filter
def billing_whatsapp_link(record):
    """
    Gera o link wa.me com número limpo e texto pré-formatado de aviso de vencimento do plano.
    """
    if not record or not getattr(record, 'subscription', None):
        return ""

    phone = whatsapp_clean(record.subscription.billing_phone)
    if not phone:
        return ""

    import urllib.parse

    resp = record.subscription.financial_responsible_name or (record.band.name if record.band else "Responsável")
    band_name = record.band.name if record.band else "Banda"
    plan_name = record.plan_name or record.subscription.plan_name or "Plano Backstage Pro"
    period = record.reference_period or ""
    amount_str = f"R$ {record.amount}" if record.amount is not None else ""
    due_str = record.due_date.strftime('%d/%m/%Y') if record.due_date else ""

    msg = (
        f"Olá, {resp}. Tudo bem?\n\n"
        f"Estou passando para lembrar sobre o vencimento da assinatura do Backstage Pro da banda *{band_name}*.\n\n"
        f"📄 *Plano:* {plan_name}\n"
        f"🗓 *Período:* {period}\n"
        f"💰 *Valor:* {amount_str}\n"
        f"📅 *Vencimento:* {due_str}\n\n"
        f"O pagamento pode ser regularizado conforme combinado via Pix/transferência.\n\n"
        f"Qualquer dúvida ou se já efetuou o pagamento, fico à disposição!\n\n"
        f"Atenciosamente,\n"
        f"Equipe Backstage Pro"
    )

    encoded_text = urllib.parse.quote(msg)
    return f"https://wa.me/{phone}?text={encoded_text}"
