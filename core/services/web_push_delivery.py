import json
import logging
from django.utils import timezone
from django.db import models, connection
from core.models import Notification, WebPushSubscription, WebPushDelivery
from core.services.vapid_config import load_vapid_configuration
from pywebpush import webpush, WebPushException
import urllib.parse

logger = logging.getLogger(__name__)

MAX_WEB_PUSH_PAYLOAD_BYTES = 3800

def build_web_push_payload(notification: Notification) -> dict:
    valid_events = ['NEW_SHOW', 'SHOW_CANCELLED', 'SHOW_DATE_CHANGED', 'SHOW_START_TIME_CHANGED', 'SHOW_CONFIRMED', 'AVISO']
    if notification.event_type not in valid_events:
        return None
    
    if not isinstance(notification.id, int) or notification.id <= 0:
        return None

    if not notification.band or not notification.band.slug:
        return None

    if not notification.title or not isinstance(notification.title, str) or len(notification.title) == 0 or len(notification.title) > 120:
        return None
    
    for char in notification.title:
        if ord(char) < 32 or ord(char) == 127:
            return None

    if not notification.message or not isinstance(notification.message, str) or len(notification.message) == 0 or len(notification.message) > 300:
        return None
    
    for char in notification.message:
        if ord(char) < 32 or ord(char) == 127:
            return None

    target = notification.target_url
    if not isinstance(target, str) or len(target) > 500:
        return None
        
    if not target.startswith(f"/{notification.band.slug}/"):
        return None
    
    if target.startswith('//'):
        return None
        
    if '\\' in target or '\r' in target or '\n' in target:
        return None
        
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return None
        
    parts = parsed.path.split('/')
    if '.' in parts or '..' in parts:
        return None
        
    decoded_once = urllib.parse.unquote(target)
    decoded_twice = urllib.parse.unquote(decoded_once)
    if decoded_once != decoded_twice:
        return None

    payload = {
        "version": 1,
        "notification_id": notification.id,
        "event_type": notification.event_type,
        "band_slug": notification.band.slug,
        "title": notification.title,
        "message": notification.message,
        "target_url": notification.target_url
    }
    
    return payload

def prepare_web_push_deliveries(notification_id: int):
    try:
        notification = Notification.objects.select_related('recipient', 'band').get(pk=notification_id)
    except Notification.DoesNotExist:
        return []
        
    payload = build_web_push_payload(notification)
    if not payload:
        logger.warning(f"Invalid payload for notification_id {notification_id}")
        return []
        
    # Validamos tamanho no prepare também para não gerar deliveries mortos atoa?
    # Mas a instrução: "Payload acima do limite: não chama webpush; delivery fica SKIPPED; error_code='payload_too_large'". Isso exige que as deliveries sejam criadas.
    # Então não bloqueamos aqui.

    now = timezone.now()
    
    from django.db.models import Q, F
    valid_subs = WebPushSubscription.objects.filter(
        is_active=True,
        user=notification.recipient,
        band=notification.band,
        service_worker_scope=f"/{notification.band.slug}/"
    ).filter(
        Q(expiration_time__isnull=True) | Q(expiration_time__gt=now)
    )

    expired_subs = WebPushSubscription.objects.filter(
        is_active=True,
        user=notification.recipient,
        band=notification.band,
        service_worker_scope=f"/{notification.band.slug}/",
        expiration_time__lte=now
    )
    
    # Expiradas são imediatamente desativadas, e falhas incrementadas sem gerar Delivery
    if expired_subs.exists():
        expired_subs.update(
            is_active=False,
            failure_count=F('failure_count') + 1,
            last_failure_at=now
        )
        
    deliveries_created = []
    for sub in valid_subs:
        delivery, created = WebPushDelivery.objects.get_or_create(
            notification=notification,
            subscription=sub,
            defaults={'status': WebPushDelivery.StatusChoices.PENDING}
        )
        if created:
            deliveries_created.append(delivery)
            
    return deliveries_created

def send_web_push_delivery(delivery_id: int):
    now = timezone.now()
    
    # Claim atômico. Sem transaction block longo
    updated = WebPushDelivery.objects.filter(
        pk=delivery_id, 
        status=WebPushDelivery.StatusChoices.PENDING
    ).update(
        status=WebPushDelivery.StatusChoices.SENDING,
        attempt_count=models.F('attempt_count') + 1,
        last_attempt_at=now,
        updated_at=now
    )
    
    if updated == 0:
        return "SKIPPED/ALREADY_CLAIMED"
        
    try:
        delivery = WebPushDelivery.objects.select_related('notification__band', 'subscription').get(pk=delivery_id)
    except WebPushDelivery.DoesNotExist:
        return "SKIPPED"
        
    payload = build_web_push_payload(delivery.notification)
    if not payload:
        rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
            status=WebPushDelivery.StatusChoices.SKIPPED,
            error_code="invalid_payload",
            updated_at=timezone.now()
        )
        if rows == 0:
            return "SKIPPED/ALREADY_FINALIZED"
        return "SKIPPED"
        
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(payload_json.encode('utf-8')) > MAX_WEB_PUSH_PAYLOAD_BYTES:
        rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
            status=WebPushDelivery.StatusChoices.SKIPPED,
            error_code="payload_too_large",
            updated_at=timezone.now()
        )
        if rows == 0:
            return "SKIPPED/ALREADY_FINALIZED"
        return "SKIPPED"
    
    try:
        vapid_config = load_vapid_configuration()
    except Exception:
        rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
            status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
            error_code="vapid_error",
            updated_at=timezone.now()
        )
        if rows == 0:
            return "SKIPPED/ALREADY_FINALIZED"
        
        WebPushSubscription.objects.filter(pk=delivery.subscription_id).update(
            failure_count=models.F('failure_count') + 1,
            last_failure_at=timezone.now()
        )
        return "TEMPORARY_FAILURE"
        
    subscription_info = {
        "endpoint": delivery.subscription.endpoint,
        "keys": {
            "p256dh": delivery.subscription.p256dh,
            "auth": delivery.subscription.auth
        }
    }
    
    if connection.in_atomic_block:
        raise RuntimeError("Rede chamada dentro de transação")
    
    try:
        # Novo dict para vapid claims a cada envio
        vapid_claims = {"sub": vapid_config.subject}
        
        response = webpush(
            subscription_info=subscription_info,
            data=payload_json,
            vapid_private_key=vapid_config.private_key,
            vapid_claims=vapid_claims,
            content_encoding="aes128gcm",
            ttl=3600,
            timeout=5,
            verbose=False,
        )
        
        if response is None or not hasattr(response, 'status_code'):
            rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
                status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
                error_code="missing_http_response",
                updated_at=timezone.now()
            )
            if rows == 0:
                return "SKIPPED/ALREADY_FINALIZED"
            
            WebPushSubscription.objects.filter(pk=delivery.subscription_id).update(
                failure_count=models.F('failure_count') + 1,
                last_failure_at=timezone.now()
            )
            logger.warning(f"WebPush delivery {delivery_id} temporary failure (missing response). Notification: {delivery.notification_id}, Sub: {delivery.subscription_id}, Band: {delivery.notification.band_id}")
            return "TEMPORARY_FAILURE"
            
        status_code = response.status_code
        
        if status_code in (200, 201, 202):
            rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
                status=WebPushDelivery.StatusChoices.SENT,
                sent_at=timezone.now(),
                last_http_status=status_code,
                error_code="",
                updated_at=timezone.now()
            )
            if rows == 0:
                return "SKIPPED/ALREADY_FINALIZED"
            
            WebPushSubscription.objects.filter(pk=delivery.subscription_id).update(
                failure_count=0,
                last_success_at=timezone.now()
            )
            logger.info(f"WebPush delivery {delivery_id} sent successfully ({status_code}). Notification: {delivery.notification_id}, Sub: {delivery.subscription_id}, Band: {delivery.notification.band_id}")
            return "SENT"
        
        elif status_code == 204:
            rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
                status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
                last_http_status=status_code,
                error_code="unexpected_http_status",
                updated_at=timezone.now()
            )
            if rows == 0:
                return "SKIPPED/ALREADY_FINALIZED"
            
            WebPushSubscription.objects.filter(pk=delivery.subscription_id).update(
                failure_count=models.F('failure_count') + 1,
                last_failure_at=timezone.now()
            )
            logger.warning(f"WebPush delivery {delivery_id} temporary failure ({status_code}). Notification: {delivery.notification_id}, Sub: {delivery.subscription_id}, Band: {delivery.notification.band_id}")
            return "TEMPORARY_FAILURE"
            
        else:
            rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
                status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
                last_http_status=status_code,
                error_code="unexpected_http_status",
                updated_at=timezone.now()
            )
            if rows == 0:
                return "SKIPPED/ALREADY_FINALIZED"
            
            WebPushSubscription.objects.filter(pk=delivery.subscription_id).update(
                failure_count=models.F('failure_count') + 1,
                last_failure_at=timezone.now()
            )
            logger.warning(f"WebPush delivery {delivery_id} temporary failure ({status_code}). Notification: {delivery.notification_id}, Sub: {delivery.subscription_id}, Band: {delivery.notification.band_id}")
            return "TEMPORARY_FAILURE"
            
    except WebPushException as exc:
        status_code = None
        if exc.response is not None:
            status_code = getattr(exc.response, 'status_code', None)
            
        if status_code in (404, 410):
            rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
                status=WebPushDelivery.StatusChoices.PERMANENT_FAILURE,
                last_http_status=status_code,
                error_code="subscription_expired",
                updated_at=timezone.now()
            )
            if rows == 0:
                return "SKIPPED/ALREADY_FINALIZED"
            
            WebPushSubscription.objects.filter(pk=delivery.subscription_id).update(
                is_active=False,
                failure_count=models.F('failure_count') + 1,
                last_failure_at=timezone.now()
            )
            logger.info(f"WebPush delivery {delivery_id} permanent failure ({status_code}). Notification: {delivery.notification_id}, Sub: {delivery.subscription_id}, Band: {delivery.notification.band_id}")
            return "PERMANENT_FAILURE"
        else:
            rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
                status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
                last_http_status=status_code,
                error_code="webpush_exception",
                updated_at=timezone.now()
            )
            if rows == 0:
                return "SKIPPED/ALREADY_FINALIZED"
            
            WebPushSubscription.objects.filter(pk=delivery.subscription_id).update(
                failure_count=models.F('failure_count') + 1,
                last_failure_at=timezone.now()
            )
            logger.warning(f"WebPush delivery {delivery_id} temporary failure ({status_code}). Notification: {delivery.notification_id}, Sub: {delivery.subscription_id}, Band: {delivery.notification.band_id}")
            return "TEMPORARY_FAILURE"
            
    except Exception:
        rows = WebPushDelivery.objects.filter(pk=delivery_id, status=WebPushDelivery.StatusChoices.SENDING).update(
            status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
            error_code="unexpected_error",
            updated_at=timezone.now()
        )
        if rows == 0:
            return "SKIPPED/ALREADY_FINALIZED"
        
        WebPushSubscription.objects.filter(pk=delivery.subscription_id).update(
            failure_count=models.F('failure_count') + 1,
            last_failure_at=timezone.now()
        )
        logger.warning(f"WebPush delivery {delivery_id} unexpected error. Notification: {delivery.notification_id}, Sub: {delivery.subscription_id}, Band: {delivery.notification.band_id}")
        return "TEMPORARY_FAILURE"


def dispatch_notification_web_push(notification_id: int) -> dict:
    deliveries = prepare_web_push_deliveries(notification_id)
    
    results = {
        "total": len(deliveries),
        "sent": 0,
        "temporary_failure": 0,
        "permanent_failure": 0,
        "skipped": 0
    }
    
    for delivery in deliveries:
        res = send_web_push_delivery(delivery.id)
        if res == "SENT":
            results["sent"] += 1
        elif res == "TEMPORARY_FAILURE":
            results["temporary_failure"] += 1
        elif res == "PERMANENT_FAILURE":
            results["permanent_failure"] += 1
        else:
            results["skipped"] += 1
            
    return results
