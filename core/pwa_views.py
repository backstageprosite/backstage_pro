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
        
    v, _ = get_band_icon_version(band)
    icon_url = reverse('band_icon', kwargs={'band_slug': band.slug, 'filename': 'icon-192.png'}) + f"?v={v}"
    notifications_url = reverse('notifications_list', kwargs={'band_slug': band.slug})

    sw_content = f"""
"use strict";

const SW_VERSION = {json.dumps("backstage-" + band.slug + "-v4")};
const BAND_SLUG = {json.dumps(band.slug)};
const BAND_SCOPE = {json.dumps("/" + band.slug + "/")};
const BAND_NAME = {json.dumps(band.name.strip())};
const NOTIFICATIONS_URL = {json.dumps(notifications_url)};
const ICON_URL = {json.dumps(icon_url)};

self.addEventListener("install", (event) => {{
    self.skipWaiting();
}});

self.addEventListener("activate", (event) => {{
    event.waitUntil((async () => {{
        const cacheNames = await caches.keys();
        await Promise.all(
            cacheNames.filter(name => name.startsWith("backstage-") && name !== SW_VERSION)
                      .map(name => caches.delete(name))
        );
        await self.clients.claim();
    }})());
}});

function normalizeInternalTarget(rawTarget) {{
    if (typeof rawTarget !== 'string') return NOTIFICATIONS_URL;
    if (rawTarget.length > 500) return NOTIFICATIONS_URL;
    
    if (!rawTarget.startsWith('/') || rawTarget.startsWith('//')) return NOTIFICATIONS_URL;
    if (/[\\x00-\\x1F\\x7F\\r\\n\\\\]/.test(rawTarget)) return NOTIFICATIONS_URL;
    
    try {{
        const url = new URL(rawTarget, self.location.origin);
        if (url.origin !== self.location.origin) return NOTIFICATIONS_URL;
        if (!url.pathname.startsWith(BAND_SCOPE)) return NOTIFICATIONS_URL;
        if (url.pathname.startsWith('/painel/')) return NOTIFICATIONS_URL;
        
        const segments = url.pathname.split('/');
        const badSegments = ['.', '..', '%2e', '%2e%2e', '%252e', '%252e%252e'];
        for (let b of badSegments) {{
            if (segments.includes(b)) return NOTIFICATIONS_URL;
        }}
        
        const decoded = decodeURIComponent(url.pathname);
        const decSegments = decoded.split('/');
        if (decSegments.includes('.') || decSegments.includes('..')) return NOTIFICATIONS_URL;
        if (decoded.includes('//')) return NOTIFICATIONS_URL;
        
        return url.pathname + url.search;
    }} catch (e) {{
        return NOTIFICATIONS_URL;
    }}
}}

self.addEventListener("push", (event) => {{
    event.waitUntil((async () => {{
        let payload = null;
        try {{
            if (event.data) {{
                payload = event.data.json();
            }}
        }} catch (e) {{
            payload = null;
        }}

        let title = BAND_NAME || "Backstage Pro";
        let message = "Há uma nova atualização disponível.";
        let targetUrl = NOTIFICATIONS_URL;
        let notificationId = null;
        let eventType = null;

        if (payload) {{
            if (
                payload.version === 1 &&
                Number.isInteger(payload.notification_id) && payload.notification_id > 0 &&
                ["NEW_SHOW", "SHOW_CANCELLED", "SHOW_DATE_CHANGED", "SHOW_START_TIME_CHANGED", "SHOW_CONFIRMED"].includes(payload.event_type) &&
                payload.band_slug === BAND_SLUG &&
                typeof payload.title === 'string' && payload.title.trim().length > 0 && payload.title.length <= 120 &&
                !/[\\x00-\\x1F\\x7F<>]/.test(payload.title) &&
                typeof payload.message === 'string' && payload.message.trim().length > 0 && payload.message.length <= 300 &&
                !/[\\x00-\\x1F\\x7F<>]/.test(payload.message)
            ) {{
                title = payload.title.trim();
                message = payload.message.trim();
                targetUrl = normalizeInternalTarget(payload.target_url);
                notificationId = payload.notification_id;
                eventType = payload.event_type;
            }}
        }}

        const options = {{
            body: message,
            icon: ICON_URL,
            data: {{
                notificationId: notificationId,
                targetUrl: targetUrl,
                bandSlug: BAND_SLUG,
                eventType: eventType
            }}
        }};

        let tag = "backstagepro-" + BAND_SLUG + "-notification";
        if (notificationId) {{
            tag += "-" + notificationId;
        }}
        options.tag = tag;

        return self.registration.showNotification(title, options);
    }})().catch(() => {{
        return self.registration.showNotification(BAND_NAME || "Backstage Pro", {{
            body: "Há uma nova atualização disponível.",
            icon: ICON_URL,
            data: {{ targetUrl: NOTIFICATIONS_URL }}
        }});
    }}));
}});

self.addEventListener("notificationclick", (event) => {{
    event.notification.close();

    event.waitUntil((async () => {{
        let rawTarget = NOTIFICATIONS_URL;
        if (event.notification.data && event.notification.data.targetUrl) {{
            rawTarget = event.notification.data.targetUrl;
        }}
        const targetUrl = normalizeInternalTarget(rawTarget);
        const absoluteTargetUrl = new URL(targetUrl, self.location.origin).href;

        let windowClients = [];
        try {{
            windowClients = await clients.matchAll({{
                type: "window",
                includeUncontrolled: true
            }});
        }} catch (e) {{
            windowClients = [];
        }}

        for (let client of windowClients) {{
            if (client.url === absoluteTargetUrl) {{
                try {{
                    return await client.focus();
                }} catch (e) {{
                    return;
                }}
            }}
        }}

        for (let client of windowClients) {{
            try {{
                const clientUrl = new URL(client.url);
                if (clientUrl.origin === self.location.origin && clientUrl.pathname.startsWith(BAND_SCOPE)) {{
                    const navigatedClient = await client.navigate(targetUrl);
                    if (navigatedClient) {{
                        return await navigatedClient.focus();
                    }} else {{
                        return await client.focus();
                    }}
                }}
            }} catch (e) {{}}
        }}

        if (clients.openWindow) {{
            try {{
                return await clients.openWindow(targetUrl);
            }} catch (e) {{}}
        }}
    }})());
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
