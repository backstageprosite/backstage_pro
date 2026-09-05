import json
import logging
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional, List, Tuple
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

    def get_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        """
        Consulta dados de uma cobranca diretamente na API do Asaas via GET /v3/payments/{id}.
        """
        if not payment_id or not self.config.api_key:
            return None

        encoded_id = urllib.parse.quote(str(payment_id))
        url = f"{self.base_url}/payments/{encoded_id}"
        req = urllib.request.Request(url, headers=self.get_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            logger.warning("Falha na consulta de cobranca %s no Asaas: %s", payment_id, str(e))
            return None

    def get_installment(self, installment_id: str) -> Optional[Dict[str, Any]]:
        """
        Consulta dados de um parcelamento diretamente na API do Asaas via GET /v3/installments/{id}.
        """
        if not installment_id or not self.config.api_key:
            return None

        encoded_id = urllib.parse.quote(str(installment_id))
        url = f"{self.base_url}/installments/{encoded_id}"
        req = urllib.request.Request(url, headers=self.get_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode('utf-8'))
        except Exception as e:
            logger.warning("Falha na consulta de parcelamento %s no Asaas: %s", installment_id, str(e))
            return None

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

    def cancel_subscription(self, subscription_id: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Cancela uma assinatura na API do Asaas utilizando DELETE /v3/subscriptions/{id}.
        Retorna (sucesso: bool, resposta_ou_erro: dict).
        """
        if not subscription_id:
            return False, {"error": "subscription_id_invalido"}
        if not self.config.api_key:
            return False, {"error": "api_key_ausente"}

        encoded_id = urllib.parse.quote(str(subscription_id))
        url = f"{self.base_url}/subscriptions/{encoded_id}"
        req = urllib.request.Request(url, headers=self.get_headers(), method='DELETE')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status_code = resp.getcode()
                raw_body = resp.read().decode('utf-8')
                data = json.loads(raw_body) if raw_body else {}
                if status_code in (200, 204) or data.get('deleted') is True:
                    return True, data
                return False, data
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode('utf-8') if hasattr(http_err, 'read') else str(http_err)
            try:
                err_data = json.loads(raw_err)
            except Exception:
                err_data = {"error": str(http_err), "status": http_err.code}
            logger.warning("Erro HTTP %s ao cancelar assinatura %s no Asaas: %s", http_err.code, subscription_id, raw_err)
            return False, err_data
        except Exception as e:
            logger.warning("Exceção ao cancelar assinatura %s no Asaas: %s", subscription_id, str(e))
            return False, {"error": str(e)}

    def update_subscription(self, subscription_id: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Atualiza dados de uma assinatura na API do Asaas utilizando PUT /v3/subscriptions/{id}.
        Ex: atualizar nextDueDate.
        Retorna (sucesso: bool, resposta_ou_erro: dict).
        """
        if not subscription_id:
            return False, {"error": "subscription_id_invalido"}
        if not self.config.api_key:
            return False, {"error": "api_key_ausente"}

        encoded_id = urllib.parse.quote(str(subscription_id))
        url = f"{self.base_url}/subscriptions/{encoded_id}"
        body_bytes = self.encode_payload(data)
        req = urllib.request.Request(url, data=body_bytes, headers=self.get_headers(), method='PUT')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status_code = resp.getcode()
                raw_body = resp.read().decode('utf-8')
                resp_data = json.loads(raw_body) if raw_body else {}
                if status_code in (200, 204) or resp_data.get('id'):
                    return True, resp_data
                return False, resp_data
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode('utf-8') if hasattr(http_err, 'read') else str(http_err)
            try:
                err_data = json.loads(raw_err)
            except Exception:
                err_data = {"error": str(http_err), "status": http_err.code}
            logger.warning("Erro HTTP %s ao atualizar assinatura %s no Asaas: %s", http_err.code, subscription_id, raw_err)
            return False, err_data
        except Exception as e:
            logger.warning("Exceção ao atualizar assinatura %s no Asaas: %s", subscription_id, str(e))
            return False, {"error": str(e)}

    def update_payment(self, payment_id: str, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Atualiza dados de uma cobrança na API do Asaas utilizando PUT /v3/payments/{id}.
        Ex: atualizar dueDate.
        Retorna (sucesso: bool, resposta_ou_erro: dict).
        """
        if not payment_id:
            return False, {"error": "payment_id_invalido"}
        if not self.config.api_key:
            return False, {"error": "api_key_ausente"}

        encoded_id = urllib.parse.quote(str(payment_id))
        url = f"{self.base_url}/payments/{encoded_id}"
        body_bytes = self.encode_payload(data)
        req = urllib.request.Request(url, data=body_bytes, headers=self.get_headers(), method='PUT')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status_code = resp.getcode()
                raw_body = resp.read().decode('utf-8')
                resp_data = json.loads(raw_body) if raw_body else {}
                if status_code in (200, 204) or resp_data.get('id'):
                    return True, resp_data
                return False, resp_data
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode('utf-8') if hasattr(http_err, 'read') else str(http_err)
            try:
                err_data = json.loads(raw_err)
            except Exception:
                err_data = {"error": str(http_err), "status": http_err.code}
            logger.warning("Erro HTTP %s ao atualizar cobrança %s no Asaas: %s", http_err.code, payment_id, raw_err)
            return False, err_data
        except Exception as e:
            logger.warning("Exceção ao atualizar cobrança %s no Asaas: %s", payment_id, str(e))
            return False, {"error": str(e)}

    def create_installment(self, data: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """
        Cria um parcelamento no Asaas via POST /v3/installments sem informar cartão/token.
        Retorna (sucesso: bool, resposta_ou_erro: dict).
        """
        if not self.config.live_payments_enabled:
            logger.warning("Operação de escrita financeira bloqueada pelo safety gate (PAYMENTS_LIVE_ENABLED=False).")
            return False, {"error": "payments_live_disabled", "message": "Operações financeiras públicas estão temporariamente desabilitadas."}

        if not self.config.api_key:
            return False, {"error": "api_key_ausente"}

        url = f"{self.base_url}/installments"

        body_bytes = self.encode_payload(data)
        req = urllib.request.Request(url, data=body_bytes, headers=self.get_headers(), method='POST')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status_code = resp.getcode()
                raw_body = resp.read().decode('utf-8')
                resp_data = json.loads(raw_body) if raw_body else {}
                if status_code in (200, 201) or resp_data.get('id'):
                    return True, resp_data
                return False, resp_data
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode('utf-8') if hasattr(http_err, 'read') else str(http_err)
            try:
                err_data = json.loads(raw_err)
            except Exception:
                err_data = {"error": str(http_err), "status": http_err.code}
            logger.warning("Erro HTTP %s ao criar parcelamento no Asaas: %s", http_err.code, raw_err)
            return False, err_data
        except Exception as e:
            logger.warning("Exceção ao criar parcelamento no Asaas: %s", str(e))
            return False, {"error": str(e)}

    def get_payments_by_installment(self, installment_id: str) -> List[Dict[str, Any]]:
        """
        Consulta as parcelas (payments) vinculadas a um installment via GET /v3/payments?installment={id}.
        """
        if not installment_id or not self.config.api_key:
            return []

        encoded_id = urllib.parse.quote(str(installment_id))
        url = f"{self.base_url}/payments?installment={encoded_id}&limit=50"
        req = urllib.request.Request(url, headers=self.get_headers())
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                return data.get('data', [])
        except Exception as e:
            logger.warning("Falha na consulta de parcelas do installment %s no Asaas: %s", installment_id, str(e))
            return []

    def pay_with_credit_card(self, payment_id: str, credit_card_token: str) -> Tuple[bool, Dict[str, Any]]:
        """
        Realiza o pagamento de uma cobrança com cartão tokenizado via POST /v3/payments/{id}/payWithCreditCard.
        O credit_card_token nunca é logado ou exposto em exceções.
        Retorna (sucesso: bool, resposta_ou_erro: dict).
        """
        if not self.config.live_payments_enabled:
            logger.warning("Operação payWithCreditCard bloqueada pelo safety gate (PAYMENTS_LIVE_ENABLED=False).")
            return False, {"error": "payments_live_disabled", "message": "Operações financeiras públicas estão temporariamente desabilitadas."}

        if not payment_id:
            return False, {"error": "payment_id_invalido"}
        if not credit_card_token:
            return False, {"error": "credit_card_token_ausente"}
        if not self.config.api_key:
            return False, {"error": "api_key_ausente"}


        encoded_id = urllib.parse.quote(str(payment_id))
        url = f"{self.base_url}/payments/{encoded_id}/payWithCreditCard"
        payload = {"creditCardToken": credit_card_token}
        body_bytes = self.encode_payload(payload)
        req = urllib.request.Request(url, data=body_bytes, headers=self.get_headers(), method='POST')
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status_code = resp.getcode()
                raw_body = resp.read().decode('utf-8')
                resp_data = json.loads(raw_body) if raw_body else {}
                if status_code in (200, 201) or resp_data.get('status') in ('CONFIRMED', 'RECEIVED'):
                    return True, resp_data
                return False, resp_data
        except urllib.error.HTTPError as http_err:
            raw_err = http_err.read().decode('utf-8') if hasattr(http_err, 'read') else str(http_err)
            try:
                err_data = json.loads(raw_err)
            except Exception:
                err_data = {"error": str(http_err), "status": http_err.code}
            logger.warning("Erro HTTP %s ao executar payWithCreditCard na cobrança %s no Asaas", http_err.code, payment_id)
            return False, err_data
        except Exception as e:
            logger.warning("Exceção ao executar payWithCreditCard na cobrança %s no Asaas: %s", payment_id, str(e))
            return False, {"error": str(e)}
