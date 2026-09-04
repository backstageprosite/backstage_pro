import os
import re
import unicodedata
from decimal import Decimal
from datetime import date
from typing import Optional, Dict, Any
from dataclasses import dataclass
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True)
class AsaasConfig:
    environment: str
    base_url: str
    api_key: Optional[str]
    webhook_token: Optional[str]

    @classmethod
    def from_settings(cls) -> "AsaasConfig":
        env = getattr(settings, "ASAAS_ENVIRONMENT", None) or os.getenv("ASAAS_ENVIRONMENT", "sandbox")
        env = str(env).strip().lower()
        if env not in ("sandbox", "production"):
            env = "sandbox"

        default_base_url = (
            "https://api-sandbox.asaas.com/v3"
            if env == "sandbox"
            else "https://api.asaas.com/v3"
        )

        raw_base_url = getattr(settings, "ASAAS_BASE_URL", None) or os.getenv("ASAAS_BASE_URL") or default_base_url
        base_url = str(raw_base_url).strip()

        # Prioriza settings sobre os.environ se explicitamente definido
        if hasattr(settings, "ASAAS_API_KEY"):
            raw_api_key = settings.ASAAS_API_KEY
        else:
            raw_api_key = os.getenv("ASAAS_API_KEY", None)
        api_key = str(raw_api_key).strip() if raw_api_key else None

        if hasattr(settings, "ASAAS_WEBHOOK_TOKEN"):
            raw_webhook_token = settings.ASAAS_WEBHOOK_TOKEN
        else:
            raw_webhook_token = os.getenv("ASAAS_WEBHOOK_TOKEN", None)
        webhook_token = str(raw_webhook_token).strip() if raw_webhook_token else None

        return cls(
            environment=env,
            base_url=base_url,
            api_key=api_key,
            webhook_token=webhook_token
        )

    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_key.strip())


def normalize_band_slug(band_name: str) -> str:
    """
    Gera slug limpo para a banda conforme especificação:
    - "Banda Mambolada" -> mambolada
    - "Duas Medidas" -> duasmedidas
    - lowercase, sem acentos, sem hífens, sem espaços, sem prefixo "Banda " inicial.
    """
    if not band_name:
        return ""

    name = band_name.strip()
    name = re.sub(r'^(banda\s+)', '', name, flags=re.IGNORECASE).strip()
    normalized = unicodedata.normalize('NFKD', name)
    ascii_str = normalized.encode('ASCII', 'ignore').decode('ASCII').lower()
    slug = re.sub(r'[^a-z0-9]', '', ascii_str)
    return slug


def generate_unique_band_slug(band_name: str, current_band_id: Optional[int] = None) -> str:
    """
    Gera slug único para nova banda considerando colisões:
    mambolada -> mambolada2 -> mambolada3
    """
    from core.models import Band

    base_slug = normalize_band_slug(band_name) or "banda"
    slug = base_slug
    counter = 2

    qs = Band.objects.all()
    if current_band_id:
        qs = qs.exclude(pk=current_band_id)

    while qs.filter(slug=slug).exists():
        slug = f"{base_slug}{counter}"
        counter += 1

    return slug


def calculate_next_billing_date(start_date: date, cycle: str, periods_offset: int = 1) -> date:
    """
    Cálculo de data-base fixa preservando o dia original (ex: dia 03, dia 31).
    Trata meses com 28/29/30/31 dias e anos bissextos adequadamente.
    """
    if not start_date:
        return start_date

    orig_day = start_date.day
    orig_month = start_date.month
    orig_year = start_date.year

    if cycle == 'ANUAL':
        target_year = orig_year + periods_offset
        target_month = orig_month
    else:
        total_months = (orig_year * 12 + orig_month - 1) + periods_offset
        target_year = total_months // 12
        target_month = (total_months % 12) + 1

    import calendar
    max_days_in_target = calendar.monthrange(target_year, target_month)[1]
    target_day = min(orig_day, max_days_in_target)

    return date(target_year, target_month, target_day)


def extract_asaas_id(value: Any, expected_prefix: Optional[str] = None) -> Optional[str]:
    """
    Extrai e valida de forma segura um identificador escalar do Asaas.
    Rejeita estritamente:
    - dicts/listas sem ID inequívoco (ex: {'cycle': 'MONTHLY', ...})
    - objetos JSON serializados ou conversões cegas de str(dict)
    - valores vazios ou não strings
    - strings que contenham formatação de dict ('{', '}')

    Se expected_prefix for informado (ex: 'sub_', 'pay_', 'cus_', 'chk_'):
    - Garante que a string comece com o prefixo esperado.
    """
    if value is None:
        return None

    # Se for dict, só aceita se possuir a chave 'id' escalar válida
    if isinstance(value, dict):
        raw_id = value.get('id')
        if not raw_id or not isinstance(raw_id, str):
            return None
        value = raw_id

    # Não aceita tipos não string
    if not isinstance(value, str):
        return None

    s = value.strip()
    if not s:
        return None

    # Rejeita representações textuais de dicionários / objetos / JSON
    if s.startswith('{') or s.endswith('}') or ':' in s:
        return None

    if expected_prefix:
        if not s.startswith(expected_prefix):
            return None

    return s
