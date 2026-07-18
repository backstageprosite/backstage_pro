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

import logging
from core.services.web_push_delivery import send_web_push_delivery

logger = logging.getLogger(__name__)

from django.db.models import Case, When, Value, IntegerField, DateTimeField, F
from django.db.models.functions import Coalesce

def find_retryable_web_push_deliveries(band_slug: str, status_filter: str, retry_after_minutes: int, max_attempts: int, limit: int):
    now = timezone.now()
    age_threshold = now - datetime.timedelta(minutes=retry_after_minutes)
    
    qs = WebPushDelivery.objects.filter(
        notification__band__slug=band_slug,
        attempt_count__lt=max_attempts,
        subscription__is_active=True,
        subscription__user=F('notification__recipient'),
        subscription__band=F('notification__band'),
        subscription__service_worker_scope=f"/{band_slug}/"
    ).filter(
        Q(subscription__expiration_time__isnull=True) | Q(subscription__expiration_time__gt=now)
    )

    if status_filter == 'pending':
        qs = qs.filter(
            status=WebPushDelivery.StatusChoices.PENDING,
            updated_at__lt=age_threshold
        )
    elif status_filter == 'temporary-failure':
        qs = qs.filter(
            status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE
        ).filter(
            Q(last_attempt_at__isnull=False, last_attempt_at__lt=age_threshold) |
            Q(last_attempt_at__isnull=True, updated_at__lt=age_threshold)
        )
    else:  # both
        qs = qs.filter(
            Q(
                status=WebPushDelivery.StatusChoices.PENDING,
                updated_at__lt=age_threshold
            ) |
            Q(
                status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
                last_attempt_at__isnull=False, last_attempt_at__lt=age_threshold
            ) |
            Q(
                status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
                last_attempt_at__isnull=True, updated_at__lt=age_threshold
            )
        )

    qs = qs.annotate(
        status_order=Case(
            When(status=WebPushDelivery.StatusChoices.PENDING, then=Value(1)),
            When(status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        ),
        sort_time=Case(
            When(
                status=WebPushDelivery.StatusChoices.PENDING,
                then=F("updated_at"),
            ),
            When(
                status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
                then=Coalesce("last_attempt_at", "updated_at"),
            ),
            default=F("updated_at"),
            output_field=DateTimeField(),
        )
    ).order_by('status_order', 'sort_time', 'pk')[:limit]

    results = []
    for delivery in qs.values('id', 'status', 'attempt_count', 'updated_at', 'last_attempt_at'):
        ts = delivery['last_attempt_at'] or delivery['updated_at']
        results.append({
            "delivery_id": delivery['id'],
            "status": delivery['status'],
            "attempt_count": delivery['attempt_count'],
            "timestamp": ts.isoformat() if ts else None,
            "band_slug": band_slug
        })
    return results

def retry_web_push_deliveries(*, band_slug: str, status_filter: str = 'both', retry_after_minutes: int = 15, max_attempts: int = 3, limit: int = 50, execute: bool = False):
    if not band_slug:
        raise ValueError("band_slug is required")
        
    if status_filter not in ['pending', 'temporary-failure', 'both']:
        raise ValueError("status_filter must be pending, temporary-failure, or both")
        
    if not isinstance(retry_after_minutes, (int, float)) or retry_after_minutes < 5 or retry_after_minutes > 10080:
        raise ValueError("retry_after_minutes deve estar entre 5 e 10080")
        
    if not isinstance(max_attempts, int) or max_attempts < 1 or max_attempts > 10:
        raise ValueError("max_attempts deve estar entre 1 e 10")
        
    if not isinstance(limit, int) or limit < 1 or limit > 500:
        raise ValueError("limit deve estar entre 1 e 500")

    candidates = find_retryable_web_push_deliveries(band_slug, status_filter, retry_after_minutes, max_attempts, limit)
    
    summary = {
        "mode": "EXECUTE" if execute else "DRY-RUN",
        "candidates": len(candidates),
        "attempted": 0,
        "sent": 0,
        "temporary_failure": 0,
        "permanent_failure": 0,
        "skipped": 0,
        "skipped_concurrent": 0,
        "skipped_max_attempts": 0,
        "skipped_inactive_subscription": 0,
        "skipped_expired_subscription": 0,
        "unexpected_error": 0,
        "processed_ids": []
    }

    if not execute:
        summary["processed_ids"] = [c["delivery_id"] for c in candidates]
        return {"candidates": candidates, "summary": summary}
        
    now = timezone.now()
    age_threshold = now - datetime.timedelta(minutes=retry_after_minutes)

    for cand in candidates:
        d_id = cand["delivery_id"]
        initial_status = cand["status"]
        
        try:
            if initial_status == WebPushDelivery.StatusChoices.TEMPORARY_FAILURE:
                updated = WebPushDelivery.objects.filter(
                    pk=d_id,
                    status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
                    attempt_count__lt=max_attempts,
                    notification__band__slug=band_slug,
                    subscription__is_active=True,
                    subscription__user=F('notification__recipient'),
                    subscription__band=F('notification__band'),
                    subscription__service_worker_scope=f"/{band_slug}/"
                ).filter(
                    Q(subscription__expiration_time__isnull=True) | Q(subscription__expiration_time__gt=now)
                ).filter(
                    Q(last_attempt_at__isnull=False, last_attempt_at__lt=age_threshold) |
                    Q(last_attempt_at__isnull=True, updated_at__lt=age_threshold)
                ).update(
                    status=WebPushDelivery.StatusChoices.PENDING,
                    error_code="",
                    last_http_status=None,
                    updated_at=now
                )
                
                if updated == 1:
                    res = send_web_push_delivery(d_id)
                    summary["attempted"] += 1
                else:
                    summary["skipped_concurrent"] += 1
                    continue
                    
            elif initial_status == WebPushDelivery.StatusChoices.PENDING:
                valid = WebPushDelivery.objects.filter(
                    pk=d_id,
                    status=WebPushDelivery.StatusChoices.PENDING,
                    attempt_count__lt=max_attempts,
                    notification__band__slug=band_slug,
                    subscription__is_active=True,
                    subscription__user=F('notification__recipient'),
                    subscription__band=F('notification__band'),
                    subscription__service_worker_scope=f"/{band_slug}/",
                    updated_at__lt=age_threshold
                ).filter(
                    Q(subscription__expiration_time__isnull=True) | Q(subscription__expiration_time__gt=now)
                ).exists()
                
                if not valid:
                    summary["skipped_concurrent"] += 1
                    continue
                
                res = send_web_push_delivery(d_id)
                summary["attempted"] += 1
            else:
                summary["skipped_concurrent"] += 1
                continue
                
            if res == "SENT":
                summary["sent"] += 1
            elif res == "TEMPORARY_FAILURE":
                summary["temporary_failure"] += 1
            elif res == "PERMANENT_FAILURE":
                summary["permanent_failure"] += 1
            elif res in ["SKIPPED", "SKIPPED/ALREADY_CLAIMED", "SKIPPED/ALREADY_FINALIZED"]:
                summary["skipped"] += 1
            else:
                summary["unexpected_error"] += 1
                
            summary["processed_ids"].append(d_id)
            
        except Exception as e:
            summary["unexpected_error"] += 1
            logger.warning(
                f"Unexpected error retrying web push delivery: {e}",
                extra={
                    "delivery_id": d_id,
                    "band_slug": band_slug,
                    "previous_status": initial_status,
                    "attempt_count": cand["attempt_count"]
                },
                exc_info=True
            )
            
    return {"candidates": candidates, "summary": summary}

def build_web_push_operational_alerts(snapshot):
    alerts = []
    
    success_rate = snapshot["deliveries"]["rates"]["success_rate"]
    stale_sending_count = snapshot["anomalies"]["stale_sending_count"]
    stale_pending_count = snapshot["anomalies"]["stale_pending_count"]
    recent_tf = snapshot["deliveries"]["recent_window"]["temporary_failure"]
    recent_pf = snapshot["deliveries"]["recent_window"]["permanent_failure"]
    active_expired_subs = snapshot["anomalies"]["active_expired_subscriptions_count"]
    active_subs_with_failures = snapshot["subscriptions"]["active_with_failures"]
    created_in_window = snapshot["deliveries"]["recent_window"]["created"]
    completed = snapshot["deliveries"]["rates"]["completed"]
    
    if stale_sending_count > 0:
        alerts.append({
            "code": "stale_sending",
            "severity": "CRITICAL",
            "title": "SENDING Obsoletas",
            "message": f"Há {stale_sending_count} envios travados no estado SENDING por mais tempo que o permitido.",
            "count": stale_sending_count,
            "recommended_action": "Execute primeiro o dry-run com: python manage.py web_push_reconcile_stale ..."
        })
        
    if success_rate is not None and success_rate < 0.80 and completed > 0:
        alerts.append({
            "code": "critical_success_rate",
            "severity": "CRITICAL",
            "title": "Taxa de Sucesso Crítica",
            "message": f"A taxa de sucesso está em {success_rate * 100:.1f}%, abaixo do aceitável (80%).",
            "count": completed,
            "recommended_action": "Analise as PERMANENT_FAILURE recentes para identificar se há problemas de configuração."
        })
        
    if stale_pending_count > 0:
        alerts.append({
            "code": "stale_pending",
            "severity": "WARNING",
            "title": "PENDING Obsoletas",
            "message": f"Existem {stale_pending_count} notificações aguardando envio além da janela esperada.",
            "count": stale_pending_count,
            "recommended_action": "Execute primeiro o dry-run com: python manage.py web_push_retry ..."
        })
        
    if recent_tf > 0:
        alerts.append({
            "code": "recent_temporary_failures",
            "severity": "WARNING",
            "title": "Falhas Temporárias Recentes",
            "message": f"Houve {recent_tf} falhas de rede ou timeout recentes.",
            "count": recent_tf,
            "recommended_action": "Execute primeiro o dry-run com: python manage.py web_push_retry ..."
        })
        
    if recent_pf > 0:
        alerts.append({
            "code": "recent_permanent_failures",
            "severity": "WARNING",
            "title": "Falhas Permanentes Recentes",
            "message": f"Houve {recent_pf} inscrições inválidas ou revogadas recentemente.",
            "count": recent_pf,
            "recommended_action": "Nenhuma ação automática. Inscrições foram desativadas."
        })
        
    if active_expired_subs > 0:
        alerts.append({
            "code": "active_expired_subscriptions",
            "severity": "WARNING",
            "title": "Inscrições Expiradas Ativas",
            "message": f"Existem {active_expired_subs} inscrições ativas vencidas.",
            "count": active_expired_subs,
            "recommended_action": "Verifique a rotina de saneamento de inscrições."
        })
        
    if active_subs_with_failures > 0:
        alerts.append({
            "code": "active_subscriptions_with_failures",
            "severity": "WARNING",
            "title": "Inscrições Ativas com Falhas",
            "message": f"{active_subs_with_failures} inscrições possuem falhas.",
            "count": active_subs_with_failures,
            "recommended_action": "Acompanhe para confirmar se virarão PERMANENT_FAILURE."
        })
        
    if success_rate is not None and 0.80 <= success_rate < 0.95:
        alerts.append({
            "code": "moderate_success_rate",
            "severity": "WARNING",
            "title": "Atenção na Taxa de Sucesso",
            "message": f"A taxa de sucesso está em {success_rate * 100:.1f}%, abaixo do ideal (95%).",
            "count": completed,
            "recommended_action": "Monitore os relatórios nas próximas horas."
        })
        
    if created_in_window == 0:
        alerts.append({
            "code": "no_recent_deliveries",
            "severity": "INFO",
            "title": "Sem Envios Recentes",
            "message": "Nenhum novo envio foi registrado nesta janela de horas.",
            "count": 0,
            "recommended_action": "Nenhuma ação necessária se não houve shows."
        })
    elif completed == 0 or success_rate is None:
        alerts.append({
            "code": "no_completed_deliveries",
            "severity": "INFO",
            "title": "Aguardando Conclusões",
            "message": "Não há envios concluídos na janela selecionada para calcular a taxa de sucesso.",
            "count": 0,
            "recommended_action": "Aguarde os retornos de rede."
        })

    return alerts

def list_recent_problematic_deliveries(band_slug: str | None = None, hours: int = 24, limit: int = 50) -> list[dict]:
    from django.utils import timezone
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(hours=hours)

    qs = WebPushDelivery.objects.filter(
        created_at__gte=cutoff,
        status__in=[
            WebPushDelivery.StatusChoices.PENDING,
            WebPushDelivery.StatusChoices.SENDING,
            WebPushDelivery.StatusChoices.TEMPORARY_FAILURE,
            WebPushDelivery.StatusChoices.PERMANENT_FAILURE,
            WebPushDelivery.StatusChoices.SKIPPED
        ]
    )
    if band_slug:
        qs = qs.filter(notification__band__slug=band_slug)
        
    qs = qs.annotate(
        status_order=Case(
            When(status=WebPushDelivery.StatusChoices.SENDING, then=Value(1)),
            When(status=WebPushDelivery.StatusChoices.PENDING, then=Value(2)),
            When(status=WebPushDelivery.StatusChoices.TEMPORARY_FAILURE, then=Value(3)),
            When(status=WebPushDelivery.StatusChoices.PERMANENT_FAILURE, then=Value(4)),
            When(status=WebPushDelivery.StatusChoices.SKIPPED, then=Value(5)),
            default=Value(6),
            output_field=IntegerField(),
        )
    ).order_by('status_order', '-updated_at', 'pk')[:limit]
    
    results = []
    for d in qs.values(
        'id', 
        'notification__band__slug', 
        'status', 
        'attempt_count', 
        'last_http_status', 
        'error_code', 
        'created_at', 
        'updated_at', 
        'last_attempt_at'
    ):
        results.append({
            "delivery_id": d['id'],
            "band_slug": d['notification__band__slug'],
            "status": d['status'],
            "attempt_count": d['attempt_count'],
            "last_http_status": d['last_http_status'],
            "error_code": d['error_code'],
            "created_at": d['created_at'].isoformat() if d['created_at'] else None,
            "updated_at": d['updated_at'].isoformat() if d['updated_at'] else None,
            "last_attempt_at": d['last_attempt_at'].isoformat() if d['last_attempt_at'] else None
        })
        
    return results
