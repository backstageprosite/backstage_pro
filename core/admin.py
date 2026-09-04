from django.contrib import admin
from django.contrib.admin.filters import DateFieldListFilter
from django.contrib.auth.admin import UserAdmin
from django.db import models
from django.forms import Textarea
from django.utils import timezone
import datetime
from .models import User, Show, FinancialReceipt, ContractDocument, Band, Contact, ShowPayment, ShowTeamCost, BandSubscription, BillingRecord, WebPushSubscription, WebPushDelivery


def custom_get_app_list(self, request, app_label=None):
    # Depending on Django version, app_label might be passed
    app_dict = self._build_app_dict(request, app_label)
    if not app_dict:
        return []
    app_list = sorted(app_dict.values(), key=lambda x: x['name'].lower())
    for app in app_list:
        if app['app_label'] == 'core':
            # Nome dinâmico do app no menu lateral
            if hasattr(request, 'user') and request.user.is_authenticated:
                if not request.user.is_superuser and request.user.band:
                    app['name'] = request.user.band.name
                else:
                    app['name'] = 'Sistema Backstage Pro'
            
            ordering = {
                'Shows': 1,
                'Banco de Dados': 2,
                'Usuários': 3,
                'Bandas': 4,
            }
            app['models'].sort(key=lambda x: ordering.get(x['name'], 99))
        else:
            app['models'].sort(key=lambda x: x['name'].lower())
    return app_list

admin.site.get_app_list = custom_get_app_list.__get__(admin.site, admin.site.__class__)

@admin.register(Band)
class BandAdmin(admin.ModelAdmin):
    list_display = ('name', 'subscription_status', 'subscription_plan', 'is_active', 'slug')
    list_filter = ('subscription_status', 'subscription_plan', 'is_active')
    prepopulated_fields = {'slug': ('name',)}

    fieldsets = (
        ('Informações da Banda', {
            'fields': ('name', 'slug', 'logo')
        }),
        ('Controle de Assinatura (SaaS)', {
            'fields': ('is_active', 'subscription_status', 'subscription_plan', 'subscription_due_date'),
            'description': 'Gerencie o faturamento e o acesso desta banda ao sistema. Desmarque "Acesso Liberado" para bloquear o login de todos os usuários desta banda.'
        }),
    )

class ContractDocumentInline(admin.TabularInline):
    model = ContractDocument
    extra = 1

class FinancialReceiptInline(admin.TabularInline):
    model = FinancialReceipt
    extra = 1

class ShowTeamCostInline(admin.TabularInline):
    model = ShowTeamCost
    extra = 1

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ['username', 'first_name', 'last_name', 'band', 'role', 'is_staff']
    list_filter = ('band', 'role', 'is_staff', 'is_active')
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Informações Pessoais', {'fields': ('first_name', 'last_name', 'email')}),
        ('Perfil Backstage', {'fields': ('band', 'role', 'is_staff', 'is_active')}),
    )

    def get_list_display(self, request):
        if not request.user.is_superuser:
            return tuple(f for f in super().get_list_display(request) if f != 'band')
        return super().get_list_display(request)

    def get_list_filter(self, request):
        if not request.user.is_superuser:
            return tuple(f for f in super().get_list_filter(request) if f != 'band')
        return super().get_list_filter(request)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.user.band:
            return qs.filter(band=request.user.band, is_superuser=False)
        return qs.none()

    def has_change_permission(self, request, obj=None):
        if not request.user.is_superuser and obj and obj.is_superuser:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if not request.user.is_superuser and obj and obj.is_superuser:
            return False
        return super().has_delete_permission(request, obj)

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        if not request.user.is_superuser:
            new_fieldsets = []
            for name, opts in fieldsets:
                opts_copy = dict(opts)
                if name == 'Perfil Backstage':
                    fields = list(opts_copy.get('fields', []))
                    if 'band' in fields:
                        fields.remove('band')
                    if 'is_staff' in fields:
                        fields.remove('is_staff')
                    opts_copy['fields'] = tuple(fields)
                new_fieldsets.append((name, opts_copy))
            return new_fieldsets
        return fieldsets

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            if not change and hasattr(request.user, 'band') and request.user.band:
                obj.band = request.user.band
        
        # Garante as flags corretas baseado no papel
        if obj.role == 'INTEGRANTE':
            obj.is_staff = False
        elif obj.role == 'PRODUTOR':
            obj.is_staff = True
            
        super().save_model(request, obj, form, change)
        
        # Garante as permissões de acesso aos models no Admin para o Produtor
        if obj.role == 'PRODUTOR':
            from django.contrib.auth.models import Permission
            from django.contrib.contenttypes.models import ContentType
            show_ct = ContentType.objects.get_for_model(Show)
            user_ct = ContentType.objects.get_for_model(User)
            contact_ct = ContentType.objects.get_for_model(Contact)
            doc_ct = ContentType.objects.get_for_model(ContractDocument)
            rec_ct = ContentType.objects.get_for_model(FinancialReceipt)
            
            perms = Permission.objects.filter(content_type__in=[show_ct, user_ct, contact_ct, doc_ct, rec_ct])
            obj.user_permissions.add(*perms)

@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_type', 'phone', 'email', 'band')
    list_filter = ('contact_type', 'band')
    search_fields = ('name', 'phone', 'email', 'notes')

    def get_list_display(self, request):
        if not request.user.is_superuser:
            return tuple(f for f in super().get_list_display(request) if f != 'band')
        return super().get_list_display(request)

    def get_list_filter(self, request):
        if not request.user.is_superuser:
            return tuple(f for f in super().get_list_filter(request) if f != 'band')
        return super().get_list_filter(request)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.user.band:
            return qs.filter(band=request.user.band)
        return qs.none()

    def get_exclude(self, request, obj=None):
        if not request.user.is_superuser:
            return ('band',)
        return None

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not change:
            if hasattr(request.user, 'band') and request.user.band:
                obj.band = request.user.band
        super().save_model(request, obj, form, change)

class CustomDateFilter(DateFieldListFilter):
    def __init__(self, field, request, params, model, model_admin, field_path):
        super().__init__(field, request, params, model, model_admin, field_path)
        
        now = timezone.now()
        if timezone.is_aware(now):
            now = timezone.localtime(now)
            
        if isinstance(field, models.DateTimeField):
            today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            today = now.date()
            
        next_7_days = today + datetime.timedelta(days=8) # days=8 para incluir o 7º dia até as 23:59:59 (usando __lt)
        
        links_list = list(self.links)
        new_links = []
        
        for title, param_dict in links_list:
            # Ignora a opção "Tem data" e "Não tem data" (para deixar mais limpo)
            if param_dict.get(self.field_generic + 'isnull') in ('True', 'False') or str(title) == 'Tem data':
                continue
            
            # Renomeia "Qualquer data" (que tem dicionário vazio)
            if not param_dict:
                title = 'Todas as datas'
                
            new_links.append((title, param_dict))
            
        new_links.insert(
            3, # Inserindo logo após "Últimos 7 dias"
            (
                'Próximos 7 dias',
                {
                    self.lookup_kwarg_since: str(today),
                    self.lookup_kwarg_until: str(next_7_days),
                },
            )
        )
        self.links = tuple(new_links)

class MonthYearFilter(admin.SimpleListFilter):
    title = 'Mês específico'
    parameter_name = 'mes_ano'

    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request)
        # Pega todos os meses únicos que têm shows cadastrados
        months = qs.dates('date', 'month', order='DESC')
        
        lookup_list = []
        meses_pt = {
            1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
            5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
            9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
        }
        
        for d in months:
            val = f"{d.year}-{d.month:02d}"
            label = f"{meses_pt[d.month]} de {d.year}"
            lookup_list.append((val, label))
            
        return lookup_list

    def queryset(self, request, queryset):
        val = self.value()
        if val:
            year, month = val.split('-')
            return queryset.filter(date__year=year, date__month=month)
        return queryset

@admin.register(Show)
class ShowAdmin(admin.ModelAdmin):
    save_on_top = True
    list_display = ('title', 'band', 'date', 'city', 'contract_type', 'status', 'payment_status')
    list_filter = ('band', 'status', ('date', CustomDateFilter), MonthYearFilter, 'contract_type', 'payment_status')
    search_fields = ('title', 'city', 'venue')
    date_hierarchy = 'date'
    formfield_overrides = {
        models.TextField: {'widget': Textarea(attrs={'rows': 2})},
    }
    inlines = [ContractDocumentInline, FinancialReceiptInline, ShowTeamCostInline]
    
    def save_model(self, request, obj, form, change):
        from django.db import connection
        # Comprova que o ModelAdmin está rodando em transação (atomic)
        if not connection.in_atomic_block:
            import logging
            logging.getLogger(__name__).warning("ShowAdmin save_model executado fora de bloco atômico!")

        if not request.user.is_superuser and not change:
            if hasattr(request.user, 'band') and request.user.band:
                obj.band = request.user.band

        if not change:
            # Criação
            super().save_model(request, obj, form, change)
            from core.services.show_notifications import schedule_show_notifications
            schedule_show_notifications(old_show=None, new_show=obj, actor=request.user, is_creation=True)
            return

        # Edição
        old_obj = Show.objects.select_for_update().get(pk=obj.pk, band=obj.band)
        
        has_relevant_event = (
            (old_obj.date != obj.date) or
            (old_obj.show_time != obj.show_time) or
            (old_obj.status == 'CONFIRMADO' and obj.status == 'CANCELADO') or
            (old_obj.status != 'CONFIRMADO' and obj.status == 'CONFIRMADO')
        )
        
        if has_relevant_event:
            obj.notification_revision += 1
            
        super().save_model(request, obj, form, change)
        
        if has_relevant_event:
            from core.services.show_notifications import schedule_show_notifications
            schedule_show_notifications(old_show=old_obj, new_show=obj, actor=request.user, is_creation=False)
    
    def get_list_display(self, request):
        if not request.user.is_superuser:
            return tuple(f for f in super().get_list_display(request) if f != 'band')
        return super().get_list_display(request)

    def get_list_filter(self, request):
        if not request.user.is_superuser:
            return tuple(f for f in super().get_list_filter(request) if f != 'band')
        return super().get_list_filter(request)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if request.user.band:
            return qs.filter(band=request.user.band)
        return qs.none()

    def get_fieldsets(self, request, obj=None):
        fieldsets = list(super().get_fieldsets(request, obj))
        if not request.user.is_superuser:
            new_fieldsets = []
            for name, opts in fieldsets:
                opts_copy = dict(opts)
                if name == 'Informações Básicas':
                    fields = list(opts_copy.get('fields', []))
                    if 'band' in fields:
                        fields.remove('band')
                    opts_copy['fields'] = tuple(fields)
                new_fieldsets.append((name, opts_copy))
            return new_fieldsets
        return fieldsets


    fieldsets = (
        ('Informações Básicas', {
            'fields': ('band', 'title', 'event_name', 'date', 'status')
        }),
        ('Localização', {
            'fields': ('city', 'venue', 'location_link', 'address')
        }),
        ('Cronograma', {
            'fields': (
                ('departure_location', 'departure_location_link'),
                ('distance_km', 'travel_time'),
                ('departure_time', 'arrival_time'),
                ('soundcheck_time', 'soundcheck_end_time'),
                ('show_time', 'show_end_time', 'duration'),
                'band_notes'
            )
        }),
        ('Logística & Produção', {
            'fields': (('transport', 'transport_contact'), ('flight_number', 'airline'), ('accommodation', 'accommodation_link', 'accommodation_contact'), ('transfer', 'transfer_contact'), ('dressing_room', 'dressing_room_contact'), 'catering', 'wardrobe', 'attractions')
        }),
        ('Informações Técnicas', {
            'fields': (
                ('local_production', 'local_production_contact'),
                ('sound_system', 'sound_contact'),
                ('lighting_system', 'lighting_contact'),
                ('led_system', 'led_contact'),
                ('backline', 'backline_contact'),
                ('pyrotechnics', 'pyrotechnics_contact'),
                ('generator_system', 'generator_contact'),
                ('loaders_system', 'loaders_contact')
            )
        }),
        ('Observações (Apenas Produção)', {
            'fields': ('internal_notes',)
        }),
        ('Dados do Contrato e Financeiro (Apenas Produção)', {
            'fields': (('contractor_name', 'contractor_phone'), 'contract_type', ('fee', 'payment_status'))
        }),
    )

    class Media:
        css = {
            'all': ('css/admin_custom.css',)
        }
        js = ('js/admin_custom.js',)

@admin.register(ShowPayment)
class ShowPaymentAdmin(admin.ModelAdmin):
    list_display = ('description', 'show', 'value', 'status', 'payment_method', 'expected_date')
    list_filter = ('status', 'payment_method')
    search_fields = ('description', 'show__title', 'show__event_name')

@admin.register(BandSubscription)
class BandSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('band', 'plan_name', 'billing_cycle', 'contracted_value', 'next_due_date', 'status', 'billing_phone', 'billing_email', 'updated_at')
    list_filter = ('status', 'billing_cycle', 'plan_name')
    search_fields = ('band__name', 'financial_responsible_name', 'billing_phone', 'billing_email')

@admin.register(BillingRecord)
class BillingRecordAdmin(admin.ModelAdmin):
    list_display = ('band', 'reference_period', 'amount', 'due_date', 'paid_date', 'status', 'payment_method', 'updated_at')
    list_filter = ('status', 'payment_method', 'due_date')
    search_fields = ('band__name', 'reference_period', 'subscription__band__name')

# Customizando o título do painel de administração
admin.site.site_header = "Administração Backstage Pro"
admin.site.site_title = "Admin Backstage Pro"
admin.site.index_title = "Painel de Controle"

@admin.register(WebPushSubscription)
class WebPushSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        'user', 
        'band', 
        'get_masked_endpoint_hash', 
        'is_active', 
        'created_at'
    )
    search_fields = (
        'user__username',
        'user__email',
        'band__name',
    )
    list_filter = ('band', 'is_active', 'created_at')
    readonly_fields = (
        'get_masked_endpoint', 
        'get_masked_endpoint_hash', 
        'user_agent', 
        'service_worker_scope', 
        'failure_count', 
        'last_success_at', 
        'last_failure_at',
        'created_at',
        'updated_at'
    )
    exclude = (
        'endpoint', 
        'endpoint_hash', 
        'p256dh', 
        'auth'
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_masked_endpoint(self, obj):
        if obj.endpoint:
            return obj.endpoint[:15] + "... [MASKS]"
        return ""
    get_masked_endpoint.short_description = "Endpoint (Mascarado)"

    def get_masked_endpoint_hash(self, obj):
        if obj.endpoint_hash:
            return obj.endpoint_hash[:8] + "..." + obj.endpoint_hash[-8:]
        return ""
    get_masked_endpoint_hash.short_description = "Hash do Endpoint (Mascarado)"

@admin.register(WebPushDelivery)
class WebPushDeliveryAdmin(admin.ModelAdmin):
    list_display = ('notification_id', 'subscription_id', 'status', 'attempt_count', 'last_http_status', 'created_at', 'sent_at')
    list_filter = ('status', 'created_at')
    search_fields = ('notification__id', 'subscription__id', 'notification__recipient__username', 'notification__band__name')
    readonly_fields = (
        'notification', 'subscription', 'status', 'attempt_count', 
        'last_http_status', 'error_code', 'last_attempt_at', 
        'sent_at', 'created_at', 'updated_at'
    )

    def has_add_permission(self, request):
        return False


from .models import SignupOrder, PaymentWebhookEvent, BandActivationToken

@admin.register(SignupOrder)
class SignupOrderAdmin(admin.ModelAdmin):
    list_display = ('external_reference', 'band_name', 'responsible_name', 'email', 'plan_type', 'billing_cycle', 'amount', 'status', 'created_at')
    list_filter = ('status', 'plan_type', 'billing_cycle', 'created_at')
    search_fields = ('external_reference', 'band_name', 'responsible_name', 'email', 'gateway_checkout_id')
    readonly_fields = ('created_at', 'updated_at', 'provisioned_at')

@admin.register(PaymentWebhookEvent)
class PaymentWebhookEventAdmin(admin.ModelAdmin):
    list_display = ('gateway_event_id', 'provider', 'event_type', 'processed', 'processed_at', 'created_at')
    list_filter = ('provider', 'event_type', 'processed', 'created_at')
    search_fields = ('gateway_event_id', 'event_type')
    readonly_fields = ('created_at', 'processed_at', 'payload')

@admin.register(BandActivationToken)
class BandActivationTokenAdmin(admin.ModelAdmin):
    list_display = ('band', 'email', 'responsible_name', 'expires_at', 'used_at', 'created_at')
    list_filter = ('used_at', 'created_at')
    search_fields = ('band__name', 'email', 'responsible_name', 'token_hash')
    readonly_fields = ('token_hash', 'created_at', 'used_at')
