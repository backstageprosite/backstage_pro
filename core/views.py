from django.views.decorators.http import require_POST
import datetime
from django.shortcuts import render, get_object_or_404, redirect
from django.db import transaction
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from functools import wraps
from django.http import HttpResponseForbidden
from django.db.models import Sum
from .models import Show, FinancialReceipt, Band, User, Contact, ContractDocument, ShowPayment, ShowTeamCost, BandDashboardPendingItem
from .forms import FinancialReceiptForm, UserForm, UserEditForm, ContactForm, ShowForm, ContractDocumentFormSet, FinancialReceiptFormSet, ShowPaymentForm, ShowTeamCostForm, ContractDocumentForm
from decimal import Decimal

def landing_page_view(request):
    """
    Landing page principal de vendas do Backstage Pro.
    """
    return render(request, 'core/landing.html')

def termos_de_uso_view(request):
    """
    Página de Termos de Uso.
    """
    return render(request, 'core/termos_de_uso.html')

def politica_de_privacidade_view(request):
    """
    Página de Política de Privacidade.
    """
    return render(request, 'core/politica_de_privacidade.html')

def band_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, band_slug, *args, **kwargs):
        band = get_object_or_404(Band, slug=band_slug)
        if not request.user.is_authenticated:
            return redirect('login', band_slug=band_slug)
        if request.user.band != band and not request.user.is_superuser:
            raise PermissionDenied("Você não pertence a esta banda.")

        if not band.is_active and not request.user.is_superuser:
            raise PermissionDenied("O acesso desta banda ao Backstage Pro está temporariamente suspenso. Entre em contato com a administração.")

        request.band = band
        return view_func(request, band_slug, *args, **kwargs)
    return _wrapped_view


def band_root_redirect_view(request, band_slug):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('admin_painel:dashboard')
        if request.user.band and request.user.band.slug != band_slug:
            return redirect('dashboard', band_slug=request.user.band.slug)
    return redirect('dashboard', band_slug=band_slug)

class BandLoginView(LoginView):
    template_name = 'core/login.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        band_slug = self.kwargs.get('band_slug')
        band = get_object_or_404(Band, slug=band_slug)
        context['band'] = band
        return context

    def get_success_url(self):
        user = self.request.user
        if user.is_superuser:
            return reverse('admin_painel:dashboard')
        if user.band:
            return reverse('dashboard', kwargs={'band_slug': user.band.slug})
        return reverse('dashboard', kwargs={'band_slug': self.kwargs.get('band_slug')})

    def form_valid(self, form):
        user = form.get_user()
        band_slug = self.kwargs.get('band_slug')
        band = get_object_or_404(Band, slug=band_slug)

        if not band.is_active and not user.is_superuser:
            messages.error(self.request, "O acesso desta banda está suspenso. Procure a administração.")
            return self.form_invalid(form)

        if user.band != band and not user.is_superuser:
            messages.error(self.request, "Usuário não pertence a esta banda.")
            return self.form_invalid(form)
        return super().form_valid(form)

def band_logout(request, band_slug):
    logout(request)
    return redirect('login', band_slug=band_slug)

@login_required
@band_required
def dashboard_view(request, band_slug):
    band = get_object_or_404(Band, slug=band_slug)
    shows_proximos = Show.objects.filter(band=band, date__gte=datetime.date.today()).order_by('date', 'show_time')[:5]
    total_shows = Show.objects.filter(band=band).count()
    total_users = User.objects.filter(band=band).count()
    total_contacts = Contact.objects.filter(band=band).count()

    dashboard_pending_items = BandDashboardPendingItem.objects.filter(band=band).select_related('show', 'created_by')

    # Shows for the select in the Add modal (only for producer)
    shows = None
    if request.user.is_superuser or getattr(request.user, 'role', '') == 'PRODUTOR':
        shows = Show.objects.filter(band=band, date__gte=datetime.date.today()).order_by('date', 'show_time')

    context = {
        'band': band,
        'shows_proximos': shows_proximos,
        'total_shows': total_shows,
        'total_users': total_users,
        'total_contacts': total_contacts,
        'dashboard_pending_items': dashboard_pending_items,
        'shows': shows,
    }
    return render(request, 'core/dashboard.html', context)

@band_required
def calendario(request, band_slug):
    """
    Tela principal que exibirá o calendário e a lista de shows da banda.
    """
    shows = Show.objects.filter(band=request.band).order_by('date')
    context = {
        'shows': shows,
        'band': request.band
    }
    return render(request, 'core/calendario.html', context)

@band_required
def show_detail(request, band_slug, pk):
    """
    Detalhes de um show específico.
    """
    show = get_object_or_404(Show, pk=pk, band=request.band)

    # Processamento do formulário de comprovante (só para produtor)
    form = None
    total_custos = 0
    resultado_previsto = 0
    margem_prevista = 0

    if request.user.is_produtor():
        from django.db.models import Sum

        total_custos_logistica = show.receipts.aggregate(total=Sum('value'))['total'] or Decimal('0')
        total_custos_equipe = show.team_costs.aggregate(total=Sum('value'))['total'] or Decimal('0')
        total_custos = total_custos_logistica + total_custos_equipe

        receita = show.fee or Decimal('0')
        resultado_previsto = receita - total_custos
        if receita > 0:
            margem_prevista = (resultado_previsto / receita) * Decimal('100')

        total_recebido = sum((p.value for p in show.payments.all() if p.status == 'RECEBIDO'), Decimal('0'))
        total_pendente = receita - total_recebido
        percentual_recebido = (total_recebido / receita) * Decimal('100') if receita > 0 else Decimal('0')
        caixa_realizado = total_recebido - total_custos

    context = {
        'show': show,
        'form': form,
        'band': request.band,
        'total_custos': total_custos,
        'resultado_previsto': resultado_previsto,
        'margem_prevista': margem_prevista,
        'total_recebido': total_recebido if request.user.is_produtor() else 0,
        'total_pendente': total_pendente if request.user.is_produtor() else 0,
        'percentual_recebido': percentual_recebido if request.user.is_produtor() else 0,
        'caixa_realizado': caixa_realizado if request.user.is_produtor() else 0,
    }
    return render(request, 'core/show_detail.html', context)

@band_required
@login_required
def show_finance_detail_view(request, band_slug, pk):
    """
    Detalhes exclusivamente financeiros de um show especfico.
    """
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores tm acesso ao financeiro do show.")

    show = get_object_or_404(Show, pk=pk, band=request.band)

    receipt_form = FinancialReceiptForm()
    team_cost_form = ShowTeamCostForm()
    payment_form = ShowPaymentForm()

    if request.method == 'POST':
        if 'update_fee' in request.POST:
            fee_str = request.POST.get('fee', '')
            try:
                # Se a string já contém um ponto e não contém vírgula, e tem duas casas decimais, o JS já pode ter formatado
                # Limpeza robusta:
                fee_str = fee_str.replace('R$', '').strip()
                if ',' in fee_str and '.' in fee_str:
                    # Tem os dois, ex: 140.000,00 -> 140000.00
                    fee_str = fee_str.replace('.', '').replace(',', '.')
                elif ',' in fee_str:
                    # Só tem vírgula, ex: 140000,00 -> 140000.00
                    fee_str = fee_str.replace(',', '.')
                # Se só tem ponto, ex: 140000.00, já está no formato correto para Decimal.
                # Se tiver múltiplos pontos (ex: 140.000 sem vírgula)
                elif fee_str.count('.') > 1:
                    fee_str = fee_str.replace('.', '')

                fee_val = Decimal(fee_str)
                show.fee = fee_val
                show.save()
                messages.success(request, 'Cachê atualizado com sucesso!')
            except Exception as e:
                messages.error(request, f'Valor de cachê inválido: {str(e)}')
            return redirect('show_finance_detail', band_slug=band_slug, pk=show.id)

        if 'submit_receipt' in request.POST:
            receipt_form = FinancialReceiptForm(request.POST, request.FILES)
            if receipt_form.is_valid():
                receipt = receipt_form.save(commit=False)
                receipt.show = show
                receipt.save()
                messages.success(request, 'Comprovante adicionado com sucesso!')
                return redirect('show_finance_detail', band_slug=band_slug, pk=show.id)
        elif 'submit_payment' in request.POST:
            payment_form = ShowPaymentForm(request.POST, request.FILES)
            if payment_form.is_valid():
                payment = payment_form.save(commit=False)
                payment.show = show
                payment.save()
                messages.success(request, 'Receita adicionada com sucesso!')
                return redirect('show_finance_detail', band_slug=band_slug, pk=show.id)
        elif 'submit_team_cost' in request.POST:
            team_cost_form = ShowTeamCostForm(request.POST)
            if team_cost_form.is_valid():
                team_cost = team_cost_form.save(commit=False)
                team_cost.show = show
                team_cost.created_by = request.user
                team_cost.save()
                messages.success(request, "Custo com equipe adicionado com sucesso!")
                return redirect('show_finance_detail', band_slug=band_slug, pk=show.id)

    from django.db.models import Sum

    total_custos_logistica = show.receipts.aggregate(total=Sum('value'))['total'] or Decimal('0')
    total_custos_equipe = show.team_costs.aggregate(total=Sum('value'))['total'] or Decimal('0')
    total_custos = total_custos_logistica + total_custos_equipe

    receita = show.fee or Decimal('0')
    resultado_previsto = receita - total_custos
    margem_prevista = Decimal('0')
    if receita > 0:
        margem_prevista = (resultado_previsto / receita) * Decimal('100')

    total_recebido = sum((p.value for p in show.payments.all() if p.status == 'RECEBIDO'), Decimal('0'))
    total_pendente = receita - total_recebido
    percentual_recebido = (total_recebido / receita) * Decimal('100') if receita > 0 else Decimal('0')
    caixa_realizado = total_recebido - total_custos

    context = {
        'show': show,
        'form': receipt_form,
        'team_cost_form': team_cost_form,
        'band': request.band,
        'total_custos': total_custos,
        'resultado_previsto': resultado_previsto,
        'margem_prevista': margem_prevista,
        'total_recebido': total_recebido,
        'total_pendente': total_pendente,
        'percentual_recebido': percentual_recebido,
        'caixa_realizado': caixa_realizado,
        'receipt_form': receipt_form,
        'payment_form': payment_form,
        'team_cost_form': team_cost_form,
    }
    return render(request, 'core/show_finance_detail.html', context)

@band_required
def show_pdf_view(request, band_slug, pk):
    """
    View específica para o formato de impressão (PDF) para a banda.
    Somente usuários com perfil de produtor (ou staff) devem acessar, mas
    como o botão está no admin, basta verificar se é produtor.
    """
    if not request.user.is_produtor():
        messages.error(request, 'Você não tem permissão para exportar PDFs.')
        return redirect('calendario', band_slug=band_slug)

    show = get_object_or_404(Show, pk=pk, band=request.band)

    return render(request, 'core/show_pdf.html', {
        'show': show
    })

@band_required
def agenda_pdf_view(request, band_slug):
    """
    View específica para o formato de impressão (PDF) de toda a agenda.
    Somente produtores/staff.
    """
    if not request.user.is_produtor():
        messages.error(request, 'Você não tem permissão para exportar agendas.')
        return redirect('calendario', band_slug=band_slug)

    shows = Show.objects.filter(band=request.band).order_by('date')

    import datetime

    data_inicio = request.GET.get('data_inicio')
    data_fim = request.GET.get('data_fim')

    if data_inicio:
        try:
            inicio = datetime.datetime.strptime(data_inicio, '%Y-%m-%d').date()
            shows = shows.filter(date__gte=inicio)
        except ValueError:
            pass

    if data_fim:
        try:
            fim = datetime.datetime.strptime(data_fim, '%Y-%m-%d').date()
            shows = shows.filter(date__lte=fim)
        except ValueError:
            pass

    selected_statuses = request.GET.getlist('status')
    if selected_statuses:
        from django.db.models import Q
        import datetime

        today = datetime.date.today()
        query = Q()

        if 'CONFIRMADO' in selected_statuses:
            query |= Q(status='CONFIRMADO', date__gte=today)
        if 'CONCLUIDO' in selected_statuses:
            query |= Q(status='CONFIRMADO', date__lt=today)
        if 'PRE_RESERVADO' in selected_statuses:
            query |= Q(status='PRE_RESERVADO')
        if 'CANCELADO' in selected_statuses:
            query |= Q(status='CANCELADO')

        if query:
            shows = shows.filter(query)
        else:
            shows = shows.none()

    return render(request, 'core/agenda_pdf.html', {
        'shows': shows,
        'band': request.band,
        'today': datetime.date.today(),
    })

class CustomPasswordResetView(auth_views.PasswordResetView):
    template_name = 'core/password_reset.html'
    email_template_name = 'core/password_reset_email.html'
    subject_template_name = 'core/password_reset_subject.txt'
    success_url = '/esqueci-minha-senha/enviado/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        band_slug = self.request.GET.get('band')
        if band_slug:
            context['band'] = Band.objects.filter(slug=band_slug).first()
        return context

    def form_valid(self, form):
        band_slug = self.request.GET.get('band')
        if band_slug:
            self.extra_email_context = {'band_slug': band_slug}
        return super().form_valid(form)

    def get_success_url(self):
        url = super().get_success_url()
        band_slug = self.request.GET.get('band')
        if band_slug:
            return f"{url}?band={band_slug}"
        return url

class CustomPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'core/password_reset_done.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        band_slug = self.request.GET.get('band')
        if band_slug:
            context['band'] = Band.objects.filter(slug=band_slug).first()
        return context

class CustomPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'core/password_reset_confirm.html'
    success_url = '/redefinir-senha/concluido/'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        band_slug = self.request.GET.get('band')
        if band_slug:
            context['band'] = Band.objects.filter(slug=band_slug).first()
        return context

    def get_success_url(self):
        url = super().get_success_url()
        band_slug = self.request.GET.get('band')
        if band_slug:
            return f"{url}?band={band_slug}"
        return url

class CustomPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'core/password_reset_complete.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        band_slug = self.request.GET.get('band')
        if band_slug:
            context['band'] = Band.objects.filter(slug=band_slug).first()
        return context

@login_required
@band_required
def relatorios_index_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores têm acesso aos relatórios.")

    band = get_object_or_404(Band, slug=band_slug)

    subscription = None
    if hasattr(band, 'subscription'):
        subscription = band.subscription

    context = {'band': band, 'subscription': subscription}
    return render(request, 'core/relatorios_index.html', context)

@login_required
@band_required
def minha_assinatura_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores têm acesso aos relatórios.")

    band = get_object_or_404(Band, slug=band_slug)

    if not hasattr(band, 'subscription'):
        return redirect('relatorios_index', band_slug=band.slug)

    subscription = band.subscription
    faturas = subscription.records.all().order_by('-due_date')

    context = {
        'band': band,
        'subscription': subscription,
        'faturas': faturas
    }
    return render(request, 'core/minha_assinatura.html', context)

@login_required
@band_required
def relatorios_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores têm acesso aos relatórios.")

    band = get_object_or_404(Band, slug=band_slug)
    shows = Show.objects.filter(band=band).prefetch_related('payments', 'team_costs').annotate(total_receipts=Sum('receipts__value')).order_by('date')

    # Filtros
    date_start = request.GET.get('date_start')
    date_end = request.GET.get('date_end')
    contract_type = request.GET.get('contract_type')
    payment_status = request.GET.get('payment_status')

    if date_start:
        shows = shows.filter(date__gte=date_start)
    if date_end:
        shows = shows.filter(date__lte=date_end)
    if contract_type:
        shows = shows.filter(contract_type__icontains=contract_type)
    if payment_status:
        shows = shows.filter(payment_status=payment_status)

    total_receita = Decimal('0')
    total_custos = Decimal('0')
    total_recebido_geral = Decimal('0')

    # Processar cada show para a tabela
    for show in shows:
        show_receita = show.fee or Decimal('0')
        show_custos_logistica = show.total_receipts or Decimal('0')
        show_custos_equipe = sum((t.value for t in show.team_costs.all()), Decimal('0'))
        show_custos = show_custos_logistica + show_custos_equipe

        show_recebido = sum((p.value for p in show.payments.all() if p.status == 'RECEBIDO'), Decimal('0'))

        show.total_equipe = show_custos_equipe
        show.total_logistica = show_custos_logistica
        show.total_costs = show_custos
        show.resultado_previsto = show_receita - show_custos
        show.total_recebido = show_recebido
        show.total_pendente = show_receita - show_recebido
        show.caixa_realizado = show_recebido - show_custos

        if show_receita > 0:
            show.margem_prevista = (show.resultado_previsto / show_receita) * Decimal('100')
        else:
            show.margem_prevista = Decimal('0')

        total_receita += show_receita
        total_custos += show_custos
        total_recebido_geral += show_recebido

    resultado_previsto_total = total_receita - total_custos
    caixa_realizado_geral = total_recebido_geral - total_custos
    total_pendente_geral = total_receita - total_recebido_geral

    margem_prevista_geral = 0
    if total_receita > 0:
        margem_prevista_geral = (resultado_previsto_total / total_receita) * Decimal('100')

    context = {
        'band': band,
        'shows': shows,
        'qtd_shows': shows.count(),
        'total_receita': total_receita,
        'total_custos': total_custos,
        'total_recebido_geral': total_recebido_geral,
        'total_pendente_geral': total_pendente_geral,
        'caixa_realizado_geral': caixa_realizado_geral,
        'resultado_previsto_total': resultado_previsto_total,
        'margem_prevista_geral': margem_prevista_geral,
        'qtd_shows': shows.count(),
    }
    return render(request, 'core/relatorios.html', context)


@login_required
@band_required
def arquivos_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores têm acesso aos arquivos.")

    band = get_object_or_404(Band, slug=band_slug)

    shows_with_files = Show.objects.filter(band=band).prefetch_related('documents', 'receipts')
    shows_list = [show for show in shows_with_files if show.documents.exists() or show.receipts.exists()]

    context = {
        'band': band,
        'shows': shows_list,
    }
    return render(request, 'core/arquivos.html', context)

@login_required
@band_required
def configuracoes_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores têm acesso às configurações.")

    band = get_object_or_404(Band, slug=band_slug)

    if request.method == 'POST':
        if 'logo' in request.FILES:
            band.logo = request.FILES['logo']
            band.save()
            return redirect('configuracoes', band_slug=band.slug)

    context = {
        'band': band,
    }
    return render(request, 'core/configuracoes.html', context)

@login_required
@band_required
def shows_list_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores.")
    band = get_object_or_404(Band, slug=band_slug)
    shows = Show.objects.filter(band=band).order_by('date', 'show_time')

    # Filtros
    q = request.GET.get('q')
    status = request.GET.get('status')
    payment_status = request.GET.get('payment_status')
    month = request.GET.get('month')
    contract_type = request.GET.get('contract_type')

    if q:
        shows = shows.filter(title__icontains=q)
    if contract_type:
        shows = shows.filter(contract_type__icontains=contract_type)
    if status == 'CONCLUIDO':
        from datetime import date
        shows = shows.filter(date__lt=date.today()).exclude(status='CANCELADO')
    elif status == 'CANCELADO':
        shows = shows.filter(status='CANCELADO')
    elif status:
        from datetime import date
        from django.db.models import Q
        shows = shows.filter(Q(date__gte=date.today()) | Q(date__isnull=True), status=status)
    if payment_status:
        shows = shows.filter(payment_status=payment_status)
    if month and '-' in month:
        year, m = month.split('-')
        shows = shows.filter(date__year=year, date__month=m)

    context = {
        'band': band,
        'shows': shows,
        'current_q': q,
        'current_status': status,
        'current_payment_status': payment_status,
        'current_month': month,
        'current_contract_type': contract_type
    }
    return render(request, 'core/shows.html', context)

@login_required
@band_required
def show_create_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem adicionar shows.")

    band = get_object_or_404(Band, slug=band_slug)

    if request.method == 'POST':
        form = ShowForm(request.POST, request.FILES)
        if form.is_valid():
            with transaction.atomic():
                show = form.save(commit=False)
                show.band = band
                # Criação mantém notification_revision=0
                show.save()

                # Agenda notificação de NEW_SHOW
                from core.services.show_notifications import schedule_show_notifications
                schedule_show_notifications(old_show=None, new_show=show, actor=request.user, is_creation=True)

            messages.success(request, "Show adicionado com sucesso!")
            if 'save_and_continue' in request.POST:
                return redirect('shows_edit', band_slug=band.slug, pk=show.id)
            return redirect('calendario', band_slug=band.slug)
    else:
        form = ShowForm()

    context = {
        'band': band,
        'form': form,
        'is_edit': False
    }
    return render(request, 'core/show_form.html', context)

@login_required
@band_required
def show_edit_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem editar shows.")

    band = get_object_or_404(Band, slug=band_slug)
    show_to_edit = get_object_or_404(Show, pk=pk, band=band)

    if request.method == 'POST':
        with transaction.atomic():
            # Bloqueio concorrente
            show_to_edit = Show.objects.select_for_update().get(pk=pk, band=band)

            # Snapshot antigo
            old_date = show_to_edit.date
            old_show_time = show_to_edit.show_time
            old_status = show_to_edit.status

            form = ShowForm(request.POST, request.FILES, instance=show_to_edit)
            doc_formset = ContractDocumentFormSet(request.POST, request.FILES, instance=show_to_edit)

            if form.is_valid() and doc_formset.is_valid():
                # Detectar eventos relevantes
                new_date = form.cleaned_data.get('date')
                new_show_time = form.cleaned_data.get('show_time')
                new_status = form.cleaned_data.get('status')

                has_relevant_event = (
                    (old_date != new_date) or
                    (old_show_time != new_show_time) or
                    (old_status != 'CANCELADO' and new_status == 'CANCELADO')
                )

                if has_relevant_event:
                    show_to_edit.notification_revision += 1

                form.save()
                doc_formset.save()

                if has_relevant_event:
                    from core.services.show_notifications import schedule_show_notifications

                    # Precisamos montar um mock do old_show contendo apenas o que importa,
                    # ou podemos passar um dict, mas a assinatura aceita "old_show" que pode
                    # ser um objeto temporário simulado ou usamos uma dataclass mock.
                    # Como Python é flexível, criamos um dummy object para o old_show:
                    class OldShowMock:
                        def __init__(self):
                            self.date = old_date
                            self.show_time = old_show_time
                            self.status = old_status

                    schedule_show_notifications(
                        old_show=OldShowMock(),
                        new_show=show_to_edit,
                        actor=request.user,
                        is_creation=False
                    )

                messages.success(request, "Show atualizado com sucesso!")
                if 'save_and_continue' in request.POST:
                    return redirect('shows_edit', band_slug=band.slug, pk=show_to_edit.id)
                return redirect('calendario', band_slug=band.slug)
    else:
        form = ShowForm(instance=show_to_edit)
        doc_formset = ContractDocumentFormSet(instance=show_to_edit)

    context = {
        'band': band,
        'form': form,
        'is_edit': True,
        'show_to_edit': show_to_edit,
        'doc_formset': doc_formset
    }
    return render(request, 'core/show_form.html', context)

@login_required
@band_required
def show_delete_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem excluir shows.")

    band = get_object_or_404(Band, slug=band_slug)
    show_to_delete = get_object_or_404(Show, pk=pk, band=band)

    if request.method == 'POST':
        show_to_delete.delete()
        messages.success(request, "Show removido com sucesso!")

    return redirect('calendario', band_slug=band.slug)

@login_required
@band_required
def usuarios_list_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores.")
    band = get_object_or_404(Band, slug=band_slug)
    usuarios = User.objects.filter(band=band).order_by('first_name', 'username')

    context = {'band': band, 'usuarios': usuarios}
    return render(request, 'core/usuarios.html', context)

@login_required
@band_required
def usuario_create_view(request, band_slug):
    if not request.user.is_produtor() and not request.user.is_superuser:
        return HttpResponseForbidden("Apenas produtores podem adicionar usuários.")

    band = get_object_or_404(Band, slug=band_slug)

    if request.method == 'POST':
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.band = band
            # A senha é hasheada no método save do form
            user.save()
            messages.success(request, "Usuário criado com sucesso!")
            return redirect('usuarios_list', band_slug=band.slug)
    else:
        form = UserForm()

    context = {
        'band': band,
        'form': form,
        'is_edit': False
    }
    return render(request, 'core/usuario_form.html', context)

@login_required
@band_required
def usuario_edit_view(request, band_slug, pk):
    if not request.user.is_produtor() and not request.user.is_superuser:
        return HttpResponseForbidden("Apenas produtores podem editar usuários.")

    band = get_object_or_404(Band, slug=band_slug)
    user_to_edit = get_object_or_404(User, pk=pk, band=band)

    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user_to_edit)
        if form.is_valid():
            form.save()
            messages.success(request, "Usuário atualizado com sucesso!")
            return redirect('usuarios_list', band_slug=band.slug)
    else:
        form = UserEditForm(instance=user_to_edit)

    context = {
        'band': band,
        'form': form,
        'is_edit': True,
        'user_to_edit': user_to_edit
    }
    return render(request, 'core/usuario_form.html', context)

@login_required
@band_required
def usuario_delete_view(request, band_slug, pk):
    if not request.user.is_produtor() and not request.user.is_superuser:
        return HttpResponseForbidden("Apenas produtores podem excluir usuários.")

    band = get_object_or_404(Band, slug=band_slug)
    user_to_delete = get_object_or_404(User, pk=pk, band=band)

    if request.method == 'POST':
        user_to_delete.delete()
        messages.success(request, "Usuário excluído com sucesso!")

    return redirect('usuarios_list', band_slug=band.slug)

@login_required
@band_required
def contatos_list_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores.")
    band = get_object_or_404(Band, slug=band_slug)
    contatos = Contact.objects.filter(band=band).order_by('name')

    context = {'band': band, 'contatos': contatos}
    return render(request, 'core/contatos.html', context)

@login_required
@band_required
def contato_create_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem adicionar contatos.")

    band = get_object_or_404(Band, slug=band_slug)

    if request.method == 'POST':
        form = ContactForm(request.POST)
        if form.is_valid():
            contact = form.save(commit=False)
            contact.band = band
            contact.save()
            messages.success(request, "Contato criado com sucesso!")
            return redirect('contatos_list', band_slug=band.slug)
    else:
        form = ContactForm()

    context = {
        'band': band,
        'form': form,
        'is_edit': False
    }
    return render(request, 'core/contato_form.html', context)

@login_required
@band_required
def contato_edit_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem editar contatos.")

    band = get_object_or_404(Band, slug=band_slug)
    contact_to_edit = get_object_or_404(Contact, pk=pk, band=band)

    if request.method == 'POST':
        form = ContactForm(request.POST, instance=contact_to_edit)
        if form.is_valid():
            form.save()
            messages.success(request, "Contato atualizado com sucesso!")
            return redirect('contatos_list', band_slug=band.slug)
    else:
        form = ContactForm(instance=contact_to_edit)

    context = {
        'band': band,
        'form': form,
        'is_edit': True,
        'contact_to_edit': contact_to_edit
    }
    return render(request, 'core/contato_form.html', context)

@login_required
@band_required
def contato_delete_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem excluir contatos.")

    band = get_object_or_404(Band, slug=band_slug)
    contact = get_object_or_404(Contact, pk=pk, band=band)

    if request.method == 'POST':
        contact.delete()
        messages.success(request, "Contato excluído com sucesso!")
        return redirect('contatos_list', band_slug=band.slug)

    return redirect('contatos_list', band_slug=band.slug)

@login_required
@band_required
def payment_create_view(request, band_slug, show_id):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem adicionar recebimentos.")

    band = get_object_or_404(Band, slug=band_slug)
    show = get_object_or_404(Show, pk=show_id, band=band)

    if request.method == 'POST':
        form = ShowPaymentForm(request.POST, request.FILES)
        if form.is_valid():
            payment = form.save(commit=False)
            payment.show = show
            payment.created_by = request.user
            payment.save()
            messages.success(request, "Recebimento adicionado com sucesso!")
            if request.GET.get('next') in ['financeiro', 'show_finance_detail']:
                return redirect('show_finance_detail', band_slug=band.slug, pk=show.id)
            return redirect('show_detail', band_slug=band.slug, pk=show.id)
    else:
        form = ShowPaymentForm()

    context = {
        'band': band,
        'show': show,
        'form': form,
        'is_edit': False
    }
    return render(request, 'core/payment_form.html', context)
@login_required
@band_required
def receipt_edit_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem editar comprovantes.")

    band = get_object_or_404(Band, slug=band_slug)
    receipt = get_object_or_404(FinancialReceipt, pk=pk, show__band=band)
    show = receipt.show

    if request.method == 'POST':
        form = FinancialReceiptForm(request.POST, request.FILES, instance=receipt)
        if form.is_valid():
            form.save()
            messages.success(request, "Comprovante atualizado com sucesso!")
            next_url = request.GET.get('next')
            if next_url in ['financeiro', 'show_finance_detail']:
                return redirect('show_finance_detail', band_slug=band.slug, pk=show.id)
            elif next_url == 'arquivos':
                return redirect('arquivos', band_slug=band.slug)
            elif next_url == 'shows_edit':
                from django.urls import reverse
                return redirect(f"{reverse('shows_edit', args=[band.slug, show.id])}#anexos")
            return redirect('show_detail', band_slug=band.slug, pk=show.id)
    else:
        form = FinancialReceiptForm(instance=receipt)

    context = {
        'band': band,
        'show': show,
        'form': form,
        'is_edit': True,
        'receipt': receipt
    }
    return render(request, 'core/receipt_form.html', context)

@login_required
@band_required
def document_edit_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem editar documentos.")

    band = get_object_or_404(Band, slug=band_slug)
    document = get_object_or_404(ContractDocument, pk=pk, show__band=band)
    show = document.show

    if request.method == 'POST':
        form = ContractDocumentForm(request.POST, request.FILES, instance=document)
        if form.is_valid():
            form.save()
            messages.success(request, "Documento atualizado com sucesso!")
            if request.GET.get('next') == 'arquivos':
                return redirect('arquivos', band_slug=band.slug)
            return redirect('shows_edit', band_slug=band.slug, pk=show.id)
    else:
        form = ContractDocumentForm(instance=document)

    context = {
        'band': band,
        'show': show,
        'form': form,
        'document': document,
    }
    return render(request, 'core/document_form.html', context)

@login_required
@band_required
def document_delete_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem excluir documentos.")

    band = get_object_or_404(Band, slug=band_slug)
    document = get_object_or_404(ContractDocument, pk=pk, show__band=band)
    show_id = document.show.id

    if request.method == 'POST':
        document.delete()
        messages.success(request, "Documento excluído com sucesso!")
        next_url = request.GET.get('next')
        if next_url == 'arquivos':
            return redirect('arquivos', band_slug=band.slug)
        return redirect('shows_edit', band_slug=band.slug, pk=show_id)

    return redirect('arquivos', band_slug=band.slug)

@login_required
@band_required
def payment_edit_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem editar recebimentos.")

    band = get_object_or_404(Band, slug=band_slug)
    payment = get_object_or_404(ShowPayment, pk=pk, show__band=band)
    show = payment.show

    if request.method == 'POST':
        form = ShowPaymentForm(request.POST, request.FILES, instance=payment)
        if form.is_valid():
            form.save()
            messages.success(request, "Recebimento atualizado com sucesso!")
            if request.GET.get('next') in ['financeiro', 'show_finance_detail']:
                return redirect('show_finance_detail', band_slug=band.slug, pk=show.id)
            return redirect('show_detail', band_slug=band.slug, pk=show.id)
    else:
        form = ShowPaymentForm(instance=payment)

    context = {
        'band': band,
        'show': show,
        'form': form,
        'is_edit': True,
        'payment': payment
    }
    return render(request, 'core/payment_form.html', context)

@login_required
@band_required
def payment_delete_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem excluir recebimentos.")

    band = get_object_or_404(Band, slug=band_slug)
    payment = get_object_or_404(ShowPayment, pk=pk, show__band=band)
    show_id = payment.show.id

    if request.method == 'POST':
        payment.delete()
        messages.success(request, "Recebimento removido com sucesso!")
        if request.GET.get('next') in ['financeiro', 'show_finance_detail']:
            return redirect('show_finance_detail', band_slug=band.slug, pk=show_id)
        return redirect('show_detail', band_slug=band.slug, pk=show_id)

    context = {
        'band': band,
        'payment': payment
    }
    return render(request, 'core/payment_confirm_delete.html', context)

@login_required
@band_required
def manage_team_costs_view(request, band_slug, show_id):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem gerenciar custos com equipe.")

    band = get_object_or_404(Band, slug=band_slug)
    show = get_object_or_404(Show, pk=show_id, band=band)
    team_costs = show.team_costs.all().order_by('name')

    if request.method == 'POST':
        form = ShowTeamCostForm(request.POST)
        if form.is_valid():
            team_cost = form.save(commit=False)
            team_cost.show = show
            team_cost.created_by = request.user
            team_cost.save()
            messages.success(request, "Custo com equipe adicionado com sucesso!")
            return redirect('manage_team_costs', band_slug=band.slug, show_id=show.id)
    else:
        form = ShowTeamCostForm()

    context = {
        'band': band,
        'show': show,
        'team_costs': team_costs,
        'form': form,
    }
    return render(request, 'core/manage_team_costs.html', context)

@login_required
@band_required
def teamcost_delete_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem excluir custos com equipe.")

    band = get_object_or_404(Band, slug=band_slug)
    team_cost = get_object_or_404(ShowTeamCost, pk=pk, show__band=band)
    show_id = team_cost.show.id

    if request.method == 'POST':
        team_cost.delete()
        messages.success(request, "Custo com equipe removido com sucesso!")
        if request.GET.get('next') in ['financeiro', 'show_finance_detail']:
            return redirect('show_finance_detail', band_slug=band.slug, pk=show_id)
        return redirect('manage_team_costs', band_slug=band.slug, show_id=show_id)

    context = {
        'band': band,
        'team_cost': team_cost
    }
    return render(request, 'core/teamcost_confirm_delete.html', context)


@login_required
def teamcost_edit_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem editar custos com equipe.")

    band = get_object_or_404(Band, slug=band_slug)
    team_cost = get_object_or_404(ShowTeamCost, pk=pk, show__band=band)
    show = team_cost.show

    if request.method == 'POST':
        form = ShowTeamCostForm(request.POST, instance=team_cost)
        if form.is_valid():
            form.save()
            messages.success(request, "Custo com equipe atualizado com sucesso!")
            next_url = request.GET.get('next')
            if next_url in ['financeiro', 'show_finance_detail']:
                return redirect('show_finance_detail', band_slug=band.slug, pk=show.id)
            return redirect('manage_team_costs', band_slug=band.slug, show_id=show.id)
    return redirect('show_finance_detail', band_slug=band.slug, pk=show.id)


@login_required
def receipt_delete_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem excluir comprovantes.")

    band = get_object_or_404(Band, slug=band_slug)
    receipt = get_object_or_404(FinancialReceipt, pk=pk, show__band=band)
    show_id = receipt.show.id

    if request.method == 'POST':
        receipt.delete()
        messages.success(request, "Comprovante excluído com sucesso!")
        next_url = request.GET.get('next')
        if next_url in ['financeiro', 'show_finance_detail']:
            return redirect('show_finance_detail', band_slug=band.slug, pk=show_id)
        elif next_url == 'arquivos':
            return redirect('arquivos', band_slug=band.slug)
        return redirect('shows_edit', band_slug=band.slug, pk=show_id)

    context = {
        'band': band,
        'receipt': receipt
    }
    return render(request, 'core/receipt_confirm_delete.html', context)


@login_required
@band_required
@require_POST
def add_dashboard_pending_item(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem gerenciar pendências.")
    band = get_object_or_404(Band, slug=band_slug)
    description = request.POST.get('description', '').strip()
    show_id = request.POST.get('show')

    if not description:
        messages.error(request, "Digite uma pendência válida.")
        return redirect('dashboard', band_slug=band.slug)

    if len(description) > 500:
        messages.error(request, "A pendência deve ter no máximo 500 caracteres.")
        return redirect('dashboard', band_slug=band.slug)

    if not show_id:
        messages.error(request, "Selecione um show.")
        return redirect('dashboard', band_slug=band.slug)

    show = get_object_or_404(Show, id=show_id, band=band)

    BandDashboardPendingItem.objects.create(
        band=band,
        show=show,
        description=description,
        created_by=request.user
    )

    messages.success(request, "Pendência adicionada com sucesso.")
    return redirect('dashboard', band_slug=band.slug)

@login_required
@band_required
@require_POST
def delete_dashboard_pending_item(request, band_slug, pending_id):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem gerenciar pendências.")
    band = get_object_or_404(Band, slug=band_slug)
    pending_item = get_object_or_404(BandDashboardPendingItem, id=pending_id, band=band)

    pending_item.delete()

    messages.success(request, "Pendência excluída com sucesso.")
    return redirect('dashboard', band_slug=band.slug)
