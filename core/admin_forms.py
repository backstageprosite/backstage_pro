from django import forms
from core.models import Band, User, BandSubscription, BillingRecord

class AdminBandForm(forms.ModelForm):
    class Meta:
        model = Band
        fields = ['name', 'slug', 'logo', 'subscription_plan', 'subscription_status', 'subscription_due_date', 'is_active']
        widgets = {
            'subscription_due_date': forms.DateInput(attrs={'type': 'date'}),
        }

class AdminUserCreateForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Senha'}), label='Senha')
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirmar Senha'}), label='Confirmar Senha')

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'band', 'role', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Danniel'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Vieira'}),
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: danniel_v'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemplo.com'}),
            'band': forms.Select(attrs={'class': 'form-select'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'}),
        }
        labels = {
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'username': 'Login',
            'email': 'E-mail',
            'band': 'Banda Vinculada',
            'role': 'Perfil de Acesso',
            'is_active': 'Usuário Ativo?',
        }
        
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
        if commit:
            user.save()
        return user

class AdminUserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'band', 'role', 'is_active']

class AdminSubscriptionForm(forms.ModelForm):
    class Meta:
        model = BandSubscription
        fields = [
            'band', 'plan_name', 'billing_cycle', 'contracted_value', 
            'start_date', 'next_due_date', 'status', 'payment_method_preference',
            'financial_responsible_name', 'billing_phone', 'billing_email', 'internal_notes'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'next_due_date': forms.DateInput(attrs={'type': 'date'}),
        }

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
        fields = ['name', 'image', 'display_order', 'is_active']
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields['image'].required = True
            

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
