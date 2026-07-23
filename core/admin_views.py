from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, ListView
from django.db.models import Count
from core.models import Band, User, Show, BandSubscription, BillingRecord, AdministrativeBandNotice, Partner, SupportTicket, SystemSettings
from .admin_forms import AdminBandForm, AdminUserCreateForm, AdminUserEditForm, AdminSubscriptionForm, AdminBillingRecordForm, AdminPartnerForm
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
        from django.db.models import Sum
        today = datetime.date.today()
        seven_days_from_now = today + datetime.timedelta(days=7)

        context['total_bandas'] = Band.objects.count()
        context['bandas_ativas'] = Band.objects.filter(is_active=True).count()
        context['total_usuarios'] = User.objects.count()

        # Financeiro SaaS
        context['assinaturas_ativas'] = BandSubscription.objects.filter(status='ATIVO').count()

        receita_prevista = BandSubscription.objects.filter(status='ATIVO').aggregate(total=Sum('contracted_value'))['total'] or 0
        context['receita_prevista'] = receita_prevista

        receita_recebida = BillingRecord.objects.filter(status='PAGO', paid_date__month=today.month, paid_date__year=today.year).aggregate(total=Sum('amount'))['total'] or 0
        context['receita_recebida'] = receita_recebida

        context['cobrancas_pendentes'] = BillingRecord.objects.filter(status='PENDENTE').count()
        context['cobrancas_atrasadas'] = BillingRecord.objects.filter(status='ATRASADO').count()

        # Alertas Vencimentos
        context['bandas_vencidas'] = BandSubscription.objects.filter(status='VENCIDO')
        context['bandas_vencendo_7d'] = BandSubscription.objects.filter(next_due_date__gt=today, next_due_date__lte=seven_days_from_now)
        context['bandas_sem_assinatura'] = Band.objects.filter(subscription__isnull=True)
        context['faturas_atrasadas'] = BillingRecord.objects.filter(status='ATRASADO')

        if context['bandas_vencidas'].exists():
            context['show_alert_modal'] = True
        else:
            context['show_alert_modal'] = False

        context['total_shows'] = Show.objects.count()

        # Shows no mes atual
        context['shows_mes_atual'] = Show.objects.filter(date__year=today.year, date__month=today.month).count()

        # Shows futuros
        context['shows_futuros'] = Show.objects.filter(date__gte=today).count()

        # Fale Conosco (Mensagens não lidas pelo administrador)
        unread_tickets = SupportTicket.objects.filter(
            status__in=['NEW', 'WAITING_ADMIN']
        ).order_by('-last_message_at')
        
        unread_tickets_list = []
        for t in unread_tickets:
            if not t.admin_last_read_at or t.last_message_at > t.admin_last_read_at:
                unread_tickets_list.append(t)
                
        context['support_unread_count'] = len(unread_tickets_list)
        context['support_unread_tickets'] = unread_tickets_list[:5] # mostrar até 5 no dashboard

        # Bandas com assinatura vencida (se date for menor que hoje)
        context['assinaturas_vencidas'] = Band.objects.filter(subscription_due_date__lt=today).count()

        # Bandas vencendo nos proximos 7 dias
        next_week = today + datetime.timedelta(days=7)
        context['assinaturas_vencendo'] = Band.objects.filter(subscription_due_date__gte=today, subscription_due_date__lte=next_week).count()

        return context

class AdminBandListView(AdminRequiredMixin, ListView):
    model = Band
    template_name = 'core/admin/bandas.html'
    context_object_name = 'bandas'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_create'] = AdminBandForm()
        return context

class AdminUserListView(AdminRequiredMixin, ListView):
    model = User
    template_name = 'core/admin/usuarios.html'
    context_object_name = 'usuarios'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_create'] = AdminUserCreateForm()
        return context

class AdminShowListView(AdminRequiredMixin, ListView):
    model = Show
    template_name = 'core/admin/shows.html'
    context_object_name = 'shows'
    ordering = ['-date']

class AdminAssinaturasView(AdminRequiredMixin, ListView):
    model = BandSubscription
    template_name = 'core/admin/assinaturas.html'
    context_object_name = 'assinaturas'

    def get_queryset(self):
        qs = super().get_queryset()
        q = self.request.GET.get('q', '')
        status = self.request.GET.get('status', '')
        cycle = self.request.GET.get('cycle', '')

        if q:
            qs = qs.filter(band__name__icontains=q) | qs.filter(financial_responsible_name__icontains=q)
        if status:
            if status == 'VENCENDO_7D':
                today = datetime.date.today()
                qs = qs.filter(next_due_date__gt=today, next_due_date__lte=today + datetime.timedelta(days=7))
            else:
                qs = qs.filter(status=status)
        if cycle:
            qs = qs.filter(billing_cycle=cycle)

        return qs.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_create'] = AdminSubscriptionForm()
        context['today'] = datetime.date.today()
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
        from django.db.models import Sum, Q

        today = datetime.date.today()

        # Filtros
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        band_id = self.request.GET.get('band')
        status = self.request.GET.get('status')
        plan = self.request.GET.get('plan')
        cycle = self.request.GET.get('cycle')
        period = self.request.GET.get('period')

        if not start_date or not end_date:
            if period == 'this_month':
                start_date = today.replace(day=1)
                end_date = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
            elif period == 'last_month':
                last_day_of_prev_month = today.replace(day=1) - datetime.timedelta(days=1)
                start_date = last_day_of_prev_month.replace(day=1)
                end_date = last_day_of_prev_month
            elif period == 'next_30':
                start_date = today
                end_date = today + datetime.timedelta(days=30)
            elif period == 'this_year':
                start_date = today.replace(month=1, day=1)
                end_date = today.replace(month=12, day=31)
            else:
                # Default: this month
                start_date = today.replace(day=1)
                end_date = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
        else:
            try:
                start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d').date()
            except ValueError:
                start_date = today.replace(day=1)
                end_date = (today.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)

        # Base Querysets
        billings = BillingRecord.objects.all()
        subs = BandSubscription.objects.all()

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

        # 1. Valores Recebidos (PAGO no perÃ­odo baseado em paid_date)
        recebido = billings.filter(
            status='PAGO',
            paid_date__gte=start_date,
            paid_date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or 0

        # 2. Valores Pendentes (PENDENTE no perÃ­odo baseado em due_date, >= hoje)
        pendente = billings.filter(
            status='PENDENTE',
            due_date__gte=max(today, start_date),
            due_date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or 0

        # 3. Valores Futuros (PENDENTE com due_date > hoje)
        # Vamos pegar todo o valor futuro, ou limitar ao perÃ­odo se aplicÃ¡vel.
        # A regra diz: "soma de cobranÃ§as futuras ainda não pagas, com due_date maior que hoje. Pode incluir BillingRecord com status PENDENTE e vencimento futuro."
        futuro = billings.filter(
            status='PENDENTE',
            due_date__gt=today
        ).aggregate(total=Sum('amount'))['total'] or 0

        # 4. Valores Atrasados (ATRASADO ou PENDENTE < hoje)
        atrasado = billings.filter(
            Q(status='ATRASADO') | Q(status='PENDENTE', due_date__lt=today)
        ).aggregate(total=Sum('amount'))['total'] or 0

        # 5. Receita Prevista Mensal (Valor Contratado das assinaturas ATIVAS)
        receita_prevista_mensal = BandSubscription.objects.filter(status='ATIVO').aggregate(total=Sum('contracted_value'))['total'] or 0

        # 6. Total de Bandas Ativas Pagantes
        total_bandas_ativas = BandSubscription.objects.filter(status='ATIVO').count()

        # GrÃ¡ficos Data

        # GrÃ¡fico 1: Recebido x Pendente x Futuro x Atrasado
        chart_bars = {
            'labels': ['Recebido', 'Pendente', 'Futuro', 'Atrasado'],
            'data': [float(recebido), float(pendente), float(futuro), float(atrasado)]
        }

        # GrÃ¡fico 2: Pizza de Status
        status_counts = billings.values('status').annotate(total=Count('id'))
        status_labels = []
        status_data = []
        for s in status_counts:
            status_labels.append(s['status'])
            status_data.append(s['total'])

        chart_pie = {
            'labels': status_labels,
            'data': status_data
        }

        # GrÃ¡fico 3: Receita por Ciclo
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

        # GrÃ¡fico 4: Top Bandas
        top_bandas = billings.filter(status='PAGO', paid_date__gte=start_date, paid_date__lte=end_date).values('band__name').annotate(total=Sum('amount')).order_by('-total')[:5]
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
        all_bands = Band.objects.filter(subscription__isnull=False)
        if band_id:
            all_bands = all_bands.filter(id=band_id)

        for band in all_bands:
            band_billings = billings.filter(band=band)
            rec = band_billings.filter(status='PAGO', paid_date__gte=start_date, paid_date__lte=end_date).aggregate(total=Sum('amount'))['total'] or 0
            pend = band_billings.filter(status='PENDENTE', due_date__gte=today, due_date__lte=end_date).aggregate(total=Sum('amount'))['total'] or 0
            fut = band_billings.filter(status='PENDENTE', due_date__gt=today).aggregate(total=Sum('amount'))['total'] or 0
            atr = band_billings.filter(Q(status='ATRASADO') | Q(status='PENDENTE', due_date__lt=today)).aggregate(total=Sum('amount'))['total'] or 0

            band_summaries.append({
                'band': band,
                'subscription': band.subscription,
                'recebido': rec,
                'pendente': pend,
                'futuro': fut,
                'atrasado': atr
            })

        # Context Update
        context.update({
            'start_date': start_date.strftime('%Y-%m-%d') if isinstance(start_date, datetime.date) else start_date,
            'end_date': end_date.strftime('%Y-%m-%d') if isinstance(end_date, datetime.date) else end_date,
            'band_id': band_id,
            'status': status,
            'plan': plan,
            'cycle': cycle,
            'period': period,

            'kpi_recebido': recebido,
            'kpi_pendente': pendente,
            'kpi_futuro': futuro,
            'kpi_atrasado': atrasado,
            'kpi_receita_prevista': receita_prevista_mensal,
            'kpi_total_bandas': total_bandas_ativas,

            'chart_bars': json.dumps(chart_bars),
            'chart_pie': json.dumps(chart_pie),
            'chart_cycle': json.dumps(chart_cycle),
            'chart_top_bandas': json.dumps(chart_top_bandas),

            'band_summaries': band_summaries,
            'billings': billings.order_by('-due_date')[:100], # limit to 100 to avoid huge tables initially
            'all_bands': Band.objects.filter(subscription__isnull=False).order_by('name'),
        })

        return context

class AdminConfiguracoesView(AdminRequiredMixin, TemplateView):
    template_name = 'core/admin/configuracoes.html'

    def post(self, request, *args, **kwargs):
        settings = SystemSettings.get_settings()
        
        if 'logo' in request.FILES:
            settings.logo = request.FILES['logo']
            settings.save()
            messages.success(request, "Identidade visual atualizada com sucesso.")
            
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
def admin_user_create(request):
    if request.method == 'POST':
        form = AdminUserCreateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "UsuÃ¡rio cadastrado com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:usuarios')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_user_edit(request, pk):
    user = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = AdminUserEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, "UsuÃ¡rio atualizado com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:usuarios')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_user_toggle_active(request, pk):
    if request.method == 'POST':
        user = get_object_or_404(User, pk=pk)
        user.is_active = not user.is_active
        user.save()
        status = "ativado" if user.is_active else "desativado"
        messages.success(request, f"UsuÃ¡rio {status} com sucesso!")
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
            messages.success(request, f"Senha do usuÃ¡rio {user.username} redefinida com sucesso!")

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
    sub = get_object_or_404(BandSubscription, pk=pk)
    if request.method == 'POST':
        form = AdminSubscriptionForm(request.POST, instance=sub)
        if form.is_valid():
            form.save()
            messages.success(request, "Assinatura atualizada com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
    return redirect('admin_painel:assinaturas')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_assinatura_cancel(request, pk):
    if request.method == 'POST':
        sub = get_object_or_404(BandSubscription, pk=pk)
        sub.status = 'CANCELADO'
        sub.save()
        messages.success(request, "Assinatura cancelada com sucesso!")
    return redirect('admin_painel:assinaturas')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
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

            messages.success(request, "CobranÃ§a gerada com sucesso!")
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

            messages.success(request, "CobranÃ§a atualizada com sucesso!")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"Erro ({field}): {error}")
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
