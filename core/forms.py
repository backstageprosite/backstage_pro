from django import forms
from django.forms import inlineformset_factory
from .models import FinancialReceipt, User, Contact, Show, ContractDocument, ShowPayment, ShowTeamCost

class FinancialReceiptForm(forms.ModelForm):
    class Meta:
        model = FinancialReceipt
        fields = ['description', 'date', 'category', 'value', 'file']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Pagamento Van, Alimentação'}),
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            'category': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Logística, Alimentação'}),
            'value': forms.TextInput(attrs={'class': 'form-control money-mask'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['file'].required = False

class ShowPaymentForm(forms.ModelForm):
    class Meta:
        model = ShowPayment
        fields = ['description', 'value', 'expected_date', 'receipt_date', 'payment_method', 'file', 'observations']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Sinal 50%, Liquidação'}),
            'value': forms.TextInput(attrs={'class': 'form-control money-mask'}),
            'expected_date': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            'receipt_date': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            'payment_method': forms.Select(attrs={'class': 'form-select'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
            'observations': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Observações internas (opcional)'}),
        }

class ShowTeamCostForm(forms.ModelForm):
    class Meta:
        model = ShowTeamCost
        fields = ['name', 'date', 'role', 'value']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: João Silva'}),
            'date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'role': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Técnico de Som'}),
            'value': forms.TextInput(attrs={'class': 'form-control money-mask'}),
        }

class ContractDocumentForm(forms.ModelForm):
    class Meta:
        model = ContractDocument
        fields = ['description', 'file']
        widgets = {
            'description': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Contrato Assinado, Alvará'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
        }

class UserForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Senha de acesso'}),
        label='Senha',
        required=True
    )
    
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'role', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Danniel'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Vieira'}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: danniel_v'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemplo.com'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }
        labels = {
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'username': 'Nome de Usuário (Login)',
            'email': 'E-mail',
            'role': 'Perfil de Acesso',
            'is_active': 'Usuário Ativo?',
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user

class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'role', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Danniel'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Vieira'}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: danniel_v', 'readonly': 'readonly'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemplo.com'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }
        labels = {
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'username': 'Nome de Usuário (Login)',
            'email': 'E-mail',
            'role': 'Perfil de Acesso',
            'is_active': 'Usuário Ativo?',
        }

class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['name', 'contact_type', 'phone', 'email', 'location', 'link', 'notes']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do contato'}),
            'contact_type': forms.Select(attrs={'class': 'form-select'}),
            'phone': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemplo.com'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Endereço ou Local'}),
            'link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://exemplo.com'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Observações (opcional)'}),
        }

class ShowForm(forms.ModelForm):
    class Meta:
        model = Show
        fields = [
            'title', 'event_name', 'status', 'date',
            'city', 'venue', 'address', 'address_link', 'attractions',
            'contractor_name', 'contractor_phone', 'contract_type', 'fee', 'payment_status',
            'departure_location', 'departure_location_link', 'departure_time', 'arrival_time',
            'travel_time', 'distance_km', 'soundcheck_time', 'show_time', 'show_end_time', 'duration',
            'transport', 'flight_number', 'airline', 'transport_contact', 'boarding_time',
            'accommodation', 'accommodation_link', 'accommodation_contact', 'checkout_time',
            'dressing_room', 'dressing_room_contact', 'catering', 'wardrobe', 'transfer', 'transfer_contact',
            'sound_system', 'sound_contact', 'lighting_system', 'lighting_contact', 'led_system', 'led_contact',
            'backline', 'backline_contact', 'pyrotechnics', 'pyrotechnics_contact', 'generator_system', 'generator_contact',
            'loaders_system', 'loaders_contact', 'local_production', 'local_production_contact',
            'internal_notes', 'band_notes'
        ]
        widgets = {
            # Principal
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome da Turnê ou Show principal'}),
            'event_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Festival de Verão'}),
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            # Localização
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'venue': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Parque de Exposições'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'address_link': forms.URLInput(attrs={'class': 'form-control'}),
            'attractions': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            # Financeiro
            'contractor_name': forms.TextInput(attrs={'class': 'form-control'}),
            'contractor_phone': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            'contract_type': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Bilheteria, Prefeitura'}),
            'fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'payment_status': forms.Select(attrs={'class': 'form-select'}),
            # Cronograma
            'departure_location': forms.TextInput(attrs={'class': 'form-control'}),
            'departure_location_link': forms.URLInput(attrs={'class': 'form-control'}),
            'departure_time': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'arrival_time': forms.DateTimeInput(format='%Y-%m-%dT%H:%M', attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'travel_time': forms.TextInput(attrs={'class': 'form-control'}),
            'distance_km': forms.TextInput(attrs={'class': 'form-control'}),
            'soundcheck_time': forms.TimeInput(format='%H:%M', attrs={'class': 'form-control', 'type': 'time'}),
            'show_time': forms.TimeInput(format='%H:%M', attrs={'class': 'form-control', 'type': 'time'}),
            'show_end_time': forms.TimeInput(format='%H:%M', attrs={'class': 'form-control', 'type': 'time'}),
            'duration': forms.TextInput(attrs={'class': 'form-control'}),
            # Logística
            'transport': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'flight_number': forms.TextInput(attrs={'class': 'form-control'}),
            'airline': forms.TextInput(attrs={'class': 'form-control'}),
            'transport_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            'boarding_time': forms.TimeInput(format='%H:%M', attrs={'class': 'form-control', 'type': 'time'}),
            'accommodation': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'accommodation_link': forms.URLInput(attrs={'class': 'form-control'}),
            'accommodation_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            'checkout_time': forms.TimeInput(format='%H:%M', attrs={'class': 'form-control', 'type': 'time'}),
            'dressing_room': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'dressing_room_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            'catering': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'wardrobe': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'transfer': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'transfer_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            
            # Técnica
            'local_production': forms.TextInput(attrs={'class': 'form-control'}),
            'local_production_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            
            'sound_system': forms.TextInput(attrs={'class': 'form-control'}),
            'sound_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            
            'lighting_system': forms.TextInput(attrs={'class': 'form-control'}),
            'lighting_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            
            'led_system': forms.TextInput(attrs={'class': 'form-control'}),
            'led_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            
            'backline': forms.TextInput(attrs={'class': 'form-control'}),
            'backline_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            
            'pyrotechnics': forms.TextInput(attrs={'class': 'form-control'}),
            'pyrotechnics_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            
            'generator_system': forms.TextInput(attrs={'class': 'form-control'}),
            'generator_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            
            'loaders_system': forms.TextInput(attrs={'class': 'form-control'}),
            'loaders_contact': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            
            # Observações
            'internal_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'band_notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

# Formsets para a aba de Anexos
ContractDocumentFormSet = inlineformset_factory(
    Show, 
    ContractDocument, 
    form=ContractDocumentForm,
    extra=1,
    can_delete=True
)

FinancialReceiptFormSet = inlineformset_factory(
    Show, 
    FinancialReceipt, 
    form=FinancialReceiptForm,
    extra=1,
    can_delete=True
)
