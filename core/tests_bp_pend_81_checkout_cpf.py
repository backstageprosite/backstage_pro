from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from core.models import SignupOrder, SystemSettings
from core.forms_checkout import SignupOrderForm

class ResponsibleCpfCheckoutBpPend81Tests(TestCase):
    def setUp(self):
        self.client = Client(headers={'host': 'localhost'})
        self.settings = SystemSettings.get_settings()
        self.settings.plan_advanced_monthly = Decimal('49.90')
        self.settings.save()
        self.valid_cpf_1 = '03220864503'
        self.valid_cpf_1_formatted = '032.208.645-03'

    def test_01_all_four_checkout_links_render_responsible_cpf_correctly(self):
        """1. Os quatro links de checkout devem renderizar responsible_cpf com maxlength=14, inputmode=numeric e formatCpf."""
        four_links = [
            reverse('checkout') + '?plano=basico&ciclo=mensal',
            reverse('checkout') + '?plano=basico&ciclo=anual',
            reverse('checkout') + '?plano=avancado&ciclo=mensal',
            reverse('checkout') + '?plano=avancado&ciclo=anual',
        ]
        for url in four_links:
            with self.subTest(url=url):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200)
                content = resp.content.decode('utf-8')
                self.assertIn('name="responsible_cpf"', content)
                self.assertIn('maxlength="14"', content)
                self.assertIn('inputmode="numeric"', content)
                self.assertIn('formatCpf', content)
                self.assertIn('id_responsible_cpf', content)

    def test_02_backend_accepts_and_normalizes_11_digits_formatted_cpf(self):
        """2. Backend recebe CPF formatado com 11 dígitos (032.208.645-03) e normaliza para 11 dígitos limpos."""
        form_data = {
            'band_name': 'Banda Alfa',
            'responsible_name': 'Carlos Silva',
            'responsible_cpf': self.valid_cpf_1_formatted,
            'cpf_cnpj': '12.345.678/0001-95',
            'email': 'carlos@alfa.com',
            'phone': '71999887766',
            'postal_code': '41720-000',
            'address': 'Rua Alfa',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
            'plan_type': 'AVANCADO',
            'billing_cycle': 'MENSAL',
        }
        form = SignupOrderForm(data=form_data)
        self.assertTrue(form.is_valid(), f"Erros no formulário: {form.errors}")
        self.assertEqual(form.cleaned_data['responsible_cpf'], self.valid_cpf_1)

    def test_03_backend_rejects_invalid_cpf(self):
        """3. Backend rejeita CPF inválido matematicamente ou com quantidade incorreta."""
        form_data = {
            'band_name': 'Banda Beta',
            'responsible_name': 'Carlos Silva',
            'responsible_cpf': '032.208.645-99',  # Dígitos verificadores incorretos
            'cpf_cnpj': '12.345.678/0001-95',
            'email': 'carlos@beta.com',
            'phone': '71999887766',
            'postal_code': '41720-000',
            'address': 'Rua Beta',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
            'plan_type': 'AVANCADO',
            'billing_cycle': 'MENSAL',
        }
        form = SignupOrderForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn('responsible_cpf', form.errors)
        self.assertIn('CPF do responsável inválido', form.errors['responsible_cpf'][0])

    def test_04_field_rejects_12th_digit_or_truncated_length(self):
        """4. Backend rejeita CPF com 12 dígitos ou incompleto (ex: 9 dígitos)."""
        form_data_9 = {
            'band_name': 'Banda Gama',
            'responsible_name': 'Carlos Silva',
            'responsible_cpf': '032.208.645',  # Apenas 9 dígitos
            'cpf_cnpj': '12.345.678/0001-95',
            'email': 'carlos@gama.com',
            'phone': '71999887766',
            'postal_code': '41720-000',
            'address': 'Rua Gama',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
            'plan_type': 'AVANCADO',
            'billing_cycle': 'MENSAL',
        }
        form9 = SignupOrderForm(data=form_data_9)
        self.assertFalse(form9.is_valid())
        self.assertIn('responsible_cpf', form9.errors)

        form_data_12 = form_data_9.copy()
        form_data_12['responsible_cpf'] = '032.208.645-031'  # 12 dígitos
        form12 = SignupOrderForm(data=form_data_12)
        self.assertFalse(form12.is_valid())
        self.assertIn('responsible_cpf', form12.errors)

    def test_05_cpf_cnpj_cobranca_is_independent_and_not_regressed(self):
        """5. CPF/CNPJ de cobrança permanece independente e aceita CNPJ (14 dígitos) ou CPF (11 dígitos)."""
        form_data = {
            'band_name': 'Banda Delta',
            'responsible_name': 'Carlos Silva',
            'responsible_cpf': self.valid_cpf_1_formatted,
            'cpf_cnpj': '12.345.678/0001-95',  # CNPJ de cobrança
            'email': 'carlos@delta.com',
            'phone': '71999887766',
            'postal_code': '41720-000',
            'address': 'Rua Delta',
            'address_number': '10',
            'province': 'Centro',
            'city': 'Salvador',
            'state': 'BA',
            'plan_type': 'AVANCADO',
            'billing_cycle': 'MENSAL',
        }
        form = SignupOrderForm(data=form_data)
        self.assertTrue(form.is_valid(), f"Erros: {form.errors}")
        self.assertEqual(form.cleaned_data['responsible_cpf'], self.valid_cpf_1)
        self.assertEqual(form.cleaned_data['cpf_cnpj'], '12345678000195')
