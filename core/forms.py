from django import forms
from django.forms import inlineformset_factory
from .models import FinancialReceipt, User, Contact, Show, ContractDocument, ShowPayment, ShowTeamCost, RiderDocument

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
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Senha'}),
        label='Senha',
        required=True
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirmar Senha'}),
        label='Confirmar Senha',
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
            'username': 'Login',
            'email': 'E-mail',
            'role': 'Perfil de Acesso',
            'is_active': 'Usuário Ativo',
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
            'is_active': 'Usuário Ativo',
        }

class ContactForm(forms.ModelForm):
    class Meta:
        model = Contact
        fields = ['name', 'contact_type', 'phone', 'email', 'location', 'link', 'notes', 'public_information', 'is_shared_globally']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nome do contato'}),
            'contact_type': forms.Select(attrs={'class': 'form-select'}),
            'phone': forms.TextInput(attrs={'class': 'form-control phone-mask', 'maxlength': '15'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'email@exemplo.com'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Endereço ou Local'}),
            'link': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://exemplo.com'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Observações (opcional)'}),
            'public_information': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Informações públicas (opcional)'}),
            'is_shared_globally': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        help_texts = {
            'is_shared_globally': 'Os dados públicos deste contato ficarão visíveis para produtores e integrantes de todas as bandas cadastradas no Backstage Pro.'
        }
        labels = {
            'is_shared_globally': 'Compartilhar contato com o Banco de Dados Geral'
        }

    def clean(self):
        cleaned_data = super().clean()
        is_shared_globally = cleaned_data.get('is_shared_globally')
        phone = cleaned_data.get('phone')
        email = cleaned_data.get('email')

        if is_shared_globally:
            import re
            norm_phone = ""
            if phone:
                digits = re.sub(r'\D', '', phone)
                if digits.startswith('55') and len(digits) > 11:
                    digits = digits[2:]
                norm_phone = digits

            norm_email = ""
            if email:
                norm_email = email.strip().lower()

            qs = Contact.objects.filter(is_shared_globally=True)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            dup_found = False
            if norm_phone and qs.filter(normalized_phone=norm_phone).exists():
                dup_found = True
            elif norm_email and qs.filter(normalized_email=norm_email).exists():
                dup_found = True

            if dup_found:
                raise forms.ValidationError(
                    "Este contato já está cadastrado no Banco de Dados Geral e não pode ser compartilhado novamente.",
                    code='duplicate_shared_contact'
                )

        return cleaned_data

class ShowForm(forms.ModelForm):
    class Meta:
        model = Show
        fields = [
            'title', 'event_name', 'status', 'date',
            'city', 'venue', 'address', 'address_link', 'attractions',
            'contractor_name', 'contractor_phone', 'contract_type', 'fee', 'payment_status',
            'departure_location', 'departure_location_link', 'departure_time', 'arrival_time',
            'travel_time', 'distance_km', 'soundcheck_time', 'soundcheck_end_time', 'show_time', 'show_end_time', 'duration',
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
            'soundcheck_end_time': forms.TimeInput(format='%H:%M', attrs={'class': 'form-control', 'type': 'time'}),
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

from .models import BandDashboardPendingItem

class ShowChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.get_display_label()

class BandDashboardPendingItemForm(forms.ModelForm):
    show = ShowChoiceField(queryset=None, required=False, empty_label='Geral', widget=forms.Select(attrs={'class': 'form-select', 'style': 'border-radius: 8px;'}))
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control', 'style': 'border-radius: 8px;'}))
    class Meta:
        model = BandDashboardPendingItem
        fields = ['description', 'show', 'due_date']
    def __init__(self, *args, **kwargs):
        shows_qs = kwargs.pop('shows_qs', None)
        super().__init__(*args, **kwargs)
        self.fields['description'].widget.attrs.update({'class': 'form-control', 'rows': 3, 'placeholder': 'Digite a pendência...', 'maxlength': '500', 'style': 'border-radius: 8px; resize: none;'})
        if shows_qs is not None:
            self.fields['show'].queryset = shows_qs

class RiderDocumentForm(forms.ModelForm):
    class Meta:
        model = RiderDocument
        fields = ['name', 'file']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Rider de Luz, Mapa de Palco'}),
            'file': forms.FileInput(attrs={'class': 'form-control'}),
        }

from .models import Integrante

class IntegranteForm(forms.ModelForm):
    class Meta:
        model = Integrante
        fields = ['name', 'role', 'cpf', 'vehicle', 'category', 'pix_key', 'birth_date', 'miles_number']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'style': 'border-radius: 8px;'}),
            'role': forms.TextInput(attrs={'class': 'form-control', 'style': 'border-radius: 8px;'}),
            'cpf': forms.TextInput(attrs={'class': 'form-control cpf-mask', 'style': 'border-radius: 8px;'}),
            'vehicle': forms.TextInput(attrs={'class': 'form-control', 'style': 'border-radius: 8px;'}),
            'category': forms.Select(attrs={'class': 'form-select', 'style': 'border-radius: 8px;'}),
            'pix_key': forms.TextInput(attrs={'class': 'form-control', 'style': 'border-radius: 8px;'}),
            'birth_date': forms.TextInput(attrs={'class': 'form-control date-mask', 'style': 'border-radius: 8px;'}),
            'miles_number': forms.TextInput(attrs={'class': 'form-control', 'style': 'border-radius: 8px;'}),
        }
from core.models import RoomList, Room, Show
from django.utils import timezone
from datetime import date

class RoomListSelectShowForm(forms.Form):
    show_id = forms.ModelChoiceField(
        queryset=Show.objects.none(),
        label="Selecione o Show",
        widget=forms.Select(attrs={'class': 'form-select', 'style': 'border-radius: 8px;'})
    )

    def __init__(self, band, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # priorizar shows futuros ou ativos
        # excluir shows que já possuam Room List
        shows_with_room_list = RoomList.objects.filter(band=band).values_list('show_id', flat=True)
        self.fields['show_id'].queryset = Show.objects.filter(
            band=band,
            date__gte=date.today()
        ).exclude(id__in=shows_with_room_list).order_by('date')

class RoomListForm(forms.ModelForm):
    class Meta:
        model = RoomList
        fields = [
            'hotel_name', 'city', 'address', 'check_in', 'check_out',
            'contact', 'phone', 'notes', 'reservation_code'
        ]
        labels = {
            'hotel_name': 'Nome do hotel',
            'city': 'Cidade',
            'address': 'Endereço',
            'check_in': 'Check-in',
            'check_out': 'Check-out',
            'contact': 'Contato',
            'phone': 'Telefone',
            'notes': 'Observações',
            'reservation_code': 'Código da reserva',
        }
        widgets = {
            'hotel_name': forms.TextInput(attrs={'class': 'form-control'}),
            'city': forms.TextInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'check_in': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'check_out': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'contact': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'reservation_code': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned_data = super().clean()
        check_in = cleaned_data.get('check_in')
        check_out = cleaned_data.get('check_out')

        if check_in and check_out and check_out < check_in:
            self.add_error('check_out', 'O check-out não pode ser anterior ao check-in.')

        return cleaned_data

class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ['type', 'capacity', 'number_or_name', 'beds_config', 'has_ac']
        labels = {
            'type': 'Tipo',
            'capacity': 'Capacidade',
            'number_or_name': 'Número do quarto',
            'beds_config': 'Configuração das camas',
            'has_ac': 'Possui ar-condicionado',
        }
        widgets = {
            'type': forms.Select(attrs={'class': 'form-select'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'number_or_name': forms.TextInput(attrs={'class': 'form-control'}),
            'beds_config': forms.TextInput(attrs={'class': 'form-control'}),
            'has_ac': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_capacity(self):
        capacity = self.cleaned_data.get('capacity')
        if capacity is not None and capacity <= 0:
            raise forms.ValidationError('A capacidade deve ser um número positivo.')
        return capacity

    def clean(self):
        cleaned_data = super().clean()
        room_type = cleaned_data.get('type')
        capacity = cleaned_data.get('capacity')

        # Validar capacidade compatível com o tipo

        if room_type and capacity:
            from core.services.room_list_services import validate_room_capacity_for_type
            try:
                validate_room_capacity_for_type(room_type, capacity)
            except Exception as e:
                self.add_error('capacity', str(e))

        return cleaned_data

class ActionConfirmForm(forms.Form):
    pass

from django.forms import inlineformset_factory
from core.models import TemplateRoom, LodgingTemplate

class TemplateRoomForm(forms.ModelForm):
    participants = forms.ModelMultipleChoiceField(
        queryset=Integrante.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 5})
    )

    class Meta:
        model = TemplateRoom
        fields = ['type', 'capacity', 'order', 'beds_config', 'has_ac']
        labels = {
            'type': 'Tipo',
            'capacity': 'Capacidade',
            'number_or_name': 'Número do quarto',
            'beds_config': 'Configuração das camas',
            'has_ac': 'Possui ar-condicionado',
        }
        widgets = {
            'type': forms.Select(attrs={'class': 'form-select'}),
            'capacity': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'order': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'beds_config': forms.TextInput(attrs={'class': 'form-control'}),
            'has_ac': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.band = kwargs.pop('band', None)
        super().__init__(*args, **kwargs)
        if self.band:
            self.fields['participants'].queryset = Integrante.objects.filter(band=self.band, is_active=True)

        if self.instance and self.instance.pk:
            participant_ids = self.instance.participants.values_list('original_integrante_id', flat=True)
            self.fields['participants'].initial = participant_ids

    def clean(self):
        cleaned_data = super().clean()
        room_type = cleaned_data.get('type')
        capacity = cleaned_data.get('capacity')
        if room_type and capacity:
            from core.services.room_list_services import validate_room_capacity_for_type
            try:
                validate_room_capacity_for_type(room_type, capacity)
            except Exception as e:
                self.add_error('capacity', str(e))
        return cleaned_data

class BaseTemplateRoomFormSet(forms.BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        self.band = kwargs.pop('band', None)
        super().__init__(*args, **kwargs)

    def _construct_form(self, i, **kwargs):
        kwargs['band'] = self.band
        return super()._construct_form(i, **kwargs)

    def clean(self):
        super().clean()
        all_participants = []
        for form in self.forms:
            if self.can_delete and self._should_delete_form(form):
                continue
            participants = form.cleaned_data.get('participants')
            if participants:
                for p in participants:
                    if p.id in all_participants:
                        form.add_error('participants', f"O integrante {p.name} não pode estar em dois quartos simultaneamente.")
                    all_participants.append(p.id)

TemplateRoomFormSet = inlineformset_factory(
    LodgingTemplate,
    TemplateRoom,
    form=TemplateRoomForm,
    formset=BaseTemplateRoomFormSet,
    extra=1,
    can_delete=True
)
from django import forms
from django.utils import timezone
from datetime import datetime

class BandNoticeForm(forms.ModelForm):
    fire_now = forms.BooleanField(label='Disparar Aviso Agora', required=False, widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch', 'id': 'fireNowSwitch'}))
    date = forms.DateField(label='Data', required=False, widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date', 'class': 'form-control'}))
    time = forms.TimeField(label='Horário', required=False, widget=forms.TimeInput(format='%H:%M', attrs={'type': 'time', 'class': 'form-control'}))

    class Meta:
        from core.models import BandNotice
        model = BandNotice
        fields = ['message']
        widgets = {
            'message': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Digite o aviso para a banda...'}),
        }

    def clean_message(self):
        message = self.cleaned_data.get('message')
        if not message or not message.strip():
            raise forms.ValidationError('A mensagem não pode ser vazia.')
        return message.strip()

    def clean(self):
        cleaned_data = super().clean()
        fire_now = cleaned_data.get('fire_now')
        date = cleaned_data.get('date')
        time = cleaned_data.get('time')
        
        if fire_now:
            cleaned_data['scheduled_at'] = timezone.now()
        else:
            if not date or not time:
                raise forms.ValidationError('Data e horário são obrigatórios se não for disparar agora.')
            naive_datetime = datetime.combine(date, time)
            aware_datetime = timezone.make_aware(naive_datetime, timezone.get_current_timezone())
            cleaned_data['scheduled_at'] = aware_datetime
            
        return cleaned_data

class CommercialProposalForm(forms.ModelForm):
    fee = forms.CharField(
        label='Valor do Cachê',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control money-mask', 'placeholder': 'R$ 0,00'})
    )

    class Meta:
        from core.models import CommercialProposal
        model = CommercialProposal
        fields = ['name', 'date', 'time', 'contact_name', 'contact', 'location', 'origin', 'fee', 'phase']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Show de Réveillon, Aniversário de Cidade'}),
            'date': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            'time': forms.TimeInput(format='%H:%M', attrs={'class': 'form-control', 'type': 'time'}),
            'contact_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: João Silva, Maria Produções'}),
            'contact': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: (11) 99999-9999'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Clube Atlético, Parque de Exposições'}),
            'origin': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Indicação, Instagram, Produtor Fulano'}),
            'phase': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean_name(self):
        name = self.cleaned_data.get('name')
        if not name or not name.strip():
            raise forms.ValidationError('O nome da solicitação é obrigatório.')
        return name.strip()

    def clean_contact_name(self):
        contact_name = self.cleaned_data.get('contact_name')
        if not contact_name or not contact_name.strip():
            return None
        return contact_name.strip()

    def clean_contact(self):
        contact = self.cleaned_data.get('contact')
        if not contact or not contact.strip():
            return None
        return contact.strip()

    def clean_location(self):
        location = self.cleaned_data.get('location')
        if not location or not location.strip():
            return None
        return location.strip()

    def clean_origin(self):
        origin = self.cleaned_data.get('origin')
        if not origin or not origin.strip():
            return None
        return origin.strip()

    def clean_fee(self):
        fee_val = self.cleaned_data.get('fee')
        if not fee_val:
            return None
        from decimal import Decimal
        import re
        if isinstance(fee_val, str):
            clean_str = re.sub(r'[^\d,.-]', '', fee_val).strip()
            if not clean_str:
                return None
            if ',' in clean_str:
                clean_str = clean_str.replace('.', '').replace(',', '.')
            try:
                decimal_val = Decimal(clean_str)
            except Exception:
                raise forms.ValidationError('Informe um valor válido.')
        else:
            decimal_val = Decimal(fee_val)

        if decimal_val < 0:
            raise forms.ValidationError('O valor do cachê não pode ser negativo.')
        return decimal_val
