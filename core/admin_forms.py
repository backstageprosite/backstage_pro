from decimal import Decimal
from django import forms
from django.db import models
from core.models import Band, User, BandSubscription, BillingRecord

class AdminBandForm(forms.ModelForm):
    class Meta:
        model = Band
        fields = ['name', 'slug', 'plan_type', 'logo', 'is_active']
        widgets = {
            'subscription_due_date': forms.DateInput(attrs={'type': 'date'}),
            'plan_type': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['plan_type'].initial = None

class AdminUserCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}), label='Senha')
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}), label='Confirmar Senha')

    class Meta:
        model = User
        # BP-PEND-62: band e role são gerenciados via UserBandMembership no admin_user_create
        fields = ['first_name', 'last_name', 'username', 'email', 'phone', 'is_active', 'is_staff']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control phone-mask'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }
        labels = {
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'username': 'Login',
            'email': 'E-mail',
            'phone': 'Telefone',
            'is_active': 'Usuário Ativo?',
            'is_staff': 'Acesso ao Painel Admin Geral (Staff)',
        }
        help_texts = {
            'phone': 'Se informado, você poderá enviar os dados de acesso pelo WhatsApp após o cadastro.',
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'email' in self.fields:
            self.fields['email'].required = False
        if 'phone' in self.fields:
            self.fields['phone'].required = False
        if 'is_active' in self.fields:
            self.fields['is_active'].required = False
            if not self.is_bound:
                self.fields['is_active'].initial = True

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm_password = cleaned_data.get('confirm_password')

        if password and confirm_password and password != confirm_password:
            self.add_error('confirm_password', 'As senhas não coincidem.')
            
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password'])
        # Nota: must_change_password baseado no role é definido no admin_user_create após criar memberships
        if commit:
            user.save()
        return user

class AdminUserEditForm(forms.ModelForm):
    class Meta:
        model = User
        # BP-PEND-62: band e role são gerenciados via UserBandMembership no admin_user_edit
        fields = ['first_name', 'last_name', 'username', 'email', 'phone', 'is_active', 'is_staff']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control phone-mask'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }
        labels = {
            'phone': 'Telefone',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'email' in self.fields:
            self.fields['email'].required = False
        if 'phone' in self.fields:
            self.fields['phone'].required = False

class AdminSubscriptionForm(forms.ModelForm):
    class Meta:
        model = BandSubscription
        fields = [
            'band', 'commercial_condition', 'billing_cycle', 'contracted_value', 
            'start_date', 'next_due_date', 'status', 'payment_method_preference', 'auto_renew',
            'financial_responsible_name', 'billing_phone', 'billing_email', 'internal_notes'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'next_due_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'commercial_condition' in self.fields:
            self.fields['commercial_condition'].label = 'Condição Comercial'
            self.fields['commercial_condition'].initial = BandSubscription.COMMERCIAL_CONDITION_PAID
        if 'contracted_value' in self.fields:
            self.fields['contracted_value'].required = False
        if 'payment_method_preference' in self.fields:
            self.fields['payment_method_preference'].required = False

    def clean(self):
        cleaned_data = super().clean()
        condition = cleaned_data.get('commercial_condition') or BandSubscription.COMMERCIAL_CONDITION_PAID

        # Se for edição de assinatura existente, travar conversão entre PAGO e PARCERIA
        if self.instance and self.instance.pk:
            original_condition = self.instance.commercial_condition
            if original_condition and condition != original_condition:
                raise forms.ValidationError(
                    "A alteração da condição comercial desta assinatura não pode ser realizada por este formulário."
                )

        if condition == BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP:
            # Força backend para Parceria
            cleaned_data['contracted_value'] = Decimal('0.00')
            cleaned_data['auto_renew'] = False
            if not cleaned_data.get('payment_method_preference'):
                cleaned_data['payment_method_preference'] = 'PIX'
        else:
            # Para PAGO, contracted_value e payment_method_preference são obrigatórios
            val = cleaned_data.get('contracted_value')
            if val is None:
                self.add_error('contracted_value', 'O valor contratado é obrigatório para assinaturas pagas.')
            if not cleaned_data.get('payment_method_preference'):
                self.add_error('payment_method_preference', 'A preferência de pagamento é obrigatória para assinaturas pagas.')

        return cleaned_data
        
    def save(self, commit=True):
        instance = super().save(commit=False)
        cycle_to_plan = {
            'MENSAL': 'Mensal',
            'BIMESTRAL': 'Bimestral',
            'TRIMESTRAL': 'Trimestral',
            'SEMESTRAL': 'Semestral',
            'ANUAL': 'Anual'
        }
        instance.plan_name = cycle_to_plan.get(instance.billing_cycle, 'Mensal')

        # Blindagem de backend mandatória para Parceria
        if instance.commercial_condition == BandSubscription.COMMERCIAL_CONDITION_PARTNERSHIP:
            instance.contracted_value = Decimal('0.00')
            instance.auto_renew = False

        if commit:
            instance.save()
        return instance

class AdminBillingRecordForm(forms.ModelForm):
    class Meta:
        model = BillingRecord
        fields = [
            'subscription', 'band', 'reference_period', 'amount', 
            'due_date', 'paid_date', 'status', 'payment_method', 
            'proof_file', 'notes'
        ]
        widgets = {
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'paid_date': forms.DateInput(attrs={'type': 'date'}),
        }

from core.models import Partner
from django.core.validators import FileExtensionValidator
from PIL import Image

class AdminPartnerForm(forms.ModelForm):
    image = forms.ImageField(
        label='Logomarca ou Imagem',
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=['png', 'jpg', 'jpeg', 'webp'])]
    )
    
    class Meta:
        model = Partner
        fields = ['name', 'segment', 'instagram', 'phone', 'image', 'is_active']
        
    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image:
            # Validação de tamanho (max 5MB)
            if hasattr(image, 'size') and image.size > 5 * 1024 * 1024:
                raise forms.ValidationError('A imagem não pode ultrapassar 5MB.')
            
            # Validação real com Pillow
            try:
                img = Image.open(image)
                img.verify() # Verifica se é uma imagem válida sem carregar na memória inteira
                
                # Rejeita SVG (Pillow não suporta SVG nativamente com verify, mas garantimos pelo formato)
                if img.format.lower() not in ['png', 'jpeg', 'jpg', 'webp']:
                    raise forms.ValidationError('Formato de imagem inválido. Use PNG, JPG ou WebP.')
            except Exception:
                raise forms.ValidationError('O arquivo enviado não é uma imagem válida.')
                
            # Resetar o ponteiro do arquivo após usar o Pillow
            image.seek(0)
            
        return image

from core.models import LandingPageBandLogo

class LandingPageBandLogoForm(forms.ModelForm):
    image = forms.ImageField(
        label='Logomarca',
        required=False,
        validators=[FileExtensionValidator(allowed_extensions=['png', 'jpg', 'jpeg', 'webp'])]
    )
    
    class Meta:
        model = LandingPageBandLogo
        fields = ['name', 'image', 'is_active']
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['image'].required = True

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not instance.pk and instance.display_order == 0:
            last_order = LandingPageBandLogo.objects.aggregate(models.Max('display_order'))['display_order__max']
            instance.display_order = (last_order or 0) + 1
        if commit:
            instance.save()
        return instance
            

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if name:
            name = name.strip()
            if not name:
                raise forms.ValidationError('O nome não pode ficar vazio.')
        return name

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image:
            if hasattr(image, 'size') and image.size > 5 * 1024 * 1024:
                raise forms.ValidationError('A imagem não pode ultrapassar 5MB.')
            
            try:
                img = Image.open(image)
                if img.width != 1548 or img.height != 529:
                    raise forms.ValidationError('A imagem deve possuir exatamente 1548 × 529 pixels.')
                
                img.verify() 
                
                if img.format.lower() not in ['png', 'jpeg', 'webp', 'jpg']:
                    raise forms.ValidationError('Formato de imagem inválido. Use PNG, JPG ou WebP.')
            except forms.ValidationError as e:
                raise e
            except Exception:
                raise forms.ValidationError('O arquivo enviado não é uma imagem válida.')
                
            image.seek(0)
            
        return image


class SystemPlanPricingForm(forms.ModelForm):
    class Meta:
        from core.models import SystemSettings
        model = SystemSettings
        fields = ['plan_basic_monthly', 'plan_basic_annual', 'plan_advanced_monthly', 'plan_advanced_annual']
        widgets = {
            'plan_basic_monthly': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'plan_basic_annual': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'plan_advanced_monthly': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'plan_advanced_annual': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
        }
        labels = {
            'plan_basic_monthly': 'Mensal (R$)',
            'plan_basic_annual': 'Anual (R$)',
            'plan_advanced_monthly': 'Mensal (R$)',
            'plan_advanced_annual': 'Anual (R$)',
        }
