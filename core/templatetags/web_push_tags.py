from django import template
from django.utils.dateparse import parse_datetime
from django.utils.timezone import localtime

register = template.Library()

@register.filter
def format_iso_date_br(value):
    if not value:
        return "Nenhum registro"
    try:
        dt = parse_datetime(value)
        if dt:
            dt_local = localtime(dt)
            return dt_local.strftime("%d/%m/%Y às %H:%M")
    except Exception:
        pass
    return value
