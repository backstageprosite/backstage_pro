import hashlib
import json
import uuid
import datetime
from django.conf import settings
from django.core.validators import validate_email, URLValidator
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError, connection
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from smtplib import SMTPException, SMTPSenderRefused, SMTPRecipientsRefused, SMTPAuthenticationError
from django.db import models
from core.models import WebPushOperationalAlertEmailDelivery, WebPushOperationalAlertCycleLease, WebPushOperationalAlert
from urllib.parse import urlsplit

def get_web_push_alert_email_config() -> dict:
    enabled = getattr(settings, 'WEB_PUSH_ALERT_EMAIL_ENABLED', False)

    recipients_str = getattr(settings, 'WEB_PUSH_ALERT_EMAIL_RECIPIENTS', '')
    raw_recipients = [r.strip().casefold() for r in recipients_str.split(',') if r.strip()]

    valid_recipients = []
    for r in raw_recipients:
        try:
            validate_email(r)
            valid_recipients.append(r)
        except ValidationError:
            raise ValueError("email_configuration_invalid")

    valid_recipients = sorted(list(set(valid_recipients)))

    if enabled and not valid_recipients:
        raise ValueError("email_configuration_invalid")

    recipient_set_hash = hashlib.sha256(",".join(valid_recipients).encode('utf-8')).hexdigest()

    min_severity = getattr(settings, 'WEB_PUSH_ALERT_EMAIL_MIN_SEVERITY', 'WARNING')
    if min_severity not in ['WARNING', 'CRITICAL']:
        raise ValueError("email_configuration_invalid")

    max_attempts = getattr(settings, 'WEB_PUSH_ALERT_EMAIL_MAX_ATTEMPTS', 3)
    if not isinstance(max_attempts, int) or not (1 <= max_attempts <= 10):
        raise ValueError("email_configuration_invalid")

    retry_minutes = getattr(settings, 'WEB_PUSH_ALERT_EMAIL_RETRY_MINUTES', 15)
    if not isinstance(retry_minutes, int) or not (5 <= retry_minutes <= 10080):
        raise ValueError("email_configuration_invalid")

    lock_minutes = getattr(settings, 'WEB_PUSH_ALERT_CYCLE_LOCK_MINUTES', 15)
    if not isinstance(lock_minutes, int) or not (5 <= lock_minutes <= 1440):
        raise ValueError("email_configuration_invalid")

    from_email = getattr(settings, 'WEB_PUSH_ALERT_EMAIL_FROM', None) or getattr(settings, 'DEFAULT_FROM_EMAIL', None)
    if not from_email:
        raise ValueError("email_configuration_invalid")
    try:
        validate_email(from_email)
    except ValidationError:
        raise ValueError("email_configuration_invalid")

    dashboard_url = getattr(settings, 'WEB_PUSH_ALERT_DASHBOARD_URL', 'http://localhost:8000/painel/web-push/')
    if not dashboard_url:
        raise ValueError("email_configuration_invalid")

    url_validator = URLValidator(schemes=['http', 'https'])
    try:
        url_validator(dashboard_url)
    except ValidationError:
        raise ValueError("email_configuration_invalid")

    parsed = urlsplit(dashboard_url)
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("email_configuration_invalid")

    return {
        "enabled": enabled,
        "recipients": valid_recipients,
        "recipient_count": len(valid_recipients),
        "recipient_set_hash": recipient_set_hash,
        "min_severity": min_severity,
        "max_attempts": max_attempts,
        "retry_minutes": retry_minutes,
        "lock_minutes": lock_minutes,
        "from_email": from_email,
        "dashboard_url": dashboard_url
    }

def acquire_web_push_operational_alert_cycle_lease(owner_token: str, max_duration_minutes: int = 15) -> bool:
    now = timezone.now()
    WebPushOperationalAlertCycleLease.objects.filter(locked_until__lt=now).delete()

    try:
        with transaction.atomic():
            lease = WebPushOperationalAlertCycleLease.objects.first()
            if lease:
                return False

            WebPushOperationalAlertCycleLease.objects.create(
                owner_token=owner_token,
                locked_until=now + datetime.timedelta(minutes=max_duration_minutes)
            )
            return True
    except IntegrityError:
        return False
    except Exception:
        return False

def release_web_push_operational_alert_cycle_lease(owner_token: str):
    WebPushOperationalAlertCycleLease.objects.filter(owner_token=owner_token).delete()

def plan_web_push_operational_alert_email_deliveries(transition_events: list) -> dict:
    try:
        config = get_web_push_alert_email_config()
    except ValueError:
        return {"to_queue": [], "summary": {"queued": 0, "skipped": len(transition_events)}}

    if not config["enabled"]:
        return {"to_queue": [], "summary": {"queued": 0, "skipped": len(transition_events)}}

    to_queue = []
    skipped = 0

    for event in transition_events:
        alert_id = event["alert_id"]
        event_type = event["event_type"]
        severity = event["severity"]
        opened_count = event["opened_count"]

        if event_type not in ["OPENED", "REOPENED", "ESCALATED", "RESOLVED"]:
            skipped += 1
            continue

        if severity == 'INFO' and event_type != 'RESOLVED':
            skipped += 1
            continue

        if config["min_severity"] == 'CRITICAL' and severity != 'CRITICAL' and event_type != 'RESOLVED':
            skipped += 1
            continue

        suffix = 'critical' if event_type == 'ESCALATED' else event_type.lower()
        event_key = f"alert:{alert_id}:open:{opened_count}:{suffix}"

        if event_type == "RESOLVED":
            sent_count = WebPushOperationalAlertEmailDelivery.objects.filter(
                alert_id=alert_id,
                event_key__startswith=f"alert:{alert_id}:open:{opened_count}:",
                status='SENT'
            ).count()
            if sent_count == 0:
                skipped += 1
                continue

        to_queue.append({
            "alert_id": alert_id,
            "event_key": event_key,
            "event_type": event_type,
            "severity_snapshot": severity,
            "scope_type_snapshot": event.get("scope_type", "GLOBAL"),
            "band_slug_snapshot": event.get("band_slug", None),
            "code_snapshot": event.get("code", "unknown"),
            "current_count_snapshot": event.get("current_count", 0),
            "opened_count_snapshot": opened_count,
        })

    return {
        "to_queue": to_queue,
        "summary": {
            "queued": len(to_queue),
            "skipped": skipped
        }
    }

def queue_web_push_operational_alert_email_deliveries(plan: dict, *, execute: bool = False) -> dict:
    if not execute:
        return {"queued": len(plan["to_queue"]), "already_queued": 0, "errors": 0}

    try:
        config = get_web_push_alert_email_config()
    except ValueError:
        return {"queued": 0, "already_queued": 0, "errors": 0}

    queued = 0
    already_queued = 0
    errors = 0

    for item in plan["to_queue"]:
        try:
            with transaction.atomic():
                WebPushOperationalAlertEmailDelivery.objects.create(
                    alert_id=item["alert_id"],
                    event_key=item["event_key"],
                    event_type=item["event_type"],
                    status='PENDING',
                    severity_snapshot=item["severity_snapshot"],
                    scope_type_snapshot=item.get("scope_type_snapshot", "GLOBAL"),
                    band_slug_snapshot=item.get("band_slug_snapshot", None),
                    code_snapshot=item.get("code_snapshot", "unknown"),
                    current_count_snapshot=item.get("current_count_snapshot", 0),
                    opened_count_snapshot=item.get("opened_count_snapshot", 0),
                    recipient_count=config["recipient_count"],
                    recipient_set_hash=config["recipient_set_hash"],
                    max_attempts=config["max_attempts"],
                    attempt_count=0
                )
                queued += 1
        except IntegrityError:
            exists = WebPushOperationalAlertEmailDelivery.objects.filter(event_key=item["event_key"]).exists()
            if exists:
                already_queued += 1
            else:
                errors += 1
        except Exception:
            errors += 1

    return {"queued": queued, "already_queued": already_queued, "errors": errors}

def _handle_email_failure(delivery, error_code, config):
    delivery.last_error_code = error_code
    delivery.attempt_count += 1

    if error_code in ['smtp_authentication_failed', 'recipient_rejected', 'email_configuration_invalid', 'max_attempts_reached']:
        delivery.status = 'PERMANENT_FAILURE'
        delivery.next_attempt_at = None
    else:
        if delivery.attempt_count >= config['max_attempts']:
            delivery.status = 'PERMANENT_FAILURE'
            delivery.last_error_code = 'max_attempts_reached'
            delivery.next_attempt_at = None
        else:
            delivery.status = 'TEMPORARY_FAILURE'
            delivery.next_attempt_at = timezone.now() + datetime.timedelta(minutes=config['retry_minutes'])

    delivery.save()
    return {"id": delivery.id, "status": delivery.status, "error_code": delivery.last_error_code}

def send_web_push_alert_email_delivery(delivery_id: int) -> dict:
    if connection.in_atomic_block:
        raise RuntimeError("send_web_push_alert_email_delivery cannot be called inside an atomic block")

    now = timezone.now()
    try:
        config = get_web_push_alert_email_config()
    except ValueError:
        with transaction.atomic():
            delivery = WebPushOperationalAlertEmailDelivery.objects.select_for_update().get(id=delivery_id)
            delivery.status = 'SKIPPED'
            delivery.last_error_code = 'email_configuration_invalid'
            delivery.next_attempt_at = None
            delivery.save()
        return {"id": delivery_id, "status": "SKIPPED", "error_code": "email_configuration_invalid"}

    try:
        with transaction.atomic():
            delivery = WebPushOperationalAlertEmailDelivery.objects.select_for_update().get(id=delivery_id)

            if delivery.status not in ['PENDING', 'TEMPORARY_FAILURE']:
                return {"id": delivery_id, "status": delivery.status, "error_code": "invalid_status"}

            if delivery.next_attempt_at and delivery.next_attempt_at > now:
                return {"id": delivery_id, "status": delivery.status, "error_code": "not_due"}

            if delivery.attempt_count >= config['max_attempts']:
                delivery.status = 'PERMANENT_FAILURE'
                delivery.last_error_code = 'max_attempts_reached'
                delivery.next_attempt_at = None
                delivery.save()
                return {"id": delivery_id, "status": "PERMANENT_FAILURE", "error_code": "max_attempts_reached"}

            if not config['enabled']:
                delivery.status = 'SKIPPED'
                delivery.last_error_code = 'email_configuration_invalid'
                delivery.next_attempt_at = None
                delivery.save()
                return {"id": delivery_id, "status": "SKIPPED", "error_code": "email_configuration_invalid"}

            if delivery.recipient_count != config['recipient_count'] or delivery.recipient_set_hash != config['recipient_set_hash']:
                delivery.status = 'SKIPPED'
                delivery.last_error_code = 'recipient_configuration_changed'
                delivery.next_attempt_at = None
                delivery.save()
                return {"id": delivery_id, "status": "SKIPPED", "error_code": "recipient_configuration_changed"}

            delivery.status = 'SENDING'
            delivery.last_attempt_at = now
            delivery.save()

            severity = delivery.severity_snapshot
            recipients = config['recipients']
            from_email = config['from_email']
            dashboard_url = config['dashboard_url']

    except WebPushOperationalAlertEmailDelivery.DoesNotExist:
        return {"id": delivery_id, "status": "NOT_FOUND", "error_code": "not_found"}

    try:
        subject = f"[{severity}] {delivery.event_type} - Alerta Web Push: {delivery.code_snapshot}"
        text_content = f"Alerta {delivery.code_snapshot} ({severity})\nStatus: {delivery.event_type}\n\nAcesse o painel: {dashboard_url}"
        msg = EmailMultiAlternatives(subject, text_content, from_email, recipients)
        msg.send(fail_silently=False)

        with transaction.atomic():
            delivery = WebPushOperationalAlertEmailDelivery.objects.select_for_update().get(id=delivery_id)
            if delivery.status == 'SENDING':
                delivery.status = 'SENT'
                delivery.next_attempt_at = None
                delivery.sent_at = now
                delivery.attempt_count += 1
                delivery.save()
            return {"id": delivery.id, "status": delivery.status, "error_code": None}

    except SMTPAuthenticationError:
        with transaction.atomic():
            delivery = WebPushOperationalAlertEmailDelivery.objects.select_for_update().get(id=delivery_id)
            return _handle_email_failure(delivery, 'smtp_authentication_failed', config)
    except SMTPRecipientsRefused:
        with transaction.atomic():
            delivery = WebPushOperationalAlertEmailDelivery.objects.select_for_update().get(id=delivery_id)
            return _handle_email_failure(delivery, 'recipient_rejected', config)
    except (ConnectionError, TimeoutError):
        with transaction.atomic():
            delivery = WebPushOperationalAlertEmailDelivery.objects.select_for_update().get(id=delivery_id)
            return _handle_email_failure(delivery, 'email_backend_unavailable', config)
    except (SMTPException, SMTPSenderRefused):
        with transaction.atomic():
            delivery = WebPushOperationalAlertEmailDelivery.objects.select_for_update().get(id=delivery_id)
            return _handle_email_failure(delivery, 'smtp_temporary_failure', config)
    except Exception:
        with transaction.atomic():
            delivery = WebPushOperationalAlertEmailDelivery.objects.select_for_update().get(id=delivery_id)
            return _handle_email_failure(delivery, 'unexpected_email_error', config)

def process_due_web_push_operational_alert_email_deliveries(limit: int = 50, *, execute: bool = False) -> dict:
    if not execute:
        return {"processed": 0, "results": []}

    now = timezone.now()
    deliveries = WebPushOperationalAlertEmailDelivery.objects.filter(
        status__in=['PENDING', 'TEMPORARY_FAILURE']
    ).filter(
        models.Q(next_attempt_at__isnull=True) | models.Q(next_attempt_at__lte=now)
    ).order_by('status', 'created_at')[:limit]

    results = []
    for d in deliveries:
        try:
            res = send_web_push_alert_email_delivery(d.id)
            results.append(res)
        except Exception:
            results.append({"id": d.id, "status": "ERROR", "error_code": "critical_processor_failure"})

    return {"processed": len(results), "results": results}
