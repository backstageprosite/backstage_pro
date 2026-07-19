import datetime
from django.utils import timezone
from django.db import transaction, IntegrityError
from core.models import WebPushOperationalAlert, Band
from core.services.web_push_operations import build_web_push_health_snapshot, build_web_push_operational_alerts

def plan_web_push_operational_alerts(*, band_slug: str | None, window_hours: int, stale_pending_minutes: int, stale_sending_minutes: int) -> dict:
    snapshot = build_web_push_health_snapshot(
        window_hours=window_hours,
        stale_pending_minutes=stale_pending_minutes,
        stale_sending_minutes=stale_sending_minutes,
        band_slug=band_slug
    )
    alerts = build_web_push_operational_alerts(snapshot)
    
    scope_type = "BAND" if band_slug else "GLOBAL"
    
    if scope_type == "GLOBAL":
        existing_qs = WebPushOperationalAlert.objects.filter(scope_type="GLOBAL")
    else:
        existing_qs = WebPushOperationalAlert.objects.filter(scope_type="BAND", band__slug=band_slug)
        
    existing_incidents = {inc.dedupe_key: inc for inc in existing_qs}
    
    to_open = []
    to_update = []
    to_resolve = []
    unchanged = []
    
    active_keys = set()
    for alert in alerts:
        if alert['severity'] == 'INFO':
            continue
            
        code = alert['code']
        if scope_type == "GLOBAL":
            dedupe_key = f"global:{code}"
        else:
            band = Band.objects.get(slug=band_slug)
            dedupe_key = f"band:{band.id}:{code}"
            
        active_keys.add(dedupe_key)
        
        alert_data = {
            "scope_type": scope_type,
            "band_slug": band_slug,
            "dedupe_key": dedupe_key,
            "code": code,
            "severity": alert["severity"],
            "title": alert["title"],
            "message": alert["message"],
            "recommended_action": alert["recommended_action"],
            "current_count": alert["count"]
        }
        
        if dedupe_key not in existing_incidents:
            to_open.append(alert_data)
        else:
            inc = existing_incidents[dedupe_key]
            if inc.status == WebPushOperationalAlert.StatusChoices.ACTIVE:
                if (inc.severity == alert["severity"] and 
                    inc.title == alert["title"] and 
                    inc.message == alert["message"] and 
                    inc.recommended_action == alert["recommended_action"] and 
                    inc.current_count == alert["count"]):
                    unchanged.append(alert_data)
                else:
                    to_update.append(alert_data)
            else:
                to_update.append(alert_data)

    for key, inc in existing_incidents.items():
        if inc.status == WebPushOperationalAlert.StatusChoices.ACTIVE and key not in active_keys:
            to_resolve.append({
                "dedupe_key": key,
                "code": inc.code,
                "scope_type": scope_type,
                "band_slug": band_slug,
            })
            
    return {
        "version": "1.0",
        "scope": {
            "scope_type": scope_type,
            "band_slug": band_slug
        },
        "snapshot_summary": {
            "success_rate": snapshot["deliveries"]["rates"]["success_rate"],
            "completed": snapshot["deliveries"]["rates"]["completed"],
        },
        "to_open": to_open,
        "to_update": to_update,
        "to_resolve": to_resolve,
        "unchanged": unchanged,
        "summary": {
            "to_open": len(to_open),
            "to_update": len(to_update),
            "to_resolve": len(to_resolve),
            "unchanged": len(unchanged),
        }
    }

def apply_web_push_operational_alert_plan(plan: dict, *, execute: bool = False) -> dict:
    if not isinstance(plan, dict):
        raise ValueError("Plan must be a dict")
        
    for key in ['to_open', 'to_update', 'to_resolve', 'unchanged']:
        if key not in plan:
            raise ValueError(f"Missing required key '{key}' in plan")
            
    scope = plan.get("scope", {})
    if not isinstance(scope, dict):
        raise ValueError("Scope must be a dict")
        
    scope_type = scope.get("scope_type")
    if scope_type not in ["GLOBAL", "BAND"]:
        raise ValueError("Invalid scope_type in plan")
        
    band_slug = scope.get("band_slug")
    if scope_type == "BAND" and not band_slug:
        raise ValueError("band_slug missing for BAND scope")
    
    # Valida items
    valid_severities = ["INFO", "WARNING", "CRITICAL"]
    for key in ['to_open', 'to_update', 'to_resolve', 'unchanged']:
        items = plan.get(key, [])
        if not isinstance(items, list):
            raise ValueError(f"{key} must be a list")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Items must be dicts")
            
            if "dedupe_key" not in item or not isinstance(item["dedupe_key"], str):
                raise ValueError("Invalid dedupe_key")
                
            if scope_type == "GLOBAL" and not item["dedupe_key"].startswith("global:"):
                raise ValueError("dedupe_key incompatible with GLOBAL scope")
                
            if scope_type == "BAND" and not item["dedupe_key"].startswith(f"band:{band_slug}:"):
                raise ValueError("dedupe_key incompatible with BAND scope")
            
            if "severity" in item and item["severity"] not in valid_severities:
                raise ValueError("Invalid severity")
                
            if "code" in item and not isinstance(item["code"], str):
                raise ValueError("Invalid code")

            # No cru datetimes allowed. Let's ensure no datetime values.
            for k, v in item.items():
                if hasattr(v, 'isoformat') and callable(getattr(v, 'isoformat')):
                    raise ValueError("Raw datetime found, dict must be JSON serializable primitive objects")

    if not execute:
        return {
            "mode": "DRY_RUN",
            "scopes_processed": 1,
            "opened": len(plan.get("to_open", [])),
            "updated": len(plan.get("to_update", [])),
            "resolved": len(plan.get("to_resolve", [])),
            "unchanged": len(plan.get("unchanged", [])),
            "errors": 0,
            "results": []
        }
        
    results = []
    opened = 0
    updated = 0
    resolved = 0
    unchanged = 0
    errors = 0
    
    band = None
    if scope_type == "BAND":
        band = Band.objects.get(slug=band_slug)
        
    now = timezone.now()
    
    for item in plan.get("to_open", []):
        try:
            with transaction.atomic():
                inc = WebPushOperationalAlert.objects.create(
                    scope_type=scope_type,
                    band=band,
                    dedupe_key=item["dedupe_key"],
                    code=item["code"],
                    severity=item["severity"],
                    status=WebPushOperationalAlert.StatusChoices.ACTIVE,
                    title=item["title"],
                    message=item["message"],
                    recommended_action=item["recommended_action"],
                    current_count=item["current_count"],
                    first_detected_at=now,
                    last_detected_at=now,
                    opened_count=1,
                    resolved_at=None
                )
                opened += 1
                results.append({"dedupe_key": item["dedupe_key"], "action": "opened"})
        except IntegrityError:
            try:
                with transaction.atomic():
                    inc = WebPushOperationalAlert.objects.select_for_update().get(dedupe_key=item["dedupe_key"])
                    if inc.status == WebPushOperationalAlert.StatusChoices.RESOLVED:
                        inc.status = WebPushOperationalAlert.StatusChoices.ACTIVE
                        inc.first_detected_at = now
                        inc.last_detected_at = now
                        inc.resolved_at = None
                        inc.opened_count += 1
                        updated += 1
                        action = "reopened"
                    else:
                        inc.last_detected_at = now
                        updated += 1
                        action = "updated"
                        
                    inc.severity = item["severity"]
                    inc.title = item["title"]
                    inc.message = item["message"]
                    inc.recommended_action = item["recommended_action"]
                    inc.current_count = item["current_count"]
                    inc.save()
                    results.append({"dedupe_key": item["dedupe_key"], "action": action})
            except Exception:
                errors += 1
                results.append({"dedupe_key": item["dedupe_key"], "action": "error", "error": "integrity_recovery_failed"})

    for item in plan.get("to_update", []):
        try:
            with transaction.atomic():
                inc = WebPushOperationalAlert.objects.select_for_update().get(dedupe_key=item["dedupe_key"])
                if inc.status == WebPushOperationalAlert.StatusChoices.RESOLVED:
                    inc.status = WebPushOperationalAlert.StatusChoices.ACTIVE
                    inc.first_detected_at = now
                    inc.resolved_at = None
                    inc.opened_count += 1
                
                inc.last_detected_at = now
                inc.severity = item["severity"]
                inc.title = item["title"]
                inc.message = item["message"]
                inc.recommended_action = item["recommended_action"]
                inc.current_count = item["current_count"]
                inc.save()
                updated += 1
                results.append({"dedupe_key": item["dedupe_key"], "action": "updated"})
        except Exception:
            errors += 1
            results.append({"dedupe_key": item["dedupe_key"], "action": "error"})

    for item in plan.get("unchanged", []):
        try:
            with transaction.atomic():
                inc = WebPushOperationalAlert.objects.select_for_update().get(dedupe_key=item["dedupe_key"])
                if inc.status == WebPushOperationalAlert.StatusChoices.ACTIVE:
                    inc.last_detected_at = now
                    inc.save(update_fields=["last_detected_at", "updated_at"])
                unchanged += 1
                results.append({"dedupe_key": item["dedupe_key"], "action": "unchanged"})
        except Exception:
            errors += 1
            results.append({"dedupe_key": item["dedupe_key"], "action": "error"})

    for item in plan.get("to_resolve", []):
        try:
            with transaction.atomic():
                inc = WebPushOperationalAlert.objects.select_for_update().get(dedupe_key=item["dedupe_key"])
                if inc.status == WebPushOperationalAlert.StatusChoices.ACTIVE:
                    inc.status = WebPushOperationalAlert.StatusChoices.RESOLVED
                    inc.resolved_at = now
                    inc.save()
                    resolved += 1
                    results.append({"dedupe_key": item["dedupe_key"], "action": "resolved"})
                else:
                    unchanged += 1
                    results.append({"dedupe_key": item["dedupe_key"], "action": "already_resolved"})
        except Exception:
            errors += 1
            results.append({"dedupe_key": item["dedupe_key"], "action": "error"})
            
    return {
        "mode": "EXECUTE",
        "scopes_processed": 1,
        "opened": opened,
        "updated": updated,
        "resolved": resolved,
        "unchanged": unchanged,
        "errors": errors,
        "results": results
    }
