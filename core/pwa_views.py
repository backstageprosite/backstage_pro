from django.http import JsonResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.templatetags.static import static
from django.contrib.staticfiles import finders
import hashlib
import os
from core.models import Band
from core.pwa_utils import generate_band_icon

def get_short_name(name):
    """
    Retorna um nome curto (short_name) para a banda.
    Remove espaços extras e limita a um tamanho razoável para evitar
    cortes estranhos na tela do celular, sem quebrar palavras ao meio.
    """
    clean_name = name.strip()
    if not clean_name:
        return "Banda"
    if len(clean_name) <= 20:
        return clean_name
    
    # Corta no último espaço antes de 20 caracteres para preservar a palavra
    truncated = clean_name[:20]
    last_space = truncated.rfind(' ')
    if last_space > 0:
        return truncated[:last_space]
    return truncated

PWA_ICON_STYLE_VERSION = "white-bg-v2"

def get_band_icon_version(band):
    """
    Gera um hash curto e seguro baseado nos metadados do arquivo da logo.
    Retorna uma tupla (token_string, is_reliable), onde is_reliable indica
    se o token é baseado em fatores que mudam confiavelmente (tamanho, mtime).
    """
    if band.logo and band.logo.name:
        components = [band.logo.name, PWA_ICON_STYLE_VERSION]
        is_reliable = False
        
        try:
            # get_modified_time pode não estar implementado em todos os storages remotos
            mtime = band.logo.storage.get_modified_time(band.logo.name)
            if mtime:
                components.append(str(mtime.timestamp()))
                is_reliable = True
        except Exception:
            pass
            
        if not is_reliable:
            try:
                components.append(str(band.logo.size))
            except Exception:
                pass
            
        token_string = "|".join(components)
        token_hash = hashlib.sha256(token_string.encode('utf-8')).hexdigest()[:8]
        return token_hash, is_reliable
    return "fallback", True

def band_manifest(request, band_slug):
    """
    Retorna o manifest dinâmico de uma banda específica.
    """
    band = get_object_or_404(Band, slug=band_slug)
    
    if not band.is_active:
        raise Http404("Banda inativa.")
        
    start_url = reverse('dashboard', kwargs={'band_slug': band.slug}) + '?source=pwa'
    
    v = get_band_icon_version(band)
    icons = [
        {
            "src": reverse('band_icon', kwargs={'band_slug': band.slug, 'filename': 'icon-192.png'}) + f"?v={v}",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any"
        },
        {
            "src": reverse('band_icon', kwargs={'band_slug': band.slug, 'filename': 'icon-512.png'}) + f"?v={v}",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any"
        },
        {
            "src": reverse('band_icon', kwargs={'band_slug': band.slug, 'filename': 'icon-maskable-192.png'}) + f"?v={v}",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "maskable"
        },
        {
            "src": reverse('band_icon', kwargs={'band_slug': band.slug, 'filename': 'icon-maskable-512.png'}) + f"?v={v}",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable"
        }
    ]
    
    manifest = {
        "name": band.name.strip(),
        "short_name": get_short_name(band.name),
        "id": f"/{band.slug}/",
        "start_url": start_url,
        "scope": f"/{band.slug}/",
        "display": "standalone",
        "orientation": "any",
        "theme_color": "#6BD443",
        "background_color": "#6BD443",
        "lang": "pt-BR",
        "description": "Gestão de shows, agenda e equipe da banda.",
        "icons": icons
    }
    
    response = JsonResponse(manifest)
    response['Content-Type'] = 'application/manifest+json'
    # Força a revalidação para que se o nome da banda mudar, o manifest mude rapidamente
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response


def admin_manifest(request):
    """
    Retorna o manifest dinâmico do painel administrativo geral.
    """
    start_url = reverse('admin_painel:dashboard') + '?source=pwa'
    
    # Ícones fixos do admin (Backstage Pro)
    v = "white-bg-v2"
    icons = [
        {
            "src": static("core/pwa/icons/backstage-icon-192.png") + f"?v={v}",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any"
        },
        {
            "src": static("core/pwa/icons/backstage-icon-512.png") + f"?v={v}",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any"
        },
        {
            "src": static("core/pwa/icons/backstage-icon-maskable-192.png") + f"?v={v}",
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "maskable"
        },
        {
            "src": static("core/pwa/icons/backstage-icon-maskable-512.png") + f"?v={v}",
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable"
        }
    ]
    
    manifest = {
        "name": "Backstage Pro",
        "short_name": "Backstage Pro",
        "id": "/painel/",
        "start_url": start_url,
        "scope": "/painel/",
        "display": "standalone",
        "orientation": "any",
        "theme_color": "#6BD443",
        "background_color": "#6BD443",
        "lang": "pt-BR",
        "description": "Painel administrativo do Backstage Pro.",
        "icons": icons
    }
    
    response = JsonResponse(manifest)
    response['Content-Type'] = 'application/manifest+json'
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response

def band_icon_view(request, band_slug, filename):
    """
    Retorna os ícones da banda (192, 512, maskable e apple-touch-icon).
    O Cache é infinito pois as URLs são versionadas.
    Em caso de banda sem logo ou erro, retorna os ícones do Backstage Pro com 200.
    """
    ALLOWED_ICONS = {
        'icon-192.png': (192, False, False),
        'icon-512.png': (512, False, False),
        'icon-maskable-192.png': (192, True, False),
        'icon-maskable-512.png': (512, True, False),
        'apple-touch-icon.png': (180, False, True),
    }
    
    if filename not in ALLOWED_ICONS:
        raise Http404("Ícone inválido ou não autorizado.")
        
    size, maskable, apple = ALLOWED_ICONS[filename]
    
    band = get_object_or_404(Band, slug=band_slug)
    if not band.is_active:
        raise Http404("Banda inativa.")
        
    icon_data = generate_band_icon(band.logo, size, maskable, apple)
    
    if not icon_data:
        # Fallback para o ícone fixo
        fallback_filename = f"backstage-{filename}"
        fallback_path = finders.find(f"core/pwa/icons/{fallback_filename}")
        
        if fallback_path and os.path.exists(fallback_path):
            with open(fallback_path, 'rb') as f:
                icon_data = f.read()
        else:
            raise Http404("Fallback icon missing.")
            
    response = HttpResponse(icon_data, content_type='image/png')
    _, is_reliable = get_band_icon_version(band)
    if is_reliable:
        response['Cache-Control'] = 'public, max-age=31536000, immutable'
    else:
        response['Cache-Control'] = 'public, max-age=0, must-revalidate'
    return response

import json

def band_service_worker(request, band_slug):
    """
    Retorna o Service Worker pass-through da banda.
    """
    band = get_object_or_404(Band, slug=band_slug)
    
    if not band.is_active:
        raise Http404("Banda inativa.")
        
    sw_content = f"""
"use strict";

const SW_VERSION = {json.dumps(band.slug + "-v1")};
const SCOPE = {json.dumps("/" + band.slug + "/")};

self.addEventListener("install", (event) => {{
    // Pass-through install
}});

self.addEventListener("activate", (event) => {{
    // Pass-through activate
}});
"""
    response = HttpResponse(sw_content.strip(), content_type='application/javascript; charset=utf-8')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Service-Worker-Allowed'] = f"/{band.slug}/"
    return response

def admin_service_worker(request):
    """
    Retorna o Service Worker pass-through do painel administrativo.
    """
    sw_content = """
"use strict";

const SW_VERSION = "backstage-admin-v1";
const SCOPE = "/painel/";

self.addEventListener("install", (event) => {
    // Pass-through install
});

self.addEventListener("activate", (event) => {
    // Pass-through activate
});
"""
    response = HttpResponse(sw_content.strip(), content_type='application/javascript; charset=utf-8')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Service-Worker-Allowed'] = '/painel/'
    return response
