import json
import unicodedata
import urllib.parse
import base64
import binascii
from datetime import datetime, timezone
from django.http import JsonResponse
from django.conf import settings
from django.db import IntegrityError
from functools import wraps

from core.models import Band
from core.services import web_push_subscriptions
from core.services.web_push_subscriptions import SubscriptionConflictError
from core.services.vapid_config import load_vapid_configuration, VapidConfigurationError

def set_no_store(response):
    response['Cache-Control'] = 'no-store'
    return response

def custom_csrf_failure(request, reason=""):
    if request.path.startswith('/push/') or request.path.endswith('/push/inscrever/') or request.path.endswith('/push/status/') or request.path.endswith('/push/desinscrever/'):
        return set_no_store(JsonResponse({"error": "csrf_failed"}, status=403))
    from django.views.csrf import csrf_failure
    return csrf_failure(request, reason=reason)

def api_band_auth_required(view_func):
    """
    Garante autenticação, pertencimento à banda e papel para as rotas da API.
    """
    @wraps(view_func)
    def _wrapped_view(request, band_slug, *args, **kwargs):
        if not request.user.is_authenticated:
            return set_no_store(JsonResponse({"error": "unauthorized"}, status=401))
        if not request.user.is_active:
            return set_no_store(JsonResponse({"error": "forbidden", "detail": "user_inactive"}, status=403))
            
        try:
            band = Band.objects.get(slug=band_slug)
        except Band.DoesNotExist:
            return set_no_store(JsonResponse({"error": "not_found", "detail": "band_not_found"}, status=404))
            
        if not band.is_active:
            return set_no_store(JsonResponse({"error": "not_found", "detail": "band_inactive"}, status=404))
            
        if request.user.band != band:
            return set_no_store(JsonResponse({"error": "not_found", "detail": "not_member"}, status=404))
            
        if request.user.role not in ['PRODUTOR', 'INTEGRANTE']:
            return set_no_store(JsonResponse({"error": "forbidden", "detail": "role_not_allowed"}, status=403))
            
        request.band = band
        return view_func(request, band_slug, *args, **kwargs)
    return _wrapped_view

def require_json_post(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.method != 'POST':
            return set_no_store(JsonResponse({"error": "method_not_allowed"}, status=405))
            
        content_type = request.META.get('CONTENT_TYPE', '').lower()
        if not content_type.startswith('application/json'):
            return set_no_store(JsonResponse({"error": "unsupported_media_type"}, status=415))
            
        content_length = request.META.get('CONTENT_LENGTH', '0')
        try:
            content_length = int(content_length)
        except ValueError:
            return set_no_store(JsonResponse({"error": "bad_request"}, status=400))
            
        if content_length < 0:
            return set_no_store(JsonResponse({"error": "bad_request"}, status=400))
            
        if content_length > 16384:
            return set_no_store(JsonResponse({"error": "payload_too_large"}, status=413))
            
        body = request.body
        if len(body) > 16384:
            return set_no_store(JsonResponse({"error": "payload_too_large"}, status=413))
            
        if not body:
            return set_no_store(JsonResponse({"error": "bad_request", "detail": "empty_body"}, status=400))
            
        try:
            data = json.loads(body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_json"}, status=400))
            
        if not isinstance(data, dict):
            return set_no_store(JsonResponse({"error": "bad_request", "detail": "must_be_object"}, status=400))
            
        request.json_data = data
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def require_json_get(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.method != 'GET':
            return set_no_store(JsonResponse({"error": "method_not_allowed"}, status=405))
        return view_func(request, *args, **kwargs)
    return _wrapped_view

def validate_endpoint(endpoint):
    if not isinstance(endpoint, str):
        return False
    if not endpoint or len(endpoint) > 4096:
        return False
        
    for char in endpoint:
        if unicodedata.category(char).startswith('C'):
            return False
            
    if '\\' in endpoint:
        return False
    if endpoint.startswith('//'):
        return False
        
    parsed = urllib.parse.urlsplit(endpoint)
    if parsed.scheme != 'https':
        return False
    if not parsed.netloc:
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.fragment:
        return False
        
    return True

def decode_base64url(val):
    if not isinstance(val, str):
        return None
    for char in val:
        if char.isspace() or unicodedata.category(char).startswith('C'):
            return None
    try:
        pad = len(val) % 4
        padded_val = val + '=' * (4 - pad) if pad else val
        return base64.urlsafe_b64decode(padded_val)
    except (binascii.Error, ValueError):
        return None

def validate_p256dh(val):
    if not isinstance(val, str) or len(val) > 255:
        return False
    decoded = decode_base64url(val)
    if not decoded or len(decoded) != 65 or decoded[0] != 0x04:
        return False
    return True

def validate_auth(val):
    if not isinstance(val, str) or len(val) > 255:
        return False
    decoded = decode_base64url(val)
    if not decoded or len(decoded) != 16:
        return False
    return True

def parse_expiration_time(val):
    if val is None:
        return True, None
    if isinstance(val, bool) or not (isinstance(val, int) or isinstance(val, float)):
        return False, None
    import math
    if math.isnan(val) or math.isinf(val) or val < 0:
        return False, None
        
    try:
        dt = datetime.fromtimestamp(val / 1000.0, tz=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return False, None
        
    if dt < datetime.now(timezone.utc):
        return False, None
        
    return True, dt

def sanitize_user_agent(request):
    ua = request.META.get('HTTP_USER_AGENT', '')
    if not isinstance(ua, str):
        ua = ''
    safe_ua = ''.join(c for c in ua if not unicodedata.category(c).startswith('C'))
    return safe_ua[:512]


@require_json_get
@api_band_auth_required
def push_public_key(request, band_slug):
    try:
        vapid_config = load_vapid_configuration()
        return set_no_store(JsonResponse({"publicKey": vapid_config.public_key}))
    except VapidConfigurationError:
        return set_no_store(JsonResponse({"error": "push_not_configured"}, status=503))


@api_band_auth_required
@require_json_post
def push_subscription_status(request, band_slug):
    data = request.json_data
    allowed_keys = {'endpoint'}
    if set(data.keys()) != allowed_keys:
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_fields"}, status=400))
        
    endpoint = data.get('endpoint')
    if not validate_endpoint(endpoint):
        return set_no_store(JsonResponse({"subscribed": False}))
        
    scope = f"/{request.band.slug}/"
    is_subscribed = web_push_subscriptions.check_status(
        user=request.user,
        band=request.band,
        scope=scope,
        endpoint=endpoint
    )
    
    return set_no_store(JsonResponse({"subscribed": is_subscribed}))


@api_band_auth_required
@require_json_post
def push_subscribe(request, band_slug):
    data = request.json_data
    
    allowed_keys = {'endpoint', 'keys'}
    allowed_keys_optional = {'endpoint', 'keys', 'expirationTime'}
    keys_in_data = set(data.keys())
    if not (keys_in_data == allowed_keys or keys_in_data == allowed_keys_optional):
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_fields"}, status=400))
            
    endpoint = data.get('endpoint')
    if not validate_endpoint(endpoint):
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_endpoint"}, status=400))
        
    keys = data.get('keys')
    if not isinstance(keys, dict):
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_keys"}, status=400))
        
    if set(keys.keys()) != {'p256dh', 'auth'}:
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_keys_fields"}, status=400))
        
    p256dh = keys.get('p256dh')
    auth = keys.get('auth')
    
    if not validate_p256dh(p256dh):
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_p256dh"}, status=400))
        
    if not validate_auth(auth):
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_auth"}, status=400))
        
    exp = data.get('expirationTime')
    valid_exp, dt_exp = parse_expiration_time(exp)
    if not valid_exp:
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_expiration"}, status=400))
        
    user_agent = sanitize_user_agent(request)
    scope = f"/{request.band.slug}/"
    
    try:
        sub, created = web_push_subscriptions.register_or_update_subscription(
            user=request.user,
            band=request.band,
            scope=scope,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            user_agent=user_agent,
            expiration_time=dt_exp
        )
    except SubscriptionConflictError:
        return set_no_store(JsonResponse({"error": "subscription_conflict"}, status=409))
    except IntegrityError:
        # Corrida. Vamos tentar resolver
        try:
            sub, created = web_push_subscriptions.resolve_subscription_after_integrity_error(
                user=request.user,
                band=request.band,
                scope=scope,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=user_agent,
                expiration_time=dt_exp
            )
        except SubscriptionConflictError:
            return set_no_store(JsonResponse({"error": "subscription_conflict"}, status=409))
        except web_push_subscriptions.SubscriptionNotFoundError:
            return set_no_store(JsonResponse({"error": "subscription_conflict"}, status=409))
            
    if created:
        return set_no_store(JsonResponse({"status": "subscribed"}, status=201))
    else:
        return set_no_store(JsonResponse({"status": "updated"}, status=200))


@api_band_auth_required
@require_json_post
def push_unsubscribe(request, band_slug):
    data = request.json_data
    allowed_keys = {'endpoint'}
    if set(data.keys()) != allowed_keys:
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_fields"}, status=400))

    endpoint = data.get('endpoint')
    if not validate_endpoint(endpoint):
        return set_no_store(JsonResponse({"error": "bad_request", "detail": "invalid_endpoint"}, status=400))
        
    scope = f"/{request.band.slug}/"
    web_push_subscriptions.unsubscribe(
        user=request.user,
        band=request.band,
        scope=scope,
        endpoint=endpoint
    )
    
    return set_no_store(JsonResponse({"unsubscribed": True}, status=200))
