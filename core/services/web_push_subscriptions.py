import hashlib
from django.db import transaction, IntegrityError
from core.models import WebPushSubscription

def _get_hash(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode('utf-8')).hexdigest()

def check_status(user, band, scope, endpoint):
    """
    POST /<band_slug>/push/status/
    Verifica se existe subscription ATIVA exata para este usuário, banda, scope e endpoint.
    """
    endpoint_hash = _get_hash(endpoint)
    exists = WebPushSubscription.objects.filter(
        endpoint_hash=endpoint_hash,
        user=user,
        band=band,
        service_worker_scope=scope,
        is_active=True
    ).exists()
    return exists

def unsubscribe(user, band, scope, endpoint):
    """
    POST /<band_slug>/push/desinscrever/
    Desativa (is_active=False) se pertencer a este usuário, banda e scope.
    É idempotente e retorna True sempre (sucesso).
    """
    endpoint_hash = _get_hash(endpoint)
    
    with transaction.atomic():
        sub = WebPushSubscription.objects.select_for_update().filter(
            endpoint_hash=endpoint_hash,
            user=user,
            band=band,
            service_worker_scope=scope
        ).first()
        
        if sub:
            if sub.is_active:
                sub.is_active = False
                sub.save(update_fields=['is_active', 'updated_at'])
    return True

class SubscriptionConflictError(Exception):
    pass

class SubscriptionNotFoundError(Exception):
    pass

def resolve_subscription_after_integrity_error(user, band, scope, endpoint, p256dh, auth, expiration_time, user_agent):
    endpoint_hash = _get_hash(endpoint)
    with transaction.atomic():
        sub = WebPushSubscription.objects.select_for_update().filter(
            endpoint_hash=endpoint_hash
        ).first()
        
        if not sub:
            raise SubscriptionNotFoundError("Subscription unexpectedly not found after IntegrityError")
            
        if sub.user_id == user.id and sub.band_id == band.id and sub.service_worker_scope == scope:
            sub.p256dh = p256dh
            sub.auth = auth
            sub.expiration_time = expiration_time
            sub.user_agent = user_agent
            sub.is_active = True
            sub.failure_count = 0
            sub.last_failure_at = None
            sub.save(update_fields=[
                'p256dh', 'auth', 'expiration_time', 'user_agent', 
                'is_active', 'failure_count', 'last_failure_at', 'updated_at'
            ])
            return sub, False
        else:
            raise SubscriptionConflictError("Subscription associated with another user or scope")

def register_or_update_subscription(user, band, scope, endpoint, p256dh, auth, expiration_time, user_agent):
    endpoint_hash = _get_hash(endpoint)
    
    with transaction.atomic():
        sub = WebPushSubscription.objects.select_for_update().filter(
            endpoint_hash=endpoint_hash
        ).first()
        
        if sub:
            if sub.user_id == user.id and sub.band_id == band.id and sub.service_worker_scope == scope:
                sub.p256dh = p256dh
                sub.auth = auth
                sub.expiration_time = expiration_time
                sub.user_agent = user_agent
                sub.is_active = True
                sub.failure_count = 0
                sub.last_failure_at = None
                sub.save(update_fields=[
                    'p256dh', 'auth', 'expiration_time', 'user_agent', 
                    'is_active', 'failure_count', 'last_failure_at', 'updated_at'
                ])
                return sub, False
            else:
                raise SubscriptionConflictError("Subscription associated with another user or scope")
                
        # Attempt to create
        sub = WebPushSubscription(
            user=user,
            band=band,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            service_worker_scope=scope,
            user_agent=user_agent,
            expiration_time=expiration_time,
            is_active=True,
            failure_count=0
        )
        sub.full_clean()
        sub.save()
        return sub, True
