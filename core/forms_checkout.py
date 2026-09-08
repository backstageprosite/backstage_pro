import re
from django import forms
from core.models import SignupOrder

class SignupOrderForm(forms.ModelForm):
    PAYMENT_METHOD_CHOICES = (
        ('CREDIT_CARD', 'Cartão de Crédito'),
        ('PIX', 'PIX'),
    )

    idempotency_token = forms.CharField(
        widget=forms.HiddenInput(),
        required=False
    )
    payment_method = forms.ChoiceField(
        choices=PAYMENT_METHOD_CHOICES,
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        initial='CREDIT_CARD',
        required=False,
    )

    class Meta:
        model = SignupOrder
        fields = [
            'band_name',
            'responsible_name',
            'cpf_cnpj',
            'email',
            'phone',
            'plan_type',
            'billing_cycle',
        ]
        widgets = {
            'band_name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'required': True,
                'maxlength': '150',
            }),
            'responsible_name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'required': True,
                'maxlength': '200',
            }),
            'cpf_cnpj': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'required': True,
                'maxlength': '30',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control form-control-lg',
                'required': True,
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'required': True,
                'maxlength': '30',
            }),
            'plan_type': forms.HiddenInput(),
            'billing_cycle': forms.HiddenInput(),
        }
        error_messages = {
            'band_name': {
                'required': 'Informe o nome da banda ou artista.',
            },
            'responsible_name': {
                'required': 'Informe o nome do responsável.',
            },
            'email': {
                'required': 'Informe um e-mail válido para contato e ativação.',
            },
            'phone': {
                'required': 'Informe um telefone ou WhatsApp para contato.',
            },
            'cpf_cnpj': {
                'required': 'Informe um CPF ou CNPJ válido.',
            },
        }

    def clean_band_name(self):
        val = (self.cleaned_data.get('band_name') or '').strip()
        if not val:
            raise forms.ValidationError("Informe o nome da banda ou artista.")
        return val

    def clean_responsible_name(self):
        val = (self.cleaned_data.get('responsible_name') or '').strip()
        if not val:
            raise forms.ValidationError("Informe o nome do responsável.")
        return val

    def clean_email(self):
        val = (self.cleaned_data.get('email') or '').strip().lower()
        if not val:
            raise forms.ValidationError("Informe um e-mail válido para contato e ativação.")
        return val

    @staticmethod
    def _validate_cpf(digits: str) -> bool:
        if len(digits) != 11 or digits == digits[0] * 11:
            return False
        # Primeiro dígito verificador
        soma = sum(int(digits[i]) * (10 - i) for i in range(9))
        d1 = 11 - (soma % 11)
        d1 = 0 if d1 >= 10 else d1
        if int(digits[9]) != d1:
            return False
        # Segundo dígito verificador
        soma = sum(int(digits[i]) * (11 - i) for i in range(10))
        d2 = 11 - (soma % 11)
        d2 = 0 if d2 >= 10 else d2
        return int(digits[10]) == d2

    @staticmethod
    def _validate_cnpj(digits: str) -> bool:
        if len(digits) != 14 or digits == digits[0] * 14:
            return False
        # Primeiro dígito verificador
        weights1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = sum(int(digits[i]) * weights1[i] for i in range(12))
        d1 = soma % 11
        d1 = 0 if d1 < 2 else (11 - d1)
        if int(digits[12]) != d1:
            return False
        # Segundo dígito verificador
        weights2 = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        soma = sum(int(digits[i]) * weights2[i] for i in range(13))
        d2 = soma % 11
        d2 = 0 if d2 < 2 else (11 - d2)
        return int(digits[13]) == d2

    def clean_cpf_cnpj(self):
        val = (self.cleaned_data.get('cpf_cnpj') or '').strip()
        if not val:
            raise forms.ValidationError("Informe um CPF ou CNPJ válido.")
        
        digits = re.sub(r'\D', '', val)
        if len(digits) == 11:
            if not self._validate_cpf(digits):
                raise forms.ValidationError("CPF inválido. Verifique os dígitos informados.")
            return digits
        elif len(digits) == 14:
            if not self._validate_cnpj(digits):
                raise forms.ValidationError("CNPJ inválido. Verifique os dígitos informados.")
            return digits
        else:
            raise forms.ValidationError("Informe um CPF válido (11 dígitos) ou CNPJ válido (14 dígitos).")

    VALID_BRAZILIAN_DDDS = {
        '11', '12', '13', '14', '15', '16', '17', '18', '19',
        '21', '22', '24', '27', '28',
        '31', '32', '33', '34', '35', '37', '38',
        '41', '42', '43', '44', '45', '46', '47', '48', '49',
        '51', '53', '54', '55',
        '61', '62', '63', '64', '65', '66', '67', '68', '69',
        '71', '73', '74', '75', '77', '79',
        '81', '82', '83', '84', '85', '86', '87', '88', '89',
        '91', '92', '93', '94', '95', '96', '97', '98', '99',
    }

    def clean_phone(self):
        val = (self.cleaned_data.get('phone') or '').strip()
        if not val:
            raise forms.ValidationError("Informe um telefone ou WhatsApp para contato.")
        
        digits = re.sub(r'\D', '', val)
        # Aceita telefones brasileiros:
        # com DDD: 10 dígitos (fixo) ou 11 dígitos (celular)
        # com DDI 55 + DDD: 12 dígitos (fixo) ou 13 dígitos (celular)
        if len(digits) in (12, 13) and digits.startswith('55'):
            digits = digits[2:]

        if len(digits) not in (10, 11):
            raise forms.ValidationError("Informe um telefone ou WhatsApp válido com DDD (Ex: 71 99999-9999).")

        # Verifica se o DDD é um Código Nacional brasileiro real
        ddd = digits[:2]
        if ddd not in self.VALID_BRAZILIAN_DDDS:
            raise forms.ValidationError("DDD inválido informado no telefone.")

        return digits

    def clean_plan_type(self):
        val = (self.cleaned_data.get('plan_type') or '').strip().upper()
        if val not in ('BASICO', 'AVANCADO'):
            raise forms.ValidationError("Plano selecionado inválido.")
        return val

    def clean_billing_cycle(self):
        val = (self.cleaned_data.get('billing_cycle') or '').strip().upper()
        if val not in ('MENSAL', 'ANUAL'):
            raise forms.ValidationError("Ciclo de cobrança selecionado inválido.")
        return val

    def clean_payment_method(self):
        val = (self.cleaned_data.get('payment_method') or 'CREDIT_CARD').strip().upper()
        if val not in ('CREDIT_CARD', 'PIX'):
            return 'CREDIT_CARD'
        return val
