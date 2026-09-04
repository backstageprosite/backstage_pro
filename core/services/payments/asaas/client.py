import json
import logging
from typing import Dict, Any, Optional
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
