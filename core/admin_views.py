from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from decimal import Decimal
import uuid
import re
from django.core.management import call_command
from django.contrib.auth import logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, ListView, View
from django.db.models import Count, F, Q, Sum, Case, When, Value, IntegerField
from django.core.paginator import Paginator
from core.models import Band, User, Show, BandSubscription, BillingRecord, AdministrativeBandNotice, Partner, SupportTicket, SystemSettings, UserBandMembership, SubscriptionCancellationFeedback
from .admin_forms import AdminBandForm, AdminUserCreateForm, AdminUserEditForm, AdminSubscriptionForm, AdminBillingRecordForm, AdminPartnerForm
from core.views import build_whatsapp_access_data
import datetime

def is_admin_geral(user):
    return user.is_authenticated and user.is_superuser

def is_admin_web_push(user):
    return (
        user.is_authenticated
        and user.is_staff
        and (
            user.is_superuser
            or user.has_perm("core.view_webpushdelivery")
        )
    )

class AdminLoginView(LoginView):
    template_name = 'admin/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        return reverse_lazy('admin_painel:dashboard')

def admin_logout(request):
    logout(request)
    return redirect('/painel/login/')

class AdminRequiredMixin:
    @method_decorator(user_passes_test(is_admin_geral, login_url='/painel/login/'))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

class AdminDashboardView(AdminRequiredMixin, TemplateView):
    template_name = 'core/admin/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import json
        from django.db.models import Sum, Q, Count

        today = datetime.date.today()
        seven_days_from_now = today + datetime.timedelta(days=7)
        first_day_this_month = today.replace(day=1)

        # -------------------------------------------------------------
        # 1. Indicadores Linha 1 (Cards Existentes)
        # -------------------------------------------------------------
        context['bandas_ativas'] = Band.objects.filter(is_active=True).count()
        context['total_usuarios'] = User.objects.count()

        # Assinaturas SaaS vencendo em 7 dias (próximos 7 dias)
        context['assinaturas_vencendo'] = BandSubscription.objects.filter(
            is_deleted=False,
            status='ATIVO',
            next_due_date__gte=today,
            next_due_date__lte=seven_days_from_now
        ).count()

        # Assinaturas SaaS vencidas
        context['assinaturas_vencidas'] = BandSubscription.objects.filter(
            is_deleted=False,
            status='ATIVO',
            next_due_date__lt=today
        ).count()

        # -------------------------------------------------------------
        # 2. Novos Indicadores (Linha 2)
        # -------------------------------------------------------------
        # Recebido no mês (faturas pagas no mês atual)
        recebido_mes = BillingRecord.objects.filter(
            subscription__is_deleted=False,
            status='PAGO',
            paid_date__gte=first_day_this_month,
            paid_date__lte=today
        ).aggregate(total=Sum('amount'))['total'] or 0
        context['recebido_mes'] = float(recebido_mes)

        # A receber (faturas abertas PENDENTES não vencidas)
        a_receber = BillingRecord.objects.filter(
            subscription__is_deleted=False,
            status='PENDENTE',
            due_date__gte=today
        ).aggregate(total=Sum('amount'))['total'] or 0
        context['a_receber'] = float(a_receber)

        # Total em atraso (faturas vencidas e não pagas: ATRASADO ou PENDENTE com due_date < today)
        total_atraso = BillingRecord.objects.filter(
            subscription__is_deleted=False
        ).filter(
            Q(status='ATRASADO') | Q(status='PENDENTE', due_date__lt=today)
        ).aggregate(total=Sum('amount'))['total'] or 0
        context['total_atraso'] = float(total_atraso)

        # Fale Conosco (mensagens novas ou aguardando resposta)
        context['fale_conosco_count'] = SupportTicket.objects.filter(
            status__in=['NEW', 'WAITING_ADMIN']
        ).count()

        # -------------------------------------------------------------
        # 3. Gráfico Financeiro (Últimos 6 meses)
        # -------------------------------------------------------------
        months_labels = []
        months_recebido = []
        months_pendente = []
        months_vencido = []

        # Calcular últimos 6 meses (do mais antigo ao atual)
        month_cursor = today.replace(day=1)
        start_months = []
        for i in range(5, -1, -1):
            # Calcular mês (today - i meses)
            year = today.year
            month = today.month - i
            while month <= 0:
                month += 12
                year -= 1
            m_start = datetime.date(year, month, 1)
            if month == 12:
                m_end = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
            else:
                m_end = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)
            start_months.append((m_start, m_end, m_start.strftime('%b/%y').capitalize()))

        for m_start, m_end, m_label in start_months:
            months_labels.append(m_label)

            # Recebido no mês (por paid_date)
            rec_val = BillingRecord.objects.filter(
                subscription__is_deleted=False,
                status='PAGO',
                paid_date__gte=m_start,
                paid_date__lte=m_end
            ).aggregate(total=Sum('amount'))['total'] or 0
            months_recebido.append(float(rec_val))

            # Pendente no mês (vencimento no mês que ainda está pendente ou não venceu)
            pend_val = BillingRecord.objects.filter(
                subscription__is_deleted=False,
                status='PENDENTE',
                due_date__gte=max(m_start, today),
                due_date__lte=m_end
            ).aggregate(total=Sum('amount'))['total'] or 0
            months_pendente.append(float(pend_val))

            # Vencido no mês (vencimento no mês com atraso)
            venc_val = BillingRecord.objects.filter(
                subscription__is_deleted=False,
                due_date__gte=m_start,
                due_date__lte=min(m_end, today - datetime.timedelta(days=1))
            ).filter(
                Q(status='ATRASADO') | Q(status='PENDENTE')
            ).aggregate(total=Sum('amount'))['total'] or 0
            months_vencido.append(float(venc_val))

        chart_financial_data = {
            'labels': months_labels,
            'recebido': months_recebido,
            'pendente': months_pendente,
            'vencido': months_vencido,
            'has_data': any(sum(x) > 0 for x in [months_recebido, months_pendente, months_vencido])
        }
        context['chart_financial_json'] = json.dumps(chart_financial_data)

        # -------------------------------------------------------------
        # 4. Resumo das Assinaturas (Doughnut / Distribuição)
        # -------------------------------------------------------------
        sub_ativas_em_dia = BandSubscription.objects.filter(
            is_deleted=False,
            status='ATIVO',
            next_due_date__gt=seven_days_from_now
        ).count()
        sub_vencendo_7d = context['assinaturas_vencendo']
        sub_vencidas = context['assinaturas_vencidas']
        sub_suspensas = BandSubscription.objects.filter(
            is_deleted=False,
            status='DESATIVADO'
        ).count()

        chart_subs_data = {
            'labels': ['Ativas (Em dia)', 'Vencendo (7d)', 'Vencidas', 'Desativadas / Suspensas'],
            'data': [sub_ativas_em_dia, sub_vencendo_7d, sub_vencidas, sub_suspensas],
            'has_data': any([sub_ativas_em_dia, sub_vencendo_7d, sub_vencidas, sub_suspensas])
        }
        context['chart_subs_json'] = json.dumps(chart_subs_data)
        context['sub_counts'] = {
            'ativas': sub_ativas_em_dia,
            'vencendo': sub_vencendo_7d,
            'vencidas': sub_vencidas,
            'suspensas': sub_suspensas,
        }

        # -------------------------------------------------------------
        # 5. Assinaturas que exigem atenção (até 5: vencidas primeiro, depois vencendo 7d)
        # -------------------------------------------------------------
        attention_subs_vencidas = list(BandSubscription.objects.filter(
            is_deleted=False,
            status='ATIVO',
            next_due_date__lt=today
        ).select_related('band').order_by('next_due_date')[:5])

        vagas_restantes = 5 - len(attention_subs_vencidas)
        attention_subs_vencendo = []
        if vagas_restantes > 0:
            attention_subs_vencendo = list(BandSubscription.objects.filter(
                is_deleted=False,
                status='ATIVO',
                next_due_date__gte=today,
                next_due_date__lte=seven_days_from_now
            ).select_related('band').order_by('next_due_date')[:vagas_restantes])

        context['attention_subscriptions'] = attention_subs_vencidas + attention_subs_vencendo

        # -------------------------------------------------------------
        # 6. Fale Conosco (Até 5 chamados recentes / pendentes)
        # -------------------------------------------------------------
        context['recent_tickets'] = SupportTicket.objects.select_related('band', 'created_by').order_by('-last_message_at')[:5]

        # -------------------------------------------------------------
        # 7. Faturas Recentes (Até 5: priorizando atrasadas e pendentes)
        # -------------------------------------------------------------
        faturas_prioritarias = list(BillingRecord.objects.filter(
            subscription__is_deleted=False
        ).filter(
            Q(status='ATRASADO') | Q(status='PENDENTE')
        ).select_related('band', 'subscription').order_by('due_date')[:5])

        if len(faturas_prioritarias) < 5:
            sobra = 5 - len(faturas_prioritarias)
            outras = list(BillingRecord.objects.filter(
                subscription__is_deleted=False
            ).exclude(
                id__in=[f.id for f in faturas_prioritarias]
            ).select_related('band', 'subscription').order_by('-due_date')[:sobra])
            faturas_prioritarias.extend(outras)

        context['recent_billings'] = faturas_prioritarias

        # -------------------------------------------------------------
        # 8. Avisos Ativos (Quantidade total e até 3 recentes)
        # -------------------------------------------------------------
        context['total_avisos'] = AdministrativeBandNotice.objects.count()
        context['recent_avisos'] = AdministrativeBandNotice.objects.select_related('band').order_by('-created_at')[:3]

        return context

class AdminBandListView(AdminRequiredMixin, ListView):
    model = Band
    template_name = 'core/admin/bandas.html'
    context_object_name = 'bandas'

    def get_queryset(self):
        return Band.objects.all().prefetch_related('subscriptions', 'users').order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_create'] = AdminBandForm()
        settings_obj = SystemSettings.get_settings()
        context['canonical_prices'] = {
            'BASICO_MENSAL': float(settings_obj.plan_basic_monthly or 19.90),
            'BASICO_ANUAL': float(settings_obj.plan_basic_annual or 199.90),
            'AVANCADO_MENSAL': float(settings_obj.plan_advanced_monthly or 49.90),
            'AVANCADO_ANUAL': float(settings_obj.plan_advanced_annual or 499.90),
        }
        return context

class AdminUserListView(AdminRequiredMixin, ListView):
    model = User
    template_name = 'core/admin/usuarios.html'
    context_object_name = 'usuarios'
    
    def get_queryset(self):
        from django.db.models import F, Q
        qs = User.objects.all().order_by(F('band__name').asc(nulls_last=True), 'first_name', 'username')
        
        q = self.request.GET.get('q', '')
        band_id = self.request.GET.get('band', '')
        
        if q:
            qs = qs.filter(
                Q(first_name__icontains=q) | 
                Q(last_name__icontains=q) | 
                Q(username__icontains=q) | 
                Q(email__icontains=q)
            )
        if band_id:
            if band_id == 'none':
                qs = qs.filter(band__isnull=True)
            else:
                qs = qs.filter(band_id=band_id)

        # BP-PEND-62: prefetch memberships para exibir múltiplas bandas sem N+1 queries
        return qs.prefetch_related('band_memberships__band')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        bandas_qs = Band.objects.all().order_by('name')
        context['form_create'] = AdminUserCreateForm()
        context['bandas'] = bandas_qs
        context['bandas_list'] = bandas_qs
        context['q'] = self.request.GET.get('q', '')
        context['selected_band'] = self.request.GET.get('band', '')
        context['whatsapp_access_data'] = self.request.session.pop('whatsapp_access_data', None)
        return context

class AdminShowListView(AdminRequiredMixin, ListView):
    model = Show
    template_name = 'core/admin/shows.html'
    context_object_name = 'shows'

    def get_queryset(self):
        today = timezone.localdate()
        return Show.objects.filter(date__gte=today).select_related('band').order_by('date', 'show_time', 'id')

class AdminAssinaturasView(AdminRequiredMixin, ListView):
    model = BandSubscription
    template_name = 'core/admin/assinaturas.html'
    context_object_name = 'assinaturas'

    def get_queryset(self):
        qs = super().get_queryset().filter(is_deleted=False)
        q = self.request.GET.get('q', '')
        status = self.request.GET.get('status', '')
        cycle = self.request.GET.get('billing_cycle') or self.request.GET.get('cycle', '')
        condition = self.request.GET.get('commercial_condition', '')

        if q:
            qs = qs.filter(
                Q(band__name__icontains=q) |
                Q(financial_responsible_name__icontains=q) |
                Q(gateway_subscription_id__icontains=q) |
                Q(gateway_external_reference__icontains=q)
            )
        if status:
            if status == 'VENCENDO_7D':
                today = datetime.date.today()
                qs = qs.filter(next_due_date__gt=today, next_due_date__lte=today + datetime.timedelta(days=7))
            else:
                qs = qs.filter(status=status)
        if cycle:
            qs = qs.filter(billing_cycle=cycle)
        if condition:
            qs = qs.filter(commercial_condition=condition)

        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_create'] = AdminSubscriptionForm()
        context['today'] = datetime.date.today()
        context['seven_days'] = datetime.date.today() + datetime.timedelta(days=7)
        context['commercial_condition'] = self.request.GET.get('commercial_condition', '')
        context['billing_cycle'] = self.request.GET.get('billing_cycle') or self.request.GET.get('cycle', '')
        context['status'] = self.request.GET.get('status', '')
        context['q'] = self.request.GET.get('q', '')
        context['auto_renew'] = self.request.GET.get('auto_renew', '')

        # BP-PEND-60 + BP-PEND-61: Dados de bandas e preços canônicos para o modal 'Gerar Cobrança'
        settings_obj = SystemSettings.get_settings()
        canonical_prices = {
            'BASICO_MENSAL': float(settings_obj.plan_basic_monthly or 19.90),
            'BASICO_ANUAL': float(settings_obj.plan_basic_annual or 199.90),
            'AVANCADO_MENSAL': float(settings_obj.plan_advanced_monthly or 49.90),
            'AVANCADO_ANUAL': float(settings_obj.plan_advanced_annual or 499.90),
        }
        context['canonical_prices'] = canonical_prices

        all_bands = Band.objects.all().prefetch_related('subscriptions', 'users').order_by('name')
        context['all_bands_for_charge'] = all_bands

        bands_charge_dict = {}
        for b in all_bands:
            prod_user = b.users.filter(role__in=['PRODUTOR', 'EMPRESARIO']).order_by('-id').first() or b.users.order_by('-id').first()
            last_sub = b.subscriptions.filter(is_deleted=False).order_by('-created_at').first()

            resp_name = ''
            if prod_user and prod_user.get_full_name():
                resp_name = prod_user.get_full_name()
            elif last_sub and last_sub.financial_responsible_name:
                resp_name = last_sub.financial_responsible_name
            elif prod_user:
                resp_name = prod_user.username
            else:
                resp_name = b.name

            email = ''
            if prod_user and prod_user.email:
                email = prod_user.email
            elif last_sub and last_sub.billing_email:
                email = last_sub.billing_email

            phone = ''
            if prod_user and prod_user.phone:
                phone = prod_user.phone
            elif last_sub and last_sub.billing_phone:
                phone = last_sub.billing_phone

            has_active = b.has_contracted_active_subscription
            last_order = b.signup_orders.order_by('-created_at').first()

            cpf_cnpj = ''
            if last_order and last_order.cpf_cnpj:
                cpf_cnpj = last_order.cpf_cnpj
            elif prod_user and prod_user.cpf:
                cpf_cnpj = prod_user.cpf

            postal_code = (last_order and last_order.postal_code) or ''
            address = (last_order and last_order.address) or ''
            address_number = (last_order and last_order.address_number) or ''
            complement = (last_order and last_order.complement) or ''
            province = (last_order and last_order.province) or ''
            city = (last_order and last_order.city) or ''
            state = (last_order and last_order.state) or ''

            bands_charge_dict[str(b.id)] = {
                'id': b.id,
                'name': b.name,
                'plan_type': b.plan_type or 'AVANCADO',
                'responsible_name': resp_name,
                'email': email,
                'phone': phone,
                'cpf_cnpj': cpf_cnpj,
                'postal_code': postal_code,
                'address': address,
                'address_number': address_number,
                'complement': complement,
                'province': province,
                'city': city,
                'state': state,
                'has_active': has_active
            }

        context['bands_charge_data_json'] = json.dumps(bands_charge_dict)
        feedback_q = self.request.GET.get('feedback_q', '').strip()
        feedback = SubscriptionCancellationFeedback.objects.select_related('requested_by', 'subscription')
        if feedback_q:
            feedback = feedback.filter(
                Q(band_name__icontains=feedback_q) |
                Q(reason__icontains=feedback_q) |
                Q(requested_by__username__icontains=feedback_q)
            )
        feedback = feedback.order_by('-created_at', '-pk')
        context['feedback_q'] = feedback_q
        context['feedback_page'] = Paginator(feedback, 20).get_page(self.request.GET.get('feedback_page'))
        return context

class AdminCobrancasView(AdminRequiredMixin, ListView):
    model = BillingRecord
    template_name = 'core/admin/cobrancas.html'
    context_object_name = 'cobrancas'

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get('q', '')
        status = self.request.GET.get('status', '')
        period = self.request.GET.get('period', '')

        if q:
            qs = qs.filter(band__name__icontains=q)
        if period:
            qs = qs.filter(reference_period__icontains=period)
        if status:
            if status == 'VENCENDO_7D':
                today = datetime.date.today()
                qs = qs.filter(status='PENDENTE', due_date__gt=today, due_date__lte=today + datetime.timedelta(days=7))
            elif status == 'VENCIDAS':
                today = datetime.date.today()
                qs = qs.filter(status='PENDENTE', due_date__lt=today)
            else:
                qs = qs.filter(status=status)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_create'] = AdminBillingRecordForm()
        context['today'] = datetime.date.today()
        context['seven_days'] = datetime.date.today() + datetime.timedelta(days=7)
        return context

class AdminRelatoriosView(AdminRequiredMixin, TemplateView):
    template_name = 'core/admin/relatorios.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Fale Conosco (Mensagens não lidas)
        unread_tickets = SupportTicket.objects.filter(
            status__in=['NEW', 'WAITING_ADMIN']
        )
        count = 0
        for t in unread_tickets:
            if not t.admin_last_read_at or t.last_message_at > t.admin_last_read_at:
                count += 1
        context['support_unread_count'] = count
        
        return context

class AdminRelatorioFinanceiroView(AdminRequiredMixin, TemplateView):
    template_name = 'core/admin/relatorio_financeiro.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        import json
        from calendar import monthrange
        from django.utils import timezone
        from django.db.models import Sum, Q

        today = timezone.localdate()

        # Filtros
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        band_id = self.request.GET.get('band')
        status = self.request.GET.get('status')
        plan = self.request.GET.get('plan')
        cycle = self.request.GET.get('cycle')
        period = self.request.GET.get('period')

        if period in ['this_month', 'last_month', 'next_30', 'this_year']:
            if period == 'this_month':
                start_date = today.replace(day=1)
                _, last_day = monthrange(today.year, today.month)
                end_date = today.replace(day=last_day)
            elif period == 'last_month':
                first_this_month = today.replace(day=1)
                last_prev_month = first_this_month - datetime.timedelta(days=1)
                start_date = last_prev_month.replace(day=1)
                end_date = last_prev_month
            elif period == 'next_30':
                start_date = today
                end_date = today + datetime.timedelta(days=29)
            elif period == 'this_year':
                start_date = today.replace(month=1, day=1)
                end_date = today.replace(month=12, day=31)
        elif not start_date or not end_date:
            # Default: this month
            period = 'this_month'
            start_date = today.replace(day=1)
            _, last_day = monthrange(today.year, today.month)
            end_date = today.replace(day=last_day)
        else:
            try:
                start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                period = 'this_month'
                start_date = today.replace(day=1)
                _, last_day = monthrange(today.year, today.month)
                end_date = today.replace(day=last_day)

        # Base Querysets
        billings = BillingRecord.objects.filter(subscription__is_deleted=False)
        subs = BandSubscription.objects.filter(
            commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
            is_deleted=False
        )
        from .models import Expense
        expenses = Expense.objects.all()

        from django.db.models.functions import Coalesce

        # Applying Filters
        if band_id:
            billings = billings.filter(band_id=band_id)
            subs = subs.filter(band_id=band_id)
        if status:
            billings = billings.filter(status=status)
        if plan:
            subs = subs.filter(plan_name=plan)
            billings = billings.filter(subscription__plan_name=plan)
        if cycle:
            subs = subs.filter(billing_cycle=cycle)
            billings = billings.filter(subscription__billing_cycle=cycle)

        # Cobranças pertencentes ao período filtrado (Pagas no período OU Pendentes/Atrasadas com vencimento no período)
        billings_period = billings.filter(
            Q(paid_date__gte=start_date, paid_date__lte=end_date) |
            Q(paid_date__isnull=True, due_date__gte=start_date, due_date__lte=end_date)
        ).distinct()

        # Despesas do período filtrado
        expenses_period = expenses.filter(
            Q(paid_date__gte=start_date, paid_date__lte=end_date) |
            Q(paid_date__isnull=True, due_date__gte=start_date, due_date__lte=end_date) |
            Q(competence_date__gte=start_date, competence_date__lte=end_date)
        ).distinct()

        # Receitas recebidas (Cobranças pagas pela data de pagamento, considerando valor líquido quando informado)
        recebido = billings.filter(
            status='PAGO',
            paid_date__gte=start_date,
            paid_date__lte=end_date
        ).aggregate(
            total=Sum(Coalesce('net_amount', 'amount'))
        )['total'] or 0

        # Despesas pagas
        despesa_paga = expenses.filter(
            status='PAGO',
            paid_date__gte=start_date,
            paid_date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Resultado do Período (receitas recebidas líquidas menos despesas pagas)
        saldo_realizado = recebido - despesa_paga

        # Valores a receber (Cobranças pendentes ou vencidas no período baseado em due_date)
        a_receber = billings.filter(
            Q(status='PENDENTE', due_date__lt=timezone.localdate()) | Q(status='PENDENTE', due_date__gte=start_date, due_date__lte=end_date),
            due_date__gte=start_date,
            due_date__lte=end_date
        ).aggregate(total=Sum(Coalesce('net_amount', 'amount')))['total'] or 0

        # Valores a pagar (Despesas pendentes ou vencidas no período baseado em due_date)
        a_pagar = expenses.filter(
            Q(status='PENDENTE') | Q(status='VENCIDO'),
            due_date__gte=start_date,
            due_date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Cobranças vencidas
        cobrancas_vencidas = billings.filter(
            status='PENDENTE',
            due_date__lt=today
        ).aggregate(total=Sum(Coalesce('net_amount', 'amount')))['total'] or 0

        # Despesas vencidas
        despesas_vencidas = expenses.filter(
            Q(status='PENDENTE') | Q(status='VENCIDO'),
            due_date__lt=today
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Update chart data to match new KPIs
        chart_bars = {
            'labels': ['Recebido', 'Despesas', 'A Receber', 'A Pagar'],
            'data': [float(recebido), float(despesa_paga), float(a_receber), float(a_pagar)]
        }
        
        status_counts = billings_period.order_by().values('status').annotate(total=Count('id'))

        status_labels = []
        status_data = []
        for s in status_counts:
            status_labels.append(s['status'])
            status_data.append(s['total'])

        chart_pie = {
            'labels': status_labels,
            'data': status_data
        }

        # Gráfico 3: Receita por Ciclo
        cycle_revenue = subs.values('billing_cycle').annotate(total=Sum('contracted_value'))
        cycle_labels = []
        cycle_data = []
        for c in cycle_revenue:
            cycle_labels.append(c['billing_cycle'])
            cycle_data.append(float(c['total'] or 0))

        chart_cycle = {
            'labels': cycle_labels,
            'data': cycle_data
        }

        # Gráfico 4: Top Bandas
        top_bandas = billings.filter(status='PAGO', paid_date__gte=start_date, paid_date__lte=end_date).values('band__name').annotate(total=Sum(Coalesce('net_amount', 'amount'))).order_by('-total')[:5]
        top_bandas_labels = []
        top_bandas_data = []
        for tb in top_bandas:
            top_bandas_labels.append(tb['band__name'])
            top_bandas_data.append(float(tb['total']))

        chart_top_bandas = {
            'labels': top_bandas_labels,
            'data': top_bandas_data
        }

        # Tabelas

        # Tabela 1: Resumo por Banda
        band_summaries = []
        all_bands = Band.objects.filter(
            subscriptions__is_deleted=False,
            subscriptions__commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID
        ).distinct()
        if band_id:
            all_bands = all_bands.filter(id=band_id)

        for band in all_bands:
            band_billings = billings.filter(band=band)
            rec = band_billings.filter(status='PAGO', paid_date__gte=start_date, paid_date__lte=end_date).aggregate(total=Sum(Coalesce('net_amount', 'amount')))['total'] or 0
            pend = band_billings.filter(status='PENDENTE', due_date__gte=today, due_date__lte=end_date).aggregate(total=Sum(Coalesce('net_amount', 'amount')))['total'] or 0
            fut = band_billings.filter(status='PENDENTE', due_date__gt=today).aggregate(total=Sum(Coalesce('net_amount', 'amount')))['total'] or 0
            atr = band_billings.filter(Q(status='ATRASADO') | Q(status='PENDENTE', due_date__lt=today)).aggregate(total=Sum(Coalesce('net_amount', 'amount')))['total'] or 0

            band_summaries.append({
                'band': band,
                'subscription': band.subscriptions.filter(
                    status='ATIVO',
                    commercial_condition=BandSubscription.COMMERCIAL_CONDITION_PAID,
                    is_deleted=False
                ).first(),
                'recebido': rec,
                'pendente': pend,
                'futuro': fut,
                'atrasado': atr
            })


        # Compute KPIs for the template
        kpi_recebido = recebido
        kpi_pendente = billings.filter(status='PENDENTE', due_date__gte=today, due_date__lte=end_date).aggregate(total=Sum(Coalesce('net_amount', 'amount')))['total'] or 0
        kpi_futuro = billings.filter(status='PENDENTE', due_date__gt=end_date).aggregate(total=Sum(Coalesce('net_amount', 'amount')))['total'] or 0
        kpi_atrasado = cobrancas_vencidas

        # Context Update
        context.update({
            'kpi_recebido': kpi_recebido,
            'kpi_pendente': kpi_pendente,
            'kpi_futuro': kpi_futuro,
            'kpi_atrasado': kpi_atrasado,
            'kpi_receita_prevista': despesa_paga, # Despesas pagas no período
            'kpi_total_bandas': saldo_realizado, # Resultado do Período (Receitas Líquidas - Despesas Pagas)

            'start_date': start_date.strftime('%Y-%m-%d') if isinstance(start_date, datetime.date) else start_date,
            'end_date': end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime.date) else end_date,
            'band_id': band_id,
            'status': status,
            'plan': plan,
            'cycle': cycle,
            'period': period,

            'recebido': recebido,
            'despesa_paga': despesa_paga,
            'saldo_realizado': saldo_realizado,
            'a_receber': a_receber,
            'a_pagar': a_pagar,
            'cobrancas_vencidas': cobrancas_vencidas,
            'despesas_vencidas': despesas_vencidas,

            'chart_bars': json.dumps(chart_bars),
            'chart_pie': json.dumps(chart_pie),
            'chart_cycle': json.dumps(chart_cycle),
            'chart_top_bandas': json.dumps(chart_top_bandas),

            'band_summaries': band_summaries,
            'all_bands': Band.objects.filter(subscriptions__is_deleted=False).distinct().order_by('name'),
            'available_plans': BandSubscription.objects.filter(is_deleted=False).values_list('plan_name', flat=True).distinct().order_by('plan_name'),
            'billings': billings_period.select_related('band', 'subscription').order_by('-paid_date', '-due_date', '-created_at'),
            'expenses': expenses.select_related('created_by', 'updated_by').order_by('-due_date'),
            'expenses_period': expenses_period.select_related('created_by', 'updated_by').annotate(
                is_unpaid=Case(
                    When(status='PAGO', then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField()
                )
            ).order_by('is_unpaid', F('paid_date').desc(nulls_last=True), F('due_date').asc(nulls_last=True)),
        })

        from core.admin_views_expenses import ExpenseForm
        context['expense_form'] = ExpenseForm()

        return context

class AdminConfiguracoesView(AdminRequiredMixin, TemplateView):
    template_name = 'core/admin/configuracoes.html'

    def post(self, request, *args, **kwargs):
        settings = SystemSettings.get_settings()
        
        has_changes = False

        if 'logo' in request.FILES:
            settings.logo = request.FILES['logo']
            has_changes = True
            
        if 'ios_installation_guide_image' in request.FILES:
            settings.ios_installation_guide_image = request.FILES['ios_installation_guide_image']
            has_changes = True
            
        if 'android_installation_guide_image' in request.FILES:
            settings.android_installation_guide_image = request.FILES['android_installation_guide_image']
            has_changes = True

        if has_changes:
            settings.save()
            messages.success(request, "Configurações globais atualizadas com sucesso.")
            
        return redirect('admin_painel:configuracoes')


@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_band_create(request):
    if request.method == 'POST':
        form = AdminBandForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Banda cadastrada com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:bandas')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_band_edit(request, pk):
    band = get_object_or_404(Band, pk=pk)
    if request.method == 'POST':
        form = AdminBandForm(request.POST, request.FILES, instance=band)
        if form.is_valid():
            form.save()
            messages.success(request, "Banda atualizada com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:bandas')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_band_toggle_active(request, pk):
    if request.method == 'POST':
        band = get_object_or_404(Band, pk=pk)
        band.is_active = not band.is_active
        band.save()
        status = "ativada" if band.is_active else "desativada"
        messages.success(request, f"Banda {status} com sucesso!")
    return redirect('admin_painel:bandas')


@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_band_create_charge(request, pk=None):
    """
    BP-PEND-60 + BP-PEND-61: Gera uma cobrança/checkout Asaas para uma banda já existente no Backstage Pro.
    Respeita preços canônicos e vincula a ordem diretamente à Band.
    Retorna JSON (para AJAX) com links de pagamento e payload para compartilhamento WhatsApp.
    """
    band_id = pk or request.POST.get('band_id') or request.POST.get('band')
    band = get_object_or_404(Band, pk=band_id)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.POST.get('format') == 'json'

    if request.method != 'POST':
        if is_ajax:
            return JsonResponse({'ok': False, 'error': 'Método não permitido.'}, status=405)
        return redirect('admin_painel:assinaturas')

    plan_type = request.POST.get('plan_type', 'AVANCADO').strip().upper()
    if plan_type not in ('BASICO', 'AVANCADO'):
        plan_type = 'AVANCADO'

    billing_cycle = request.POST.get('billing_cycle', 'MENSAL').strip().upper()
    if billing_cycle not in ('MENSAL', 'ANUAL'):
        billing_cycle = 'MENSAL'

    payment_method = request.POST.get('payment_method', '').strip().upper()
    if payment_method not in ('PIX', 'CREDIT_CARD'):
        payment_method = None  # Aberto/Ambos

    # Obter ou auto-preencher dados de contato, responsável, documento fiscal e endereço
    responsible_name = request.POST.get('responsible_name', '').strip()
    email = request.POST.get('email', '').strip()
    phone = request.POST.get('phone', '').strip()
    cpf_cnpj = request.POST.get('cpf_cnpj', '').strip()

    postal_code = request.POST.get('postal_code', '').strip()
    address = request.POST.get('address', '').strip()
    address_number = request.POST.get('address_number', '').strip()
    complement = request.POST.get('complement', '').strip()
    province = request.POST.get('province', '').strip()
    city = request.POST.get('city', '').strip()
    state = request.POST.get('state', '').strip().upper()

    # Fallbacks inteligentes a partir dos usuários ou ordens/assinaturas da banda
    last_order = band.signup_orders.order_by('-created_at').first()
    prod_user = User.objects.filter(band=band, role__in=['PRODUTOR', 'EMPRESARIO']).order_by('-id').first()
    if not prod_user:
        prod_user = User.objects.filter(band=band).order_by('-id').first()
    last_sub = band.subscriptions.filter(is_deleted=False).order_by('-created_at').first()

    if not responsible_name:
        if prod_user and prod_user.get_full_name():
            responsible_name = prod_user.get_full_name()
        elif last_sub and last_sub.financial_responsible_name:
            responsible_name = last_sub.financial_responsible_name
        elif prod_user:
            responsible_name = prod_user.username
        else:
            responsible_name = band.name

    if not email:
        if prod_user and prod_user.email:
            email = prod_user.email
        elif last_sub and last_sub.billing_email:
            email = last_sub.billing_email

    if not phone:
        if prod_user and prod_user.phone:
            phone = prod_user.phone
        elif last_sub and last_sub.billing_phone:
            phone = last_sub.billing_phone

    if not cpf_cnpj:
        if last_order and last_order.cpf_cnpj:
            cpf_cnpj = last_order.cpf_cnpj
        elif prod_user and prod_user.cpf:
            cpf_cnpj = prod_user.cpf

    if not postal_code and last_order and last_order.postal_code:
        postal_code = last_order.postal_code
    if not address and last_order and last_order.address:
        address = last_order.address
    if not address_number and last_order and last_order.address_number:
        address_number = last_order.address_number
    if not complement and last_order and last_order.complement:
        complement = last_order.complement
    if not province and last_order and last_order.province:
        province = last_order.province
    if not city and last_order and last_order.city:
        city = last_order.city
    if not state and last_order and last_order.state:
        state = last_order.state.upper()

    # Validação de assinatura ativa existente (aviso/bloqueio suave se não houver confirmação)
    has_active = band.has_contracted_active_subscription
    confirm_override = request.POST.get('confirm_override') in ('true', '1', 'on')
    if has_active and not confirm_override:
        err = f"A banda '{band.name}' já possui uma assinatura ativa. Marque a confirmação para gerar nova cobrança."
        if is_ajax:
            return JsonResponse({'ok': False, 'warning_active': True, 'error': err}, status=400)
        messages.warning(request, err)
        return redirect('admin_painel:assinaturas')

    # Validações obrigatórias exigidas pelo Asaas para Checkout / Cobrança
    missing_fields = []
    if not responsible_name:
        missing_fields.append("Nome do Responsável")
    if not email:
        missing_fields.append("E-mail")
    if not cpf_cnpj:
        missing_fields.append("CPF ou CNPJ")
    if not postal_code:
        missing_fields.append("CEP")
    if not address:
        missing_fields.append("Endereço / Logradouro")
    if not address_number:
        missing_fields.append("Número")
    if not province:
        missing_fields.append("Bairro")
    if not city:
        missing_fields.append("Cidade")

    if missing_fields:
        err = f"Os seguintes campos obrigatórios não foram preenchidos: {', '.join(missing_fields)}."
        if is_ajax:
            return JsonResponse({'ok': False, 'error': err}, status=400)
        messages.error(request, err)
        return redirect('admin_painel:assinaturas')

    # Validação rigorosa de dígitos de CPF/CNPJ
    from core.forms_checkout import SignupOrderForm
    clean_digits = re.sub(r'\D', '', cpf_cnpj)
    if len(clean_digits) == 11:
        if not SignupOrderForm._validate_cpf(clean_digits):
            err = "CPF informado é inválido. Verifique os dígitos."
            if is_ajax:
                return JsonResponse({'ok': False, 'error': err}, status=400)
            messages.error(request, err)
            return redirect('admin_painel:assinaturas')
    elif len(clean_digits) == 14:
        if not SignupOrderForm._validate_cnpj(clean_digits):
            err = "CNPJ informado é inválido. Verifique os dígitos."
            if is_ajax:
                return JsonResponse({'ok': False, 'error': err}, status=400)
            messages.error(request, err)
            return redirect('admin_painel:assinaturas')
    else:
        err = "Documento fiscal inválido. Informe um CPF válido (11 dígitos) ou CNPJ (14 dígitos)."
        if is_ajax:
            return JsonResponse({'ok': False, 'error': err}, status=400)
        messages.error(request, err)
        return redirect('admin_painel:assinaturas')

    # Preço canônico centralizado
    canonical_price = SystemSettings.get_canonical_plan_price(plan_type, billing_cycle)

    # Identificar se já existe um Customer Asaas prévio para esta banda (evitar duplicação em retentativas)
    existing_customer_id = None
    existing_sub_with_customer = band.subscriptions.filter(
        gateway_customer_id__isnull=False
    ).exclude(gateway_customer_id='').first()
    if existing_sub_with_customer and existing_sub_with_customer.gateway_customer_id:
        existing_customer_id = existing_sub_with_customer.gateway_customer_id
    else:
        existing_order_with_customer = band.signup_orders.filter(
            gateway_customer_id__isnull=False
        ).exclude(gateway_customer_id='').order_by('-id').first()
        if existing_order_with_customer and existing_order_with_customer.gateway_customer_id:
            existing_customer_id = existing_order_with_customer.gateway_customer_id

    # Criação do SignupOrder vinculado à Band existente
    from core.models import SignupOrder
    from core.services.payments.checkout import create_asaas_checkout_for_signup_order
    from core.views import build_whatsapp_charge_data

    ext_ref = f"bp-adm-{band.id}-{uuid.uuid4().hex[:8]}"

    signup_order = SignupOrder.objects.create(
        band=band,
        external_reference=ext_ref,
        gateway_provider='ASAAS',
        gateway_customer_id=existing_customer_id or None,
        band_name=band.name,
        responsible_name=responsible_name,
        email=email,
        phone=phone or '',
        cpf_cnpj=clean_digits,
        postal_code=postal_code,
        address=address,
        address_number=address_number,
        complement=complement or '',
        province=province,
        city=city,
        state=state[:2] if state else '',
        plan_type=plan_type,
        billing_cycle=billing_cycle,
        amount=canonical_price,
        status='PENDENTE'
    )

    success, checkout_url, res_data, err_msg = create_asaas_checkout_for_signup_order(
        signup_order,
        payment_method=payment_method
    )

    if not success or not checkout_url:
        signup_order.status = 'FALHOU'
        signup_order.save(update_fields=['status', 'updated_at'])

        # Montar mensagem de erro amigável a partir da resposta do Asaas
        friendly_err = "Falha ao gerar cobrança no Asaas."
        if res_data and isinstance(res_data, dict):
            errors = res_data.get('errors')
            if isinstance(errors, list) and errors:
                desc_list = [e.get('description') for e in errors if isinstance(e, dict) and e.get('description')]
                if desc_list:
                    friendly_err = f"Asaas: {'; '.join(desc_list)}"
            elif res_data.get('message'):
                friendly_err = f"Asaas: {res_data.get('message')}"
        elif err_msg:
            friendly_err = f"Asaas: {err_msg}"

        if is_ajax:
            return JsonResponse({'ok': False, 'error': friendly_err}, status=400)
        messages.error(request, f"Erro ao gerar cobrança: {friendly_err}")
        return redirect('admin_painel:assinaturas')

    amount_formatted = f"{canonical_price:.2f}".replace('.', ',')

    whatsapp_data = build_whatsapp_charge_data(
        responsible_name=responsible_name,
        band_name=band.name,
        plan_type=plan_type,
        billing_cycle=billing_cycle,
        amount_str=amount_formatted,
        checkout_url=checkout_url,
        phone=phone
    )

    if is_ajax:
        return JsonResponse({
            'ok': True,
            'checkout_url': checkout_url,
            'external_reference': signup_order.external_reference,
            'amount': amount_formatted,
            'plan_display': 'Avançado' if plan_type == 'AVANCADO' else 'Básico',
            'cycle_display': 'Anual' if billing_cycle == 'ANUAL' else 'Mensal',
            'message': f"Cobrança gerada com sucesso para a banda {band.name}!",
            'whatsapp': whatsapp_data
        })

    messages.success(request, f"Cobrança criada com sucesso para a banda '{band.name}'! Link: {checkout_url}")
    return redirect('admin_painel:assinaturas')


@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_user_create(request):
    if request.method == 'POST':
        form = AdminUserCreateForm(request.POST)
        if form.is_valid():
            raw_password = form.cleaned_data.get('password')
            user = form.save(commit=False)
            user.save()

            # BP-PEND-62/63: Criar UserBandMembership para cada banda selecionada (sem duplicidade)
            band_ids_raw = request.POST.getlist('band_ids')
            legacy_band = request.POST.get('band')
            if not band_ids_raw and legacy_band:
                band_ids_raw = [legacy_band]

            seen_band_ids = set()
            ordered_band_ids = []
            for b_id in band_ids_raw:
                if b_id and str(b_id).isdigit() and b_id not in seen_band_ids:
                    seen_band_ids.add(b_id)
                    ordered_band_ids.append(b_id)

            first_band = None
            first_role = request.POST.get('role', 'INTEGRANTE')
            valid_roles = {'INTEGRANTE', 'PRODUTOR', 'EMPRESARIO'}
            for idx, band_id in enumerate(ordered_band_ids):
                try:
                    band_obj = Band.objects.get(id=band_id)
                    role = request.POST.get(f'role_{band_id}', request.POST.get('role', 'INTEGRANTE'))
                    if role not in valid_roles:
                        role = 'INTEGRANTE'
                    UserBandMembership.objects.update_or_create(
                        user=user, band=band_obj,
                        defaults={'role': role, 'is_active': True}
                    )
                    if idx == 0:
                        first_band = band_obj
                        first_role = role
                except Band.DoesNotExist:
                    pass

            # Backward compat: sincroniza user.band e user.role com o primeiro vínculo
            update_fields = []
            if first_band:
                user.band = first_band
                user.role = first_role
                update_fields.extend(['band', 'role'])
            # Força must_change_password para integrantes
            if first_role == 'INTEGRANTE':
                user.must_change_password = True
                update_fields.append('must_change_password')
            if update_fields:
                user.save(update_fields=update_fields)

            request.session['whatsapp_access_data'] = build_whatsapp_access_data(
                band=user.band,
                user=user,
                raw_password=raw_password,
                is_admin_created=True
            )
            messages.success(request, "Usuário cadastrado com sucesso!")
            return redirect('admin_painel:usuarios')
        else:
            bandas_qs = Band.objects.all().order_by('name')
            usuarios_qs = User.objects.all().order_by(F('band__name').asc(nulls_last=True), 'first_name', 'username')
            context = {
                'usuarios': usuarios_qs,
                'bandas': bandas_qs,
                'bandas_list': bandas_qs,
                'form_create': form,
                'open_create_modal': True,
                'whatsapp_access_data': None,
                'q': '',
                'selected_band': '',
            }
            return render(request, 'core/admin/usuarios.html', context)
    return redirect('admin_painel:usuarios')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = AdminUserEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()

            # BP-PEND-62/63: Atualizar UserBandMembership com deduplicação
            band_ids_raw = request.POST.getlist('band_ids')
            legacy_band = request.POST.get('band')
            if not band_ids_raw and legacy_band is not None:
                band_ids_raw = [legacy_band] if legacy_band else []

            seen_band_ids = set()
            ordered_band_ids = []
            for b_id in band_ids_raw:
                if b_id and str(b_id).isdigit() and b_id not in seen_band_ids:
                    seen_band_ids.add(b_id)
                    ordered_band_ids.append(b_id)

            band_ids_submitted = set(ordered_band_ids)
            valid_roles = {'INTEGRANTE', 'PRODUTOR', 'EMPRESARIO'}

            # Remove vínculos que foram desmarcados/removidos
            UserBandMembership.objects.filter(user=user).exclude(
                band_id__in=band_ids_submitted
            ).delete()

            # Cria ou atualiza vínculos submetidos
            first_band = None
            first_role = request.POST.get('role', 'INTEGRANTE')
            for idx, band_id in enumerate(ordered_band_ids):
                try:
                    band_obj = Band.objects.get(id=band_id)
                    role = request.POST.get(f'role_{band_id}', request.POST.get('role', 'INTEGRANTE'))
                    if role not in valid_roles:
                        role = 'INTEGRANTE'
                    UserBandMembership.objects.update_or_create(
                        user=user, band=band_obj,
                        defaults={'role': role, 'is_active': True}
                    )
                    if idx == 0:
                        first_band = band_obj
                        first_role = role
                except Band.DoesNotExist:
                    pass

            # Backward compat: sincroniza user.band e user.role
            update_fields = []
            if first_band:
                user.band = first_band
                user.role = first_role
                update_fields.extend(['band', 'role'])
            elif not band_ids_submitted:
                user.band = None
                update_fields.append('band')
            if update_fields:
                user.save(update_fields=update_fields)

            messages.success(request, "Usuário atualizado com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:usuarios')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_band_search_api(request):
    """
    BP-PEND-63: Endpoint assíncrono para busca escalável de bandas no admin geral.
    Busca case-insensitive por nome ou slug, limitada a até 20 resultados.
    """
    q = request.GET.get('q', '').strip()
    if not q or len(q) < 2:
        return JsonResponse({'results': []})

    bands = Band.objects.filter(
        Q(name__icontains=q) | Q(slug__icontains=q)
    ).order_by('name')[:20]

    results = [{'id': b.id, 'name': b.name, 'slug': b.slug} for b in bands]
    return JsonResponse({'results': results})

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_user_toggle_active(request, pk):
    if request.method == 'POST':
        user = get_object_or_404(User, pk=pk)
        user.is_active = not user.is_active
        user.save()
        status = "ativado" if user.is_active else "desativado"
        messages.success(request, f"Usuário {status} com sucesso!")
    return redirect('admin_painel:usuarios')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_user_reset_password(request, pk):
    if request.method == 'POST':
        user = get_object_or_404(User, pk=pk)
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')

        if not new_password or not confirm_password:
            messages.error(request, "As senhas não podem ser vazias.")
        elif new_password != confirm_password:
            messages.error(request, "As senhas não conferem. Tente novamente.")
        else:
            user.set_password(new_password)
            user.save()
            messages.success(request, f"Senha do usuário {user.username} redefinida com sucesso!")

    return redirect('admin_painel:usuarios')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_user_share_whatsapp(request, pk):
    """
    BP-PEND-ADMIN: Valida obrigatoriamente se o usuário possui telefone/WhatsApp válido
    ANTES de qualquer alteração de credenciais. Se não houver telefone válido, nenhuma
    senha é alterada ou salva. Se houver telefone válido, define a senha provisória,
    atualiza o usuário e prepara o link do WhatsApp para envio.
    """
    if request.method == 'POST':
        user = get_object_or_404(User, pk=pk)

        # 1. Verificar se o usuário possui telefone cadastrado e normalizável
        phone_raw = (user.phone or '').strip()
        digits = re.sub(r'\D', '', phone_raw)
        has_valid_phone = bool(digits and len(digits) >= 10)

        if not has_valid_phone:
            messages.warning(
                request,
                "Este usuário não possui telefone/WhatsApp cadastrado. "
                "Cadastre um número antes de compartilhar o acesso."
            )
            return redirect('admin_painel:usuarios')

        # 2. Verificar se o usuário já possui senha utilizável
        from core.views import build_admin_user_whatsapp_access_data
        has_usable_pwd = user.has_usable_password()

        if has_usable_pwd:
            # Usuário já possui senha utilizável:
            # - NÃO exigir provisional_password
            # - NÃO executar set_password()
            # - NÃO alterar/salvar credenciais
            whatsapp_data = build_admin_user_whatsapp_access_data(user, raw_password="")
            request.session['whatsapp_access_data'] = whatsapp_data
            messages.success(
                request,
                f"Dados de acesso prontos para compartilhar com '{user.username}' pelo WhatsApp!"
            )
        else:
            # Usuário sem senha utilizável:
            # - Exigir provisional_password
            # - Executar set_password() e salvar
            provisional_password = request.POST.get('provisional_password', '').strip()
            if not provisional_password:
                messages.error(request, "A senha provisória não pode ser vazia.")
                return redirect('admin_painel:usuarios')

            user.set_password(provisional_password)
            user.save()

            whatsapp_data = build_admin_user_whatsapp_access_data(user, provisional_password, is_provisional=True)
            request.session['whatsapp_access_data'] = whatsapp_data
            messages.success(
                request,
                f"Senha provisória definida com sucesso para '{user.username}'. Pronto para compartilhar pelo WhatsApp!"
            )

    return redirect('admin_painel:usuarios')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_assinatura_create(request):
    if request.method == 'POST':
        form = AdminSubscriptionForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Assinatura cadastrada com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:assinaturas')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_assinatura_edit(request, pk):
    from django.utils import timezone
    import datetime
    from core.models import BillingRecord
    
    sub = get_object_or_404(BandSubscription, pk=pk)
    if request.method == 'POST':
        form = AdminSubscriptionForm(request.POST, instance=sub)
        if form.is_valid():
            sub = form.save()
            
            # Sincroniza faturas pendentes com a nova data da assinatura (SOMENTE para assinaturas PAGO)
            if not sub.is_partnership and sub.next_due_date:
                today = timezone.localdate()
                seven_days = today + datetime.timedelta(days=7)
                
                pending_invoices = BillingRecord.objects.filter(subscription=sub, status='PENDENTE')
                
                if sub.next_due_date > seven_days:
                    # Nova data tá mais de 7 dias pra frente, exclui faturas pendentes
                    pending_invoices.delete()
                else:
                    # Dentro de 7 dias (ou já passou). Garantimos que a fatura reflete a assinatura.
                    month_names = {
                        1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
                        5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
                        9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
                    }
                    ref_period = f"{month_names[sub.next_due_date.month]}/{sub.next_due_date.year}"
                    
                    if pending_invoices.exists():
                        # Atualiza a fatura pendente existente
                        for inv in pending_invoices:
                            inv.due_date = sub.next_due_date
                            inv.amount = sub.contracted_value
                            inv.reference_period = ref_period
                            inv.plan_name = getattr(sub, 'plan_name', '')
                            inv.billing_cycle = sub.billing_cycle
                            inv.save()
                    else:
                        # Se não existir, cria a fatura imediatamente para já aparecer na tela
                        BillingRecord.objects.create(
                            subscription=sub,
                            band=sub.band,
                            reference_period=ref_period,
                            amount=sub.contracted_value,
                            due_date=sub.next_due_date,
                            status='PENDENTE',
                            plan_name=getattr(sub, 'plan_name', ''),
                            billing_cycle=sub.billing_cycle,
                        )

            messages.success(request, "Assinatura atualizada com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:assinaturas')

from django.utils import timezone
@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_assinatura_cancel(request, pk):
    if request.method == 'POST':
        sub = get_object_or_404(BandSubscription, pk=pk)
        sub.is_deleted = True
        sub.deleted_at = timezone.now()
        sub.status = 'DESATIVADO'
        sub.save()
        messages.success(request, "Assinatura excluída com sucesso!")
    return redirect('admin_painel:assinaturas')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_identificar_cobranca_asaas(request):
    """
    Consulta somente de leitura para identificar uma cobrança Asaas por ID (pay_...)
    ou pelo número da fatura (invoiceNumber) e localizar de forma comprovada e única
    a Banda e Assinatura correspondente.
    Não altera dados locais e não faz mutações na API Asaas.
    """
    if request.method not in ('GET', 'POST'):
        return JsonResponse({'ok': False, 'error': 'Método não permitido.'}, status=405)

    raw_query = request.POST.get('payment_id') or request.GET.get('payment_id') or ''
    query_str = raw_query.strip()

    if not query_str:
        return JsonResponse({
            'ok': False,
            'status': 'Vínculo não identificado',
            'error': 'Informe o ID da cobrança (pay_...) ou o número da fatura.'
        }, status=400)

    from core.services.payments.asaas.client import AsaasClient
    client = AsaasClient()

    if not client.config.api_key:
        return JsonResponse({
            'ok': False,
            'status': 'Vínculo não identificado',
            'error': 'Integração Asaas não configurada neste ambiente.'
        }, status=400)

    # Caso 1: ID direto de cobrança Asaas (inicia com pay_ ou PAY_)
    if query_str.startswith('pay_') or query_str.startswith('PAY_'):
        payment_info = client.get_payment(query_str)
        if not payment_info or not isinstance(payment_info, dict):
            return JsonResponse({
                'ok': False,
                'status': 'Vínculo não identificado',
                'payment_id': query_str,
                'subscription_id': None,
                'invoice_number': None,
                'message': 'Cobrança não encontrada no gateway Asaas para o ambiente configurado.'
            })

        sub_id = payment_info.get('subscription')
        customer_id = payment_info.get('customer')
        payment_id = payment_info.get('id', query_str)
        invoice_number = payment_info.get('invoiceNumber')
        payment_status = payment_info.get('status')

        if not sub_id:
            return JsonResponse({
                'ok': False,
                'status': 'Vínculo não identificado',
                'payment_id': payment_id,
                'subscription_id': None,
                'invoice_number': invoice_number,
                'customer_id': customer_id,
                'message': 'Esta cobrança existe no Asaas, porém não possui assinatura de origem (cobrança avulsa ou parcelamento).'
            })

        matching_subs = BandSubscription.objects.filter(
            is_deleted=False,
            gateway_subscription_id=sub_id
        ).select_related('band')

        if matching_subs.count() == 1:
            subscription = matching_subs.first()
            # Validar consistência do customer se cadastrado na assinatura local
            if subscription.gateway_customer_id and customer_id and subscription.gateway_customer_id != customer_id:
                return JsonResponse({
                    'ok': False,
                    'status': 'Ambíguo',
                    'payment_id': payment_id,
                    'subscription_id': sub_id,
                    'invoice_number': invoice_number,
                    'message': 'O ID do cliente (customer) no Asaas diverge do cliente registrado na assinatura local.'
                })

            band = subscription.band
            return JsonResponse({
                'ok': True,
                'status': 'Comprovado',
                'payment_id': payment_id,
                'subscription_id': sub_id,
                'invoice_number': invoice_number,
                'payment_status': payment_status,
                'band': {
                    'id': band.id,
                    'name': band.name,
                    'slug': getattr(band, 'slug', '')
                },
                'subscription': {
                    'id': subscription.id,
                    'plan_name': subscription.plan_name or subscription.get_billing_cycle_display(),
                    'billing_cycle': subscription.billing_cycle,
                    'status': subscription.status,
                    'contracted_value': str(subscription.contracted_value),
                    'next_due_date': subscription.next_due_date.strftime('%d/%m/%Y') if subscription.next_due_date else None,
                    'external_reference': subscription.gateway_external_reference or ''
                }
            })
        elif matching_subs.count() > 1:
            return JsonResponse({
                'ok': False,
                'status': 'Ambíguo',
                'payment_id': payment_id,
                'subscription_id': sub_id,
                'invoice_number': invoice_number,
                'message': 'Mais de uma assinatura no sistema possui o mesmo ID de assinatura Asaas. Não foi possível garantir vínculo único.'
            })
        else:
            return JsonResponse({
                'ok': False,
                'status': 'Vínculo não identificado',
                'payment_id': payment_id,
                'subscription_id': sub_id,
                'invoice_number': invoice_number,
                'message': f'A cobrança pertence à assinatura Asaas {sub_id}, mas nenhuma banda local está vinculada a este ID.'
            })

    # Caso 2: Número de fatura (invoiceNumber)
    # Busca sob demanda e somente por GET /v3/subscriptions/{gateway_subscription_id}/payments
    # em todas as assinaturas locais ativas com gateway_subscription_id configurado.
    active_subs = list(
        BandSubscription.objects.filter(
            is_deleted=False
        ).exclude(
            gateway_subscription_id__isnull=True
        ).exclude(
            gateway_subscription_id=''
        ).select_related('band')
    )

    matches = []

    for sub in active_subs:
        sub_id = sub.gateway_subscription_id
        # Consulta pagamentos da assinatura considerando paginação completa
        payments = client.get_payments_by_subscription(sub_id, limit=50, fetch_all=True)
        for p in payments:
            p_invoice = str(p.get('invoiceNumber') or '').strip()
            # Se invoiceNumber não veio na listagem da assinatura, recupera a cobrança individual
            if not p_invoice and p.get('id'):
                individual_p = client.get_payment(p['id'])
                if individual_p and isinstance(individual_p, dict):
                    p_invoice = str(individual_p.get('invoiceNumber') or '').strip()
                    p = individual_p

            if p_invoice == query_str:
                p_customer = p.get('customer')
                p_sub = p.get('subscription')
                # Confirmar correspondência exata de subscription
                if p_sub != sub_id:
                    continue
                # Se houver customer registrado na assinatura local, confirmar correspondência exata
                if sub.gateway_customer_id and p_customer and sub.gateway_customer_id != p_customer:
                    continue

                matches.append({
                    'payment': p,
                    'subscription': sub,
                    'band': sub.band
                })

    if len(matches) == 1:
        match = matches[0]
        matched_payment = match['payment']
        matched_sub = match['subscription']
        matched_band = match['band']
        return JsonResponse({
            'ok': True,
            'status': 'Comprovado',
            'payment_id': matched_payment.get('id'),
            'subscription_id': matched_sub.gateway_subscription_id,
            'invoice_number': matched_payment.get('invoiceNumber') or query_str,
            'payment_status': matched_payment.get('status'),
            'band': {
                'id': matched_band.id,
                'name': matched_band.name,
                'slug': getattr(matched_band, 'slug', '')
            },
            'subscription': {
                'id': matched_sub.id,
                'plan_name': matched_sub.plan_name or matched_sub.get_billing_cycle_display(),
                'billing_cycle': matched_sub.billing_cycle,
                'status': matched_sub.status,
                'contracted_value': str(matched_sub.contracted_value),
                'next_due_date': matched_sub.next_due_date.strftime('%d/%m/%Y') if matched_sub.next_due_date else None,
                'external_reference': matched_sub.gateway_external_reference or ''
            }
        })
    elif len(matches) > 1:
        return JsonResponse({
            'ok': False,
            'status': 'Ambíguo',
            'invoice_number': query_str,
            'matches_count': len(matches),
            'message': f'A fatura {query_str} foi encontrada em múltiplas assinaturas. Não foi possível garantir vínculo único.'
        })
    else:
        return JsonResponse({
            'ok': False,
            'status': 'Vínculo não identificado',
            'invoice_number': query_str,
            'message': f'Fatura {query_str} não encontrada em nenhuma assinatura ativa consultada no Asaas.'
        })


@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_ver_cobrancas_banda_asaas(request, subscription_id):
    """
    Consulta sob demanda e somente por GET as cobranças da assinatura Asaas de uma banda.
    Retorna a lista de cobranças com payment_id, invoiceNumber, valor, vencimento e status.
    Não altera nem cancela cobranças ou assinaturas.
    """
    if request.method != 'GET':
        return JsonResponse({'ok': False, 'error': 'Método não permitido.'}, status=405)

    subscription = get_object_or_404(
        BandSubscription.objects.select_related('band'),
        id=subscription_id,
        is_deleted=False
    )

    gateway_sub_id = subscription.gateway_subscription_id
    if not gateway_sub_id:
        return JsonResponse({
            'ok': False,
            'error': 'Esta banda não possui ID de assinatura no Asaas cadastrado.'
        }, status=400)

    from core.services.payments.asaas.client import AsaasClient
    client = AsaasClient()

    if not client.config.api_key:
        return JsonResponse({
            'ok': False,
            'error': 'Integração Asaas não configurada neste ambiente.'
        }, status=400)

    payments = client.get_payments_by_subscription(gateway_sub_id, limit=50, fetch_all=True)

    items = []
    for p in payments:
        inv_num = p.get('invoiceNumber')
        p_id = p.get('id')
        if not inv_num and p_id:
            ind_p = client.get_payment(p_id)
            if ind_p and isinstance(ind_p, dict):
                inv_num = ind_p.get('invoiceNumber')
                p = ind_p

        items.append({
            'id': p.get('id'),
            'invoice_number': inv_num or '-',
            'value': str(p.get('value', '')),
            'status': p.get('status', '-'),
            'due_date': p.get('dueDate', '-'),
            'payment_date': p.get('paymentDate') or p.get('clientPaymentDate') or '-',
            'billing_type': p.get('billingType', '-'),
            'invoice_url': p.get('invoiceUrl') or ''
        })

    return JsonResponse({
        'ok': True,
        'band_name': subscription.band.name,
        'gateway_subscription_id': gateway_sub_id,
        'gateway_customer_id': subscription.gateway_customer_id,
        'total_payments': len(items),
        'payments': items
    })


@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_band_cobrancas_periodo(request, band_id):
    """
    Retorna a lista de cobranças (BillingRecord) de uma banda específica para o modal
    'Editar recebido' no relatório financeiro, com cálculo de diferença e auditoria.
    """
    if request.method != 'GET':
        return JsonResponse({'ok': False, 'error': 'Método não permitido.'}, status=405)

    band = get_object_or_404(Band, pk=band_id)
    records = BillingRecord.objects.filter(
        band=band,
        subscription__is_deleted=False
    ).select_related('subscription', 'net_amount_updated_by').order_by('-due_date')

    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')

    if start_date_str and end_date_str:
        try:
            s_date = datetime.datetime.strptime(start_date_str, '%Y-%m-%d').date()
            e_date = datetime.datetime.strptime(end_date_str, '%Y-%m-%d').date()
            records = records.filter(
                Q(paid_date__gte=s_date, paid_date__lte=e_date) |
                Q(paid_date__isnull=True, due_date__gte=s_date, due_date__lte=e_date)
            )
        except ValueError:
            pass

    cobrancas_data = []
    for r in records:
        net_val = r.net_amount if r.net_amount is not None else r.amount
        diff = r.amount - net_val
        cobrancas_data.append({
            'id': r.id,
            'reference_period': r.reference_period,
            'amount': str(r.amount),
            'net_amount': str(r.net_amount) if r.net_amount is not None else '',
            'difference': str(diff),
            'status': r.status,
            'status_display': r.get_status_display(),
            'due_date': r.due_date.strftime('%d/%m/%Y') if r.due_date else '-',
            'paid_date': r.paid_date.strftime('%d/%m/%Y') if r.paid_date else '-',
            'gateway_payment_id': r.gateway_payment_id or '-',
            'gateway_invoice_url': r.gateway_invoice_url or '',
            'net_amount_manual': r.net_amount_manual,
            'net_amount_reason': r.net_amount_reason or '',
            'net_amount_updated_at': r.net_amount_updated_at.strftime('%d/%m/%Y %H:%M') if r.net_amount_updated_at else '',
            'net_amount_updated_by': r.net_amount_updated_by.get_full_name() or r.net_amount_updated_by.username if r.net_amount_updated_by else '',
        })

    return JsonResponse({
        'ok': True,
        'band_name': band.name,
        'band_id': band.id,
        'cobrancas': cobrancas_data
    })


@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_billing_adjust_net_amount(request, pk):
    """
    Permite informar ou atualizar o valor líquido de uma cobrança individualmente,
    com motivo e histórico da correção. Não altera nem cancela dados no Asaas.
    """
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'Método não permitido.'}, status=405)

    record = get_object_or_404(BillingRecord, pk=pk)

    raw_net = request.POST.get('net_amount')
    reason = request.POST.get('reason', '').strip()

    if raw_net is None or raw_net.strip() == '':
        # Remover correção manual e restaurar o valor bruto original
        record.net_amount = None
        record.net_amount_manual = False
        record.net_amount_reason = reason or 'Correção manual removida.'
        record.net_amount_updated_at = timezone.now()
        record.net_amount_updated_by = request.user if request.user.is_authenticated else None
        record.save()
        return JsonResponse({
            'ok': True,
            'message': 'Valor líquido restaurado ao valor bruto original.',
            'amount': str(record.amount),
            'net_amount': str(record.amount),
            'difference': '0.00'
        })

    try:
        clean_net = raw_net.strip().replace('R$', '').replace(' ', '').replace(',', '.')
        net_decimal = Decimal(clean_net)
        if net_decimal < 0:
            return JsonResponse({'ok': False, 'error': 'O valor líquido não pode ser negativo.'}, status=400)
    except Exception:
        return JsonResponse({'ok': False, 'error': 'Formato de valor inválido.'}, status=400)

    if not reason:
        return JsonResponse({'ok': False, 'error': 'Por favor, informe o motivo da correção.'}, status=400)

    record.net_amount = net_decimal
    record.net_amount_manual = True
    record.net_amount_reason = reason
    record.net_amount_updated_at = timezone.now()
    if request.user.is_authenticated:
        record.net_amount_updated_by = request.user
    record.save()

    diff = record.amount - record.net_amount

    return JsonResponse({
        'ok': True,
        'message': 'Valor líquido atualizado com sucesso!',
        'amount': str(record.amount),
        'net_amount': str(record.net_amount),
        'difference': str(diff),
        'reason': record.net_amount_reason,
        'updated_at': record.net_amount_updated_at.strftime('%d/%m/%Y %H:%M'),
        'updated_by': record.net_amount_updated_by.get_full_name() or record.net_amount_updated_by.username if record.net_amount_updated_by else ''
    })


@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_cobranca_create(request):
    if request.method == 'POST':
        form = AdminBillingRecordForm(request.POST, request.FILES)
        if form.is_valid():
            record = form.save(commit=False)
            record.created_by = request.user
            record.save()

            # Auto-ativa a assinatura se a fatura for paga
            if record.status == 'PAGO' and record.subscription:
                sub = record.subscription
                if sub.status != 'ATIVO':
                    sub.status = 'ATIVO'
                    sub.save(update_fields=['status'])

            messages.success(request, "Cobrança gerada com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:cobrancas')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_cobranca_edit(request, pk):
    record = get_object_or_404(BillingRecord, pk=pk)
    if request.method == 'POST':
        form = AdminBillingRecordForm(request.POST, request.FILES, instance=record)
        if form.is_valid():
            record = form.save()

            # Auto-ativa a assinatura se a fatura for paga
            if record.status == 'PAGO' and record.subscription:
                sub = record.subscription
                if sub.status != 'ATIVO':
                    sub.status = 'ATIVO'
                    sub.save(update_fields=['status'])

            messages.success(request, "Cobrança atualizada com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:cobrancas')



from django.db import transaction
from dateutil.relativedelta import relativedelta
from datetime import date
from django.contrib import messages

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_cobranca_pagar(request, pk):
    if request.method == 'POST':
        rec = get_object_or_404(BillingRecord, pk=pk)
        
        # Check if already paid to prevent double payment
        if rec.status == 'PAGO':
            messages.warning(request, "Esta fatura já consta como paga.")
            return redirect('admin_painel:cobrancas')
            
        paid_date_str = request.POST.get('paid_date')
        payment_method = request.POST.get('payment_method', '')
        notes = request.POST.get('notes', '')
        
        try:
            paid_date = datetime.datetime.strptime(paid_date_str, '%Y-%m-%d').date() if paid_date_str else timezone.localdate()
        except ValueError:
            paid_date = timezone.localdate()
            
        with transaction.atomic():
            rec.paid_date = paid_date
            rec.status = 'PAGO'
            
            # If the user model is available, maybe save in notes or log somewhere
            admin_user = request.user.get_full_name() or request.user.username
            rec.notes = f"{rec.notes}\n[Pago recebido via {payment_method} em {paid_date} por {admin_user}]. Obs: {notes}".strip()
            rec.save()
            
            sub = rec.subscription
            if sub and sub.auto_renew:
                # Calculate new due date based on previous due date, not paid_date
                old_date = sub.next_due_date or rec.due_date
                
                cycle = sub.billing_cycle
                if cycle == 'MENSAL':
                    new_date = old_date + relativedelta(months=1)
                elif cycle == 'BIMESTRAL':
                    new_date = old_date + relativedelta(months=2)
                elif cycle == 'TRIMESTRAL':
                    new_date = old_date + relativedelta(months=3)
                elif cycle == 'SEMESTRAL':
                    new_date = old_date + relativedelta(months=6)
                elif cycle == 'ANUAL':
                    new_date = old_date + relativedelta(months=12)
                else:
                    # fallback
                    new_date = old_date + relativedelta(months=1)
                
                sub.next_due_date = new_date
                sub.save()
                messages.success(request, f"Pagamento confirmado. Assinatura renovada automaticamente até {new_date.strftime('%d/%m/%Y')}.")
            else:
                messages.success(request, "Pagamento confirmado. A assinatura não foi renovada automaticamente.")
                
    return redirect('admin_painel:cobrancas')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_cobranca_delete(request, pk):
    if request.method == 'POST':
        rec = get_object_or_404(BillingRecord, pk=pk)
        rec.delete()
        messages.success(request, "Fatura excluída com sucesso!")
    return redirect('admin_painel:cobrancas')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_cobranca_change_status(request, pk, status):
    if request.method == 'POST':
        record = get_object_or_404(BillingRecord, pk=pk)
        if status in dict(BillingRecord.STATUS_CHOICES):
            record.status = status
            if status == 'PAGO' and not record.paid_date:
                record.paid_date = datetime.date.today()
            record.save()

            # Auto-ativa a assinatura se a fatura for paga
            if status == 'PAGO' and record.subscription:
                sub = record.subscription
                if sub.status != 'ATIVO':
                    sub.status = 'ATIVO'
                    sub.save(update_fields=['status'])

            messages.success(request, f"Status alterado para {record.get_status_display()}!")
    return redirect('admin_painel:cobrancas')

def is_admin_web_push(user):
    return user.is_authenticated and (user.is_superuser or user.has_perm('core.view_webpushdelivery'))

class AdminWebPushRequiredMixin:
    @method_decorator(user_passes_test(is_admin_web_push, login_url='/painel/login/'))
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)

from django.views.decorators.http import require_GET
from core.services.web_push_operations import build_web_push_health_snapshot, build_web_push_operational_alerts, list_recent_problematic_deliveries

@method_decorator(require_GET, name='dispatch')
class AdminWebPushDashboardView(AdminWebPushRequiredMixin, TemplateView):
    template_name = 'core/admin/web_push_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        band_slug = self.request.GET.get('band_slug', '').strip() or None

        try:
            hours = int(self.request.GET.get('hours', 24))
            if not (1 <= hours <= 720):
                hours = 24
        except ValueError:
            hours = 24

        try:
            stale_pending_minutes = int(self.request.GET.get('stale_pending_minutes', 10))
            if not (5 <= stale_pending_minutes <= 10080):
                stale_pending_minutes = 10
        except ValueError:
            stale_pending_minutes = 10

        try:
            stale_sending_minutes = int(self.request.GET.get('stale_sending_minutes', 15))
            if not (5 <= stale_sending_minutes <= 10080):
                stale_sending_minutes = 15
        except ValueError:
            stale_sending_minutes = 15

        try:
            limit = int(self.request.GET.get('limit', 50))
            if not (1 <= limit <= 100):
                limit = 50
        except ValueError:
            limit = 50

        if band_slug:
            from core.models import Band
            if not Band.objects.filter(slug=band_slug).exists():
                messages.warning(self.request, "A banda informada não foi encontrada.")
                snapshot = {
                    "deliveries": {
                        "total": {"total": 0, "PENDING": 0, "SENDING": 0, "SENT": 0, "TEMPORARY_FAILURE": 0, "PERMANENT_FAILURE": 0, "SKIPPED": 0},
                        "recent_window": {"created": 0, "sent": 0, "temporary_failure": 0, "permanent_failure": 0, "skipped": 0},
                        "rates": {"completed": 0, "success_rate": None}
                    },
                    "subscriptions": {"total": 0, "active": 0, "active_with_failures": 0},
                    "anomalies": {"stale_sending_count": 0, "stale_pending_count": 0, "active_expired_subscriptions_count": 0}
                }
                alerts = []
                problematic_deliveries = []
                overall_state = "NO_DATA"
                context.update({
                    'snapshot': snapshot,
                    'alerts': alerts,
                    'problematic_deliveries': problematic_deliveries,
                    'current_band_slug': band_slug,
                    'current_hours': hours,
                    'current_stale_pending': stale_pending_minutes,
                    'current_stale_sending': stale_sending_minutes,
                    'current_limit': limit,
                    'invalid_band_filter': True,
                    'overall_state': overall_state,
                    'active_incidents': [],
                    'recently_resolved': [],
                })
                return context

        snapshot = build_web_push_health_snapshot(
            window_hours=hours,
            stale_pending_minutes=stale_pending_minutes,
            stale_sending_minutes=stale_sending_minutes,
            band_slug=band_slug
        )
        alerts = build_web_push_operational_alerts(snapshot)
        problematic_deliveries = list_recent_problematic_deliveries(band_slug=band_slug, hours=hours, limit=limit)

        has_critical = any(a['severity'] == 'CRITICAL' for a in alerts)
        has_warning = any(a['severity'] == 'WARNING' for a in alerts)

        if has_critical:
            overall_state = 'CRITICAL'
        elif has_warning:
            overall_state = 'ATTENTION'
        elif snapshot['deliveries']['rates']['completed'] == 0:
            overall_state = 'NO_DATA'
        else:
            overall_state = 'HEALTHY'

        active_incidents = []
        recently_resolved = []

        from core.models import WebPushOperationalAlert
        scope_filter = {"scope_type": "BAND", "band__slug": band_slug} if band_slug else {"scope_type": "GLOBAL", "band__isnull": True}

        qs_active = WebPushOperationalAlert.objects.filter(status="ACTIVE", **scope_filter).order_by("-last_detected_at")[:100]
        active_incidents = [
            {
                "alert_id": alert.id,
                "scope_type": alert.scope_type,
                "band_slug": alert.band.slug if alert.band else None,
                "code": alert.code,
                "severity": alert.severity,
                "status": alert.status,
                "current_count": alert.current_count,
                "first_detected_at": alert.first_detected_at,
                "last_detected_at": alert.last_detected_at,
                "resolved_at": alert.resolved_at,
                "opened_count": alert.opened_count,
                "recommended_action": alert.recommended_action,
            }
            for alert in qs_active
        ]

        qs_resolved = WebPushOperationalAlert.objects.filter(status="RESOLVED", **scope_filter).order_by("-resolved_at")[:20]
        recently_resolved = [
            {
                "alert_id": alert.id,
                "scope_type": alert.scope_type,
                "band_slug": alert.band.slug if alert.band else None,
                "code": alert.code,
                "severity": alert.severity,
                "status": alert.status,
                "current_count": alert.current_count,
                "first_detected_at": alert.first_detected_at,
                "last_detected_at": alert.last_detected_at,
                "resolved_at": alert.resolved_at,
                "opened_count": alert.opened_count,
                "recommended_action": alert.recommended_action,
            }
            for alert in qs_resolved
        ]

        from core.services.web_push_alert_email import get_web_push_alert_email_config
        from core.models import WebPushOperationalAlertEmailDelivery

        try:
            email_config = get_web_push_alert_email_config()
            email_enabled = email_config['enabled']
            email_severity = email_config['min_severity']
            recipient_count = email_config['recipient_count']
        except ValueError:
            email_enabled = False
            email_severity = 'WARNING'
            recipient_count = 0

        qs_email = WebPushOperationalAlertEmailDelivery.objects.all().order_by('-created_at')

        email_recent_deliveries = []
        for d in qs_email[:20]:
            email_recent_deliveries.append({
                "event_type": d.event_type,
                "code_snapshot": d.code_snapshot,
                "severity_snapshot": d.severity_snapshot,
                "scope_type_snapshot": d.scope_type_snapshot,
                "band_slug_snapshot": d.band_slug_snapshot,
                "status": d.status,
                "attempt_count": d.attempt_count,
                "last_error_code": d.last_error_code,
                "created_at": d.created_at,
                "sent_at": d.sent_at
            })

        pending_count = WebPushOperationalAlertEmailDelivery.objects.filter(status='PENDING').count()
        temp_fail_count = WebPushOperationalAlertEmailDelivery.objects.filter(status='TEMPORARY_FAILURE').count()
        perm_fail_count = WebPushOperationalAlertEmailDelivery.objects.filter(status='PERMANENT_FAILURE').count()

        context['WEB_PUSH_ALERT_EMAIL_ENABLED'] = email_enabled
        context['WEB_PUSH_ALERT_EMAIL_MIN_SEVERITY'] = email_severity
        context['email_channel_recipient_count'] = recipient_count
        context['email_pending_count'] = pending_count
        context['email_temporary_failure_count'] = temp_fail_count
        context['email_permanent_failure_count'] = perm_fail_count
        context['email_recent_deliveries'] = email_recent_deliveries

        context['snapshot'] = snapshot
        context['alerts'] = alerts
        context['overall_state'] = overall_state
        context['problematic_deliveries'] = problematic_deliveries
        context['active_incidents'] = active_incidents
        context['recently_resolved'] = recently_resolved

        context['current_band_slug'] = band_slug
        context['current_hours'] = hours
        context['current_stale_pending'] = stale_pending_minutes
        context['current_stale_sending'] = stale_sending_minutes
        context['current_limit'] = limit
        from core.models import Band
        context['all_bands'] = Band.objects.all().order_by('name')

        return context

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response

# --- AVISOS ADMINISTRATIVOS ---
class AdminAvisosView(AdminRequiredMixin, ListView):
    model = AdministrativeBandNotice
    template_name = 'core/admin/avisos.html'
    context_object_name = 'avisos'
    
    def get_queryset(self):
        return AdministrativeBandNotice.objects.all().order_by('-created_at', '-pk')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['bandas'] = Band.objects.filter(is_active=True).order_by('name')
        return context

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_aviso_create(request):
    if request.method == 'POST':
        band_id = request.POST.get('band_id')
        message = request.POST.get('message', '').strip()
        
        if not message:
            messages.error(request, 'O aviso não pode ficar vazio.')
            return redirect('admin_painel:avisos')
            
        band = None
        if band_id and band_id != 'all':
            band = get_object_or_404(Band, pk=band_id)
            
        AdministrativeBandNotice.objects.create(
            band=band,
            message=message,
            created_by=request.user
        )
        messages.success(request, 'Aviso enviado com sucesso.')
    return redirect('admin_painel:avisos')

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_aviso_edit(request, pk):
    aviso = get_object_or_404(AdministrativeBandNotice, pk=pk)
    if request.method == 'POST':
        band_id = request.POST.get('band_id')
        message = request.POST.get('message', '').strip()
        
        if not message:
            messages.error(request, 'O aviso não pode ficar vazio.')
            return redirect('admin_painel:avisos')
            
        if band_id and band_id != 'all':
            aviso.band = get_object_or_404(Band, pk=band_id)
        else:
            aviso.band = None
            
        aviso.message = message
        aviso.save()
        messages.success(request, 'Aviso atualizado com sucesso.')
    return redirect('admin_painel:avisos')

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_aviso_delete(request, pk):
    if request.method == 'POST':
        aviso = get_object_or_404(AdministrativeBandNotice, pk=pk)
        aviso.delete()
        messages.success(request, 'Aviso excluído com sucesso.')
    return redirect('admin_painel:avisos')


# -----------------------------------------------------------------------------
# PARCEIROS GLOBAIS
# -----------------------------------------------------------------------------

class AdminPartnerListView(AdminRequiredMixin, ListView):
    model = Partner
    template_name = 'core/admin/partners_list.html'
    context_object_name = 'partners'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form'] = AdminPartnerForm()
        return context

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_partner_create(request):
    if request.method == 'POST':
        form = AdminPartnerForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Parceiro adicionado com sucesso!')
        else:
            messages.error(request, 'Erro ao adicionar parceiro. Verifique os dados e tente novamente.')
    return redirect('admin_painel:parceiros')

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_partner_edit(request, pk):
    partner = get_object_or_404(Partner, pk=pk)
    if request.method == 'POST':
        form = AdminPartnerForm(request.POST, request.FILES, instance=partner)
        if form.is_valid():
            form.save()
            messages.success(request, 'Parceiro atualizado com sucesso!')
        else:
            messages.error(request, 'Erro ao atualizar parceiro.')
    return redirect('admin_painel:parceiros')

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_partner_toggle_active(request, pk):
    if request.method == 'POST':
        partner = get_object_or_404(Partner, pk=pk)
        partner.is_active = not partner.is_active
        partner.save()
        messages.success(request, f'Parceiro {'ativado' if partner.is_active else 'desativado'} com sucesso.')
    return redirect('admin_painel:parceiros')

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_partner_delete(request, pk):
    if request.method == 'POST':
        partner = get_object_or_404(Partner, pk=pk)
        partner.delete()
        messages.success(request, 'Parceiro excluído com sucesso.')
    return redirect('admin_painel:parceiros')
from django.views.generic import DeleteView
from core.models import LandingPageBandLogo, SystemSettings
from core.admin_forms import LandingPageBandLogoForm, SystemPlanPricingForm

class SiteLogosView(AdminRequiredMixin, ListView):
    model = LandingPageBandLogo
    template_name = 'core/admin/site_logos.html'
    context_object_name = 'logos'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'form' not in context:
            context['form'] = LandingPageBandLogoForm()
        if 'form_plans' not in context:
            settings_obj = SystemSettings.get_settings()
            context['form_plans'] = SystemPlanPricingForm(instance=settings_obj)
        return context
        
    def post(self, request, *args, **kwargs):
        form = LandingPageBandLogoForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, 'Logo cadastrada com sucesso!')
            return redirect('admin_painel:site_logos')
        
        self.object_list = self.get_queryset()
        context = self.get_context_data()
        context['form'] = form
        context['open_modal'] = True
        return self.render_to_response(context)

class SitePlansPriceUpdateView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        settings_obj = SystemSettings.get_settings()
        form = SystemPlanPricingForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, 'Valores dos planos atualizados com sucesso!')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{form.fields.get(field, field).label if field in form.fields else field}: {error}")
        return redirect('admin_painel:site_logos')

import json
from django.http import JsonResponse

class SiteLogoReorderView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        try:
            data = json.loads(request.body)
            order = data.get('order', [])
            
            for index, logo_id in enumerate(order):
                LandingPageBandLogo.objects.filter(pk=logo_id).update(display_order=index)
                
            return JsonResponse({'status': 'success'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)

class SiteLogoEditView(AdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        logo = get_object_or_404(LandingPageBandLogo, pk=pk)
        form = LandingPageBandLogoForm(request.POST, request.FILES, instance=logo)
        if form.is_valid():
            form.save()
            messages.success(request, 'Logo atualizada com sucesso!')
        else:
            # Em caso de erro de validação, os erros deveriam ser devolvidos,
            # mas simplificamos devolvendo erro genérico e mandando tentar de novo.
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{form.fields[field].label}: {error}")
        return redirect('admin_painel:site_logos')

class SiteLogoDeleteView(AdminRequiredMixin, DeleteView):
    model = LandingPageBandLogo
    success_url = reverse_lazy('admin_painel:site_logos')
    
    def get(self, request, *args, **kwargs):
        return redirect('admin_painel:site_logos')

    def delete(self, request, *args, **kwargs):
        messages.success(request, 'Logo excluída com sucesso!')
        return super().delete(request, *args, **kwargs)

class SiteLogoToggleActiveView(AdminRequiredMixin, View):
    def post(self, request, pk, *args, **kwargs):
        logo = get_object_or_404(LandingPageBandLogo, pk=pk)
        logo.is_active = not logo.is_active
        logo.save()
        status_text = 'ativada' if logo.is_active else 'desativada'
        messages.success(request, f'Logo {status_text} com sucesso!')
        return redirect('admin_painel:site_logos')


@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_assinatura_status(request, pk):
    if request.method == 'POST':
        sub = get_object_or_404(BandSubscription, pk=pk)
        sub.status = 'DESATIVADO' if sub.status == 'ATIVO' else 'ATIVO'
        sub.save()
        messages.success(request, f'Status da assinatura alterado com sucesso!')
    return redirect('admin_painel:assinaturas')
