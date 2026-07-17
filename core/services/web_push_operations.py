import datetime
from django.db.models import Count, Q, F
from django.utils import timezone
from core.models import WebPushDelivery, WebPushSubscription

def find_stale_pending_deliveries(stale_minutes: int, band_slug=None):
    if not isinstance(stale_minutes, (int, float)) or stale_minutes < 5 or stale_minutes > 10080:
        raise ValueError("stale_minutes deve estar entre 5 e 10080")
    
    stale_before = timezone.now() - datetime.timedelta(minutes=stale_minutes)
    
    qs = WebPushDelivery.objects.filter(
        status=WebPushDelivery.StatusChoices.PENDING,
        created_at__lt=stale_before
    )
    if band_slug:
        qs = qs.filter(notification__band__slug=band_slug)
        
    return qs

def find_stale_sending_deliveries(stale_minutes: int, band_slug=None):
    if not isinstance(stale_minutes, (int, float)) or stale_minutes < 5 or stale_minutes > 10080:
        raise ValueError("stale_minutes deve estar entre 5 e 10080")
        
    stale_before = timezone.now() - datetime.timedelta(minutes=stale_minutes)
    
    qs = WebPushDelivery.objects.filter(
        status=WebPushDelivery.StatusChoices.SENDING
    ).filter(
        Q(last_attempt_at__isnull=False, last_attempt_at__lt=stale_before) |
        Q(last_attempt_at__isnull=True, updated_at__lt=stale_before)
    )
    if band_slug:
        qs = qs.filter(notification__band__slug=band_slug)
        
    return qs

def build_web_push_health_snapshot(*, window_hours=24, stale_pending_minutes=10, stale_sending_minutes=15, band_slug=None):
    now = timezone.now()
    window_start = now - datetime.timedelta(hours=window_hours)
    
    base_del = WebPushDelivery.objects.all()
    base_sub = WebPushSubscription.objects.all()
    
    if band_slug:
        from core.models import Band
        if not Band.objects.filter(slug=band_slug).exists():
            raise ValueError("Banda não encontrada")
        base_del = base_del.filter(notification__band__slug=band_slug)
        base_sub = base_sub.filter(band__slug=band_slug)
        
    totals = base_del.aggregate(
        total=Count('id'),
        pending=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.PENDING)),
        sending=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.SENDING)),
        sent=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.SENT)),
        temporary_failure=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE)),
        permanent_failure=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.PERMANENT_FAILURE)),
        skipped=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.SKIPPED)),
    )
    
    recent = base_del.filter(created_at__gte=window_start).aggregate(
        created=Count('id'),
        sent=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.SENT)),
        temporary_failure=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE)),
        permanent_failure=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.PERMANENT_FAILURE)),
        skipped=Count('id', filter=Q(status=WebPushDelivery.StatusChoices.SKIPPED)),
    )
    
    completed = (totals['sent'] or 0) + (totals['temporary_failure'] or 0) + (totals['permanent_failure'] or 0) + (totals['skipped'] or 0)
    if completed > 0:
        success_rate = (totals['sent'] or 0) / completed
    else:
        success_rate = None
        
    stale_pending_count = find_stale_pending_deliveries(stale_pending_minutes, band_slug).count()
    stale_sending_count = find_stale_sending_deliveries(stale_sending_minutes, band_slug).count()
    
    pending_without_attempt = base_del.filter(status=WebPushDelivery.StatusChoices.PENDING, attempt_count__gt=0).count()
    sending_without_last_attempt = base_del.filter(status=WebPushDelivery.StatusChoices.SENDING, last_attempt_at__isnull=True).count()
    sent_without_sent_at = base_del.filter(status=WebPushDelivery.StatusChoices.SENT, sent_at__isnull=True).count()
    active_expired_subscriptions = base_sub.filter(is_active=True, expiration_time__lte=now).count()
    
    subs = base_sub.aggregate(
        total=Count('id'),
        active=Count('id', filter=Q(is_active=True)),
        inactive=Count('id', filter=Q(is_active=False)),
        active_with_failures=Count('id', filter=Q(is_active=True, failure_count__gt=0)),
        success_recent=Count('id', filter=Q(deliveries__status=WebPushDelivery.StatusChoices.SENT, deliveries__updated_at__gte=window_start), distinct=True),
        failure_recent=Count('id', filter=Q(deliveries__status__in=[WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, WebPushDelivery.StatusChoices.PERMANENT_FAILURE], deliveries__updated_at__gte=window_start), distinct=True),
    )
    
    oldest_pending = base_del.filter(status=WebPushDelivery.StatusChoices.PENDING).order_by('created_at').first()
    oldest_sending = base_del.filter(status=WebPushDelivery.StatusChoices.SENDING).order_by('last_attempt_at').first()
    last_success = base_del.filter(status=WebPushDelivery.StatusChoices.SENT).order_by('-sent_at').first()
    last_failure = base_del.filter(status__in=[WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, WebPushDelivery.StatusChoices.PERMANENT_FAILURE]).order_by('-updated_at').first()
    
    return {
        "deliveries": {
            "total": {
                "total": totals['total'] or 0,
                "PENDING": totals['pending'] or 0,
                "SENDING": totals['sending'] or 0,
                "SENT": totals['sent'] or 0,
                "TEMPORARY_FAILURE": totals['temporary_failure'] or 0,
                "PERMANENT_FAILURE": totals['permanent_failure'] or 0,
                "SKIPPED": totals['skipped'] or 0,
            },
            "recent_window": {
                "created": recent['created'] or 0,
                "sent": recent['sent'] or 0,
                "temporary_failure": recent['temporary_failure'] or 0,
                "permanent_failure": recent['permanent_failure'] or 0,
                "skipped": recent['skipped'] or 0,
            },
            "rates": {
                "completed": completed,
                "success_rate": success_rate,
            }
        },
        "anomalies": {
            "stale_pending_count": stale_pending_count,
            "stale_sending_count": stale_sending_count,
            "pending_without_attempt_count": pending_without_attempt,
            "sending_without_last_attempt_count": sending_without_last_attempt,
            "sent_without_sent_at_count": sent_without_sent_at,
            "active_expired_subscriptions_count": active_expired_subscriptions,
        },
        "subscriptions": {
            "total": subs['total'] or 0,
            "active": subs['active'] or 0,
            "inactive": subs['inactive'] or 0,
            "active_with_failures": subs['active_with_failures'] or 0,
            "expired_but_active": active_expired_subscriptions,
            "recent_success": subs['success_recent'] or 0,
            "recent_failure": subs['failure_recent'] or 0,
        },
        "antiquity": {
            "oldest_pending_created_at": oldest_pending.created_at.isoformat() if oldest_pending else None,
            "oldest_sending_last_attempt_at": oldest_sending.last_attempt_at.isoformat() if oldest_sending and oldest_sending.last_attempt_at else (oldest_sending.updated_at.isoformat() if oldest_sending else None),
            "last_success_at": last_success.sent_at.isoformat() if last_success and last_success.sent_at else None,
            "last_failure_at": last_failure.updated_at.isoformat() if last_failure else None,
        }
    }


def reconcile_stale_sending_deliveries(stale_minutes: int, limit: int = 100, execute: bool = False, band_slug=None):
    if not isinstance(limit, int) or limit < 1 or limit > 1000:
        raise ValueError("limit deve estar entre 1 e 1000")
        
    candidatas = find_stale_sending_deliveries(stale_minutes, band_slug).order_by(
        F('last_attempt_at').asc(nulls_last=True),
        'updated_at',
        'pk'
    )[:limit]
    
    ids = list(candidatas.values_list('id', flat=True))
    
    if not execute:
        return {
            "dry_run": True,
            "found_count": len(ids),
            "reconciled_count": 0,
            "ids": ids,
        }
        
    reconciled = 0
    stale_before = timezone.now() - datetime.timedelta(minutes=stale_minutes)
    now = timezone.now()
    
    for d_id in ids:
        updated = WebPushDelivery.objects.filter(
            pk=d_id,
            status=WebPushDelivery.StatusChoices.SENDING,
        ).filter(
            Q(last_attempt_at__isnull=False, last_attempt_at__lt=stale_before) |
            Q(last_attempt_at__isnull=True, updated_at__lt=stale_before)
        ).update(
            status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
            error_code="stale_sending",
            last_http_status=None,
            updated_at=now
        )
        if updated > 0:
            reconciled += 1
            
    return {
        "dry_run": False,
        "found_count": len(ids),
        "reconciled_count": reconciled,
        "ids": ids,
    }
