from django import template
import hashlib

register = template.Library()

@register.filter
def band_color(band_name):
    if not band_name:
        return "bg-secondary text-white"
        
    colors = [
        "bg-primary bg-opacity-10 text-primary border border-primary border-opacity-25",
        "bg-success bg-opacity-10 text-success border border-success border-opacity-25",
        "bg-danger bg-opacity-10 text-danger border border-danger border-opacity-25",
        "bg-warning bg-opacity-10 text-dark border border-warning border-opacity-25",
        "bg-info bg-opacity-10 text-dark border border-info border-opacity-25",
        "bg-secondary bg-opacity-10 text-secondary border border-secondary border-opacity-25",
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
