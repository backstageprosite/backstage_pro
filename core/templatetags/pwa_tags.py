from django import template
from core.pwa_views import get_band_icon_version, get_short_name

register = template.Library()

@register.simple_tag
def get_pwa_icon_version(band):
    if not band:
        return "fallback"
    token, _ = get_band_icon_version(band)
    return token

@register.simple_tag
def get_pwa_short_name(band):
    if not band:
        return "Backstage Pro"
    return get_short_name(band.name)
