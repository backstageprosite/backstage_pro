from django.shortcuts import render, redirect, get_object_or_404
from django.core.management import call_command
from django.contrib.auth import logout
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, ListView, View
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
        context['bandas_sem_assinatura'] = Band.objects.filter(subscriptions__isnull=True)
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
                
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['form_create'] = AdminUserCreateForm()
        context['bandas_list'] = Band.objects.all().order_by('name')
        context['q'] = self.request.GET.get('q', '')
        context['selected_band'] = self.request.GET.get('band', '')
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
        qs = super().get_queryset().filter(is_deleted=False)
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
        context['seven_days'] = datetime.date.today() + datetime.timedelta(days=7)
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
        billings = BillingRecord.objects.filter(subscription__is_deleted=False)
        subs = BandSubscription.objects.all()
        from .models import Expense
        expenses = Expense.objects.all()

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

        # Receitas recebidas (Cobranças pagas pela data de pagamento)
        recebido = billings.filter(
            status='PAGO',
            paid_date__gte=start_date,
            paid_date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Despesas pagas
        despesa_paga = expenses.filter(
            status='PAGO',
            paid_date__gte=start_date,
            paid_date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or 0

        # Saldo realizado
        saldo_realizado = recebido - despesa_paga

        # Valores a receber (Cobranças pendentes ou vencidas no período baseado em due_date)
        a_receber = billings.filter(
            Q(status='PENDENTE', due_date__lt=timezone.localdate()) | Q(status='PENDENTE', due_date__gte=start_date, due_date__lte=end_date),
            due_date__gte=start_date,
            due_date__lte=end_date
        ).aggregate(total=Sum('amount'))['total'] or 0

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
        ).aggregate(total=Sum('amount'))['total'] or 0

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
        all_bands = Band.objects.filter(subscriptions__is_deleted=False).distinct()
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
                'subscription': band.subscriptions.filter(status='ATIVO', is_deleted=False).first(),
                'recebido': rec,
                'pendente': pend,
                'futuro': fut,
                'atrasado': atr
            })


        # Compute KPIs for the template
        kpi_recebido = recebido
        kpi_pendente = billings.filter(status='PENDENTE', due_date__gte=today, due_date__lte=end_date).aggregate(total=Sum('amount'))['total'] or 0
        kpi_futuro = billings.filter(status='PENDENTE', due_date__gt=end_date).aggregate(total=Sum('amount'))['total'] or 0
        kpi_atrasado = cobrancas_vencidas

        # Context Update
        context.update({
            'kpi_recebido': kpi_recebido,
            'kpi_pendente': kpi_pendente,
            'kpi_futuro': kpi_futuro,
            'kpi_atrasado': kpi_atrasado,
            'kpi_receita_prevista': despesa_paga, # using this for Despesas
            'kpi_total_bandas': saldo_realizado, # using this for Valor em Caixa

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
            'expenses': expenses.order_by('-due_date'),
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
def admin_user_create(request):
    if request.method == 'POST':
        form = AdminUserCreateForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Usuário cadastrado com sucesso!")
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
            messages.success(request, "Usuário atualizado com sucesso!")
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
            
            # Sincroniza faturas pendentes com a nova data da assinatura
            if sub.next_due_date:
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
from core.models import LandingPageBandLogo
from core.admin_forms import LandingPageBandLogoForm

class SiteLogosView(AdminRequiredMixin, ListView):
    model = LandingPageBandLogo
    template_name = 'core/admin/site_logos.html'
    context_object_name = 'logos'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if 'form' not in context:
            context['form'] = LandingPageBandLogoForm()
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
