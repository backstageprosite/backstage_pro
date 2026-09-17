from django import template
from core.pwa_views import get_band_icon_version, get_short_name, is_multilogin_user

register = template.Library()

@register.simple_tag(takes_context=True)
def get_pwa_icon_version(context, band):
    request = context.get('request')
    if request and is_multilogin_user(request.user):
        return "white-bg-v2"
    if not band:
        return "fallback"
    token, _ = get_band_icon_version(band)
    return token

@register.simple_tag(takes_context=True)
def get_pwa_short_name(context, band):
    request = context.get('request')
    if request and is_multilogin_user(request.user):
        return "Backstage Pro"
    if not band:
        return "Backstage Pro"
    return get_short_name(band.name)

@register.simple_tag(takes_context=True)
def is_multilogin_pwa(context):
    request = context.get('request')
    if request and is_multilogin_user(request.user):
        return True
    return False
