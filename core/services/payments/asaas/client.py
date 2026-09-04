import json
import logging
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, List
from core.services.payments.base import AsaasConfig

logger = logging.getLogger(__name__)


class AsaasClient:
    """
    Cliente HTTP seguro para comunicação com a API do Asaas.
    Nunca expõe chaves ou tokens em logs e respeita a URL configurada.
    """
    def __init__(self, config: Optional[AsaasConfig] = None):
        self.config = config or AsaasConfig.from_settings()

    @property
    def base_url(self) -> str:
        return self.config.base_url.rstrip('/')

    def get_headers(self) -> Dict[str, str]:
        user_agent = f"BackstagePro/1.0 (Django; {self.config.environment})"
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "User-Agent": user_agent
        }
        if self.config.api_key:
            headers["access_token"] = self.config.api_key
        return headers

    @staticmethod
    def encode_payload(data: Dict[str, Any]) -> bytes:
        """
        Serializa payload garantindo preservação estrita de UTF-8 sem escape ASCII.
        """
        return json.dumps(data, ensure_ascii=False).encode('utf-8')

    def get_payments_by_checkout(self, checkout_id: str) -> List[Dict[str, Any]]:
        """
        Consulta cobranças geradas por uma sessão de Checkout no Asaas.
        Testa os parâmetros suportados (checkoutSessionId e checkout).
        """
        if not checkout_id or not self.config.api_key:
            return []

        encoded_id = urllib.parse.quote(str(checkout_id))
        for param in ('checkoutSessionId', 'checkout', 'checkoutSession'):
            url = f"{self.base_url}/payments?{param}={encoded_id}&limit=10"
            req = urllib.request.Request(url, headers=self.get_headers())
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    payments = data.get('data', [])
                    if payments:
                        return payments
            except Exception as e:
                logger.warning("Falha na consulta de payments por %s=%s: %s", param, checkout_id, str(e))

        return []

    def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """
        Consulta dados de uma assinatura diretamente na API do Asaas.
        """
        if not subscription_id or not self.config.api_key:
            return None

        encoded_id = urllib.parse.quote(str(subscription_id))
        url = f"{self.base_url}/subscriptions/{encoded_id}"
        req = urllib.request.Request(url, headers=self.get_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            logger.warning("Falha na consulta de assinatura %s no Asaas: %s", subscription_id, str(e))
            return None

    def get_payments_by_subscription(self, subscription_id: str) -> List[Dict[str, Any]]:
        """
        Consulta pagamentos vinculados a uma assinatura no Asaas.
        """
        if not subscription_id or not self.config.api_key:
            return []

        encoded_id = urllib.parse.quote(str(subscription_id))
        url = f"{self.base_url}/subscriptions/{encoded_id}/payments"
        req = urllib.request.Request(url, headers=self.get_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data.get('data', [])
        except Exception as e:
            logger.warning("Falha na consulta de pagamentos da assinatura %s no Asaas: %s", subscription_id, str(e))
            return []

