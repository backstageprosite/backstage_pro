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
                'placeholder': 'Ex: Banda Graveto',
                'required': True,
                'maxlength': '150',
            }),
            'responsible_name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'Ex: Carlos Oliveira',
                'required': True,
                'maxlength': '200',
            }),
            'cpf_cnpj': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': '000.000.000-00 ou 00.000.000/0000-00',
                'maxlength': '30',
            }),
            'email': forms.EmailInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'seuemail@exemplo.com',
                'required': True,
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': '(71) 99999-9999',
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

    def clean_cpf_cnpj(self):
        val = (self.cleaned_data.get('cpf_cnpj') or '').strip()
        return val

    def clean_phone(self):
        val = (self.cleaned_data.get('phone') or '').strip()
        return val

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
