from typing import Dict, Any, Optional

class BasePaymentGateway:
    """
    Interface abstrata do gateway de pagamento para permitir troca transparente no futuro.
    """
    def create_customer(self, name: str, email: str, cpf_cnpj: str, phone: str = None) -> Dict[str, Any]:
        raise NotImplementedError

    def create_checkout(self, plan_name: str, value: float, cycle: str, customer_id: str, external_reference: str) -> Dict[str, Any]:
        raise NotImplementedError

    def create_subscription(self, customer_id: str, plan_name: str, value: float, cycle: str) -> Dict[str, Any]:
        raise NotImplementedError

    def get_payment(self, payment_id: str) -> Dict[str, Any]:
        raise NotImplementedError
