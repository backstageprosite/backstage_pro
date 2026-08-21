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

from .models import Show, FinancialReceipt, Band, User, Contact, ContractDocument, ShowPayment, ShowTeamCost, BandDashboardPendingItem, AdministrativeBandNotice, RiderDocument

from .forms import FinancialReceiptForm, UserForm, UserEditForm, ContactForm, ShowForm, ContractDocumentFormSet, FinancialReceiptFormSet, ShowPaymentForm, ShowTeamCostForm, ContractDocumentForm, RiderDocumentForm

from decimal import Decimal



def landing_page_view(request):

    """

    Landing page principal de vendas do Backstage Pro.

    """

    from .models import LandingPageBandLogo

    landing_band_logos = LandingPageBandLogo.objects.filter(is_active=True)

    return render(request, 'core/landing.html', {'landing_band_logos': landing_band_logos})



def landing_page_logo_image_view(request, pk):

    from .models import LandingPageBandLogo

    import mimetypes

    from django.http import FileResponse, Http404



    logo = get_object_or_404(LandingPageBandLogo, pk=pk)

    if not logo.image:

        raise Http404("Logo sem imagem")



    try:

        content_type, _ = mimetypes.guess_type(logo.image.name)

        if not content_type:

            content_type = 'application/octet-stream'



        response = FileResponse(logo.image.open('rb'), content_type=content_type)

        response['Cache-Control'] = 'public, max-age=86400'

        return response

    except Exception:

        raise Http404("Erro ao acessar imagem")



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



    def dispatch(self, request, *args, **kwargs):

        if request.user.is_authenticated:

            band_slug = self.kwargs.get('band_slug')

            band = get_object_or_404(Band, slug=band_slug)



            if request.user.is_superuser:

                return redirect('admin_painel:dashboard')



            if request.user.band:

                if request.user.band != band:

                    raise PermissionDenied("Você não pertence a esta banda.")

                return redirect('dashboard', band_slug=band.slug)

            else:

                raise PermissionDenied("Você não pertence a esta banda.")



        return super().dispatch(request, *args, **kwargs)



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



@require_POST

def band_logout(request, band_slug):

    logout(request)

    return redirect('login', band_slug=band_slug)



@login_required

@band_required

def dashboard_view(request, band_slug):

    band = get_object_or_404(Band, slug=band_slug)

    shows_proximos = Show.objects.filter(band=band, date__gte=datetime.date.today()).order_by('date', 'show_time')[:6]

    total_shows = Show.objects.filter(band=band).count()

    total_users = 0

    total_contacts = 0



    from django.db.models import Case, When, Value, IntegerField, F

    from django.utils import timezone



    today = timezone.localdate()



    dashboard_pending_items = None

    pending_item_form = None

    administrative_notices = None

    user_is_band_producer = request.user.band == band and request.user.is_produtor()



    if user_is_band_producer:

        total_users = User.objects.filter(band=band).count()

        total_contacts = Contact.objects.filter(band=band).count()



        dashboard_pending_items = (

            BandDashboardPendingItem.objects

            .filter(band=band)

            .select_related("show", "created_by")

            .with_ordering()[:4]

        )



        from django.db.models import Q, F

        shows = Show.objects.filter(

            Q(band=band) & (Q(date__gte=today) | Q(date__isnull=True))

        ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')

        from .forms import BandDashboardPendingItemForm

        pending_item_form = BandDashboardPendingItemForm(shows_qs=shows)



        for item in dashboard_pending_items:

            item_shows = Show.objects.filter(

                Q(band=band) & (Q(date__gte=today) | Q(date__isnull=True) | Q(pk=item.show_id))

            ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')

            item.edit_form = BandDashboardPendingItemForm(instance=item, shows_qs=item_shows, prefix=f"edit_{item.id}")



        administrative_notices = AdministrativeBandNotice.objects.filter(

            Q(band=band) | Q(band__isnull=True)

        ).order_by('-created_at')



    from core.models import BandNotice
    band_notices = BandNotice.objects.filter(band=band)[:5]

    context = {

        'band': band,

        'shows_proximos': shows_proximos,

        'total_shows': total_shows,

        'total_users': total_users,

        'total_contacts': total_contacts,

        'dashboard_pending_items': dashboard_pending_items,

        'pending_item_form': pending_item_form,

        'administrative_notices': administrative_notices,

        'user_is_band_producer': user_is_band_producer,

        'band_notices': band_notices,
    }

    return render(request, 'core/dashboard.html', context)



@login_required

@band_required

def pending_list_view(request, band_slug):

    band = request.band



    user_is_band_producer = request.user.band == band and request.user.is_produtor()

    if not user_is_band_producer:

        from django.core.exceptions import PermissionDenied

        raise PermissionDenied("Apenas produtores podem visualizar ou gerenciar as pendências.")



    from django.utils import timezone

    today = timezone.localdate()



    dashboard_pending_items = (

        BandDashboardPendingItem.objects

        .filter(band=band)

        .select_related("show", "created_by")

        .with_ordering()

    )



    pending_item_form = None

    user_is_band_producer = request.user.band == band and request.user.is_produtor()



    if user_is_band_producer:

        from django.db.models import Q, F

        shows = Show.objects.filter(

            Q(band=band) & (Q(date__gte=today) | Q(date__isnull=True))

        ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')

        from .forms import BandDashboardPendingItemForm

        pending_item_form = BandDashboardPendingItemForm(shows_qs=shows)



        for item in dashboard_pending_items:

            item_shows = Show.objects.filter(

                Q(band=band) & (Q(date__gte=today) | Q(date__isnull=True) | Q(pk=item.show_id))

            ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')

            item.edit_form = BandDashboardPendingItemForm(instance=item, shows_qs=item_shows, prefix=f"edit_{item.id}")



    from core.models import BandNotice
    band_notices = BandNotice.objects.filter(band=band)[:5]

    context = {

        'band': band,

        'pending_items': dashboard_pending_items,

        'pending_item_form': pending_item_form,

        'user_is_band_producer': user_is_band_producer,

    }

    return render(request, 'core/pending_list.html', context)





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



                payment_status = request.POST.get('payment_status')

                if payment_status in ['PENDENTE', 'PARCIAL', 'PAGO']:

                    show.payment_status = payment_status



                show.save()

                messages.success(request, 'Cachê atualizado com sucesso!')

            except Exception as e:

                messages.error(request, f'Valor de cachê inválido: {str(e)}')

            return redirect('show_finance_detail', band_slug=band_slug, pk=show.id)



        if 'submit_receipt' in request.POST:

            receipt_form = FinancialReceiptForm(request.POST, request.FILES)

            if receipt_form.is_valid():

                from core.file_policy import check_show_limits
                from django.core.exceptions import ValidationError
                new_files_sizes = [f.size for f in request.FILES.values()]
                if new_files_sizes:
                    try:
                        check_show_limits(show, new_files_sizes)
                    except ValidationError as e:
                        messages.error(request, e.message)
                        return redirect('show_finance_detail', band_slug=band_slug, pk=show.id)

                receipt = receipt_form.save(commit=False)

                receipt.show = show

                receipt.save()

                messages.success(request, 'Comprovante adicionado com sucesso!')

                return redirect('show_finance_detail', band_slug=band_slug, pk=show.id)

        elif 'submit_payment' in request.POST:

            payment_form = ShowPaymentForm(request.POST, request.FILES)

            if payment_form.is_valid():

                from core.file_policy import check_show_limits
                from django.core.exceptions import ValidationError
                new_files_sizes = [f.size for f in request.FILES.values()]
                if new_files_sizes:
                    try:
                        check_show_limits(show, new_files_sizes)
                    except ValidationError as e:
                        messages.error(request, e.message)
                        return redirect('show_finance_detail', band_slug=band_slug, pk=show.id)

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

    try:
        from core.services.weather_services import get_weather_for_show
        weather = get_weather_for_show(show.city, show.date)
    except Exception:
        weather = None

    from django.template.loader import render_to_string
    from xhtml2pdf import pisa
    import io
    from django.http import HttpResponse

    context = {
        'show': show,
        'weather': weather,
        'request': request,
    }
    html_string = render_to_string('core/show_pdf.html', context, request=request)
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html_string.encode("UTF-8")), result)
    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="show.pdf"'
        response['Cache-Control'] = 'private, no-store'
        return response
    return HttpResponse('Erro ao gerar PDF', status=500)



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



    from django.template.loader import render_to_string
    from xhtml2pdf import pisa
    import io
    from django.http import HttpResponse

    context = {
        'shows': shows,
        'band': request.band,
        'today': datetime.date.today(),
        'request': request,
    }
    html_string = render_to_string('core/agenda_pdf.html', context, request=request)
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html_string.encode("UTF-8")), result)
    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="agenda.pdf"'
        response['Cache-Control'] = 'private, no-store'
        return response
    return HttpResponse('Erro ao gerar PDF', status=500)



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

        subscription = band.subscriptions.filter(status='ATIVO', is_deleted=False).first()



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



    subscription = band.subscriptions.filter(status='ATIVO', is_deleted=False).first()

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

    band = get_object_or_404(Band, slug=band_slug)



    if request.method == 'POST':

        if not request.user.is_produtor():

            return HttpResponseForbidden("Apenas produtores podem alterar a identidade visual da banda.")

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

                from core.file_policy import check_show_limits
                from django.core.exceptions import ValidationError
                new_files_sizes = [f.size for f in request.FILES.values()]
                if new_files_sizes:
                    try:
                        check_show_limits(show_to_edit, new_files_sizes)
                    except ValidationError as e:
                        messages.error(request, e.message)
                        from core.file_policy import get_show_files_info
                        files_count, files_size = get_show_files_info(show_to_edit)
                        context = {
                            'band': band,
                            'form': form,
                            'is_edit': True,
                            'show_to_edit': show_to_edit,
                            'doc_formset': doc_formset,
                            'files_count': files_count,
                            'files_size_mb': round(files_size / 1024 / 1024, 2) if files_size else 0
                        }
                        return render(request, 'core/show_form.html', context)

                # Detectar eventos relevantes

                new_date = form.cleaned_data.get('date')

                new_show_time = form.cleaned_data.get('show_time')

                new_status = form.cleaned_data.get('status')



                has_relevant_event = (

                    (old_date != new_date) or

                    (old_show_time != new_show_time) or

                    (old_status != 'CANCELADO' and new_status == 'CANCELADO') or

                    (old_status != 'CONFIRMADO' and new_status == 'CONFIRMADO')

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



    from core.file_policy import get_show_files_info
    files_count, files_size = get_show_files_info(show_to_edit)

    context = {

        'band': band,

        'form': form,

        'is_edit': True,

        'show_to_edit': show_to_edit,

        'doc_formset': doc_formset,

        'files_count': files_count,

        'files_size_mb': round(files_size / 1024 / 1024, 2) if files_size else 0

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

def usuario_reset_password_view(request, band_slug, pk):

    if not request.user.is_produtor() and not request.user.is_superuser:

        return HttpResponseForbidden("Apenas produtores podem redefinir senhas.")



    band = get_object_or_404(Band, slug=band_slug)

    user_to_edit = get_object_or_404(User, pk=pk, band=band)



    if request.method == 'POST':

        new_password = request.POST.get('new_password')

        confirm_password = request.POST.get('confirm_password')



        if not new_password or not confirm_password:

            messages.error(request, "As senhas não podem ser vazias.")

        elif new_password != confirm_password:

            messages.error(request, "As senhas não conferem. Tente novamente.")

        else:

            user_to_edit.set_password(new_password)

            user_to_edit.save()

            messages.success(request, f"Senha do usuário {user_to_edit.username} redefinida com sucesso!")



    return redirect('usuarios_list', band_slug=band.slug)



@login_required

@band_required

def contatos_list_view(request, band_slug):

    if not request.user.is_produtor():

        return HttpResponseForbidden("Apenas produtores.")

    band = get_object_or_404(Band, slug=band_slug)



    # Base QuerySet

    contatos = Contact.objects.filter(band=band).order_by('name')



    # Get Filter Params

    search_name = request.GET.get('nome', '').strip()

    search_tipo = request.GET.get('tipo', '').strip()

    search_local = request.GET.get('local', '').strip()



    if search_name:

        contatos = contatos.filter(name__icontains=search_name)

    if search_tipo:

        contatos = contatos.filter(contact_type=search_tipo)

    if search_local:

        contatos = contatos.filter(location__icontains=search_local)



    context = {

        'band': band,

        'contatos': contatos,

        'search_name': search_name,

        'search_tipo': search_tipo,

        'search_local': search_local,

        'contact_types': Contact.CONTACT_TYPE_CHOICES,

    }

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
            if contact.is_shared_globally:
                from django.utils import timezone
                contact.shared_by = request.user
                contact.shared_at = timezone.now()
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
    was_shared = contact_to_edit.is_shared_globally

    if request.method == 'POST':
        form = ContactForm(request.POST, instance=contact_to_edit)
        if form.is_valid():
            contact = form.save(commit=False)

            if contact.is_shared_globally and not was_shared:
                from django.utils import timezone
                contact.shared_by = request.user
                contact.shared_at = timezone.now()
            elif not contact.is_shared_globally:
                contact.shared_by = None
                contact.shared_at = None

            contact.save()
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
def banco_de_dados_view(request):
    user_band = request.user.band
    if not request.user.is_superuser:
        if not user_band or not user_band.is_active:
            return HttpResponseForbidden("Acesso negado: Vínculo com banda ativa necessário.")
        if request.user.role not in ['PRODUTOR', 'EMPRESARIO', 'INTEGRANTE']:
            return HttpResponseForbidden("Acesso negado: Perfil não autorizado.")

    contacts = Contact.objects.filter(
        is_shared_globally=True,
        band__is_active=True
    ).select_related('band', 'shared_by').order_by('name')

    search_query = request.GET.get('q', '').strip()
    search_type = request.GET.get('tipo', '').strip()
    search_location = request.GET.get('local', '').strip()
    search_band = request.GET.get('banda', '').strip()

    if search_query:
        contacts = contacts.filter(
            models.Q(name__icontains=search_query) |
            models.Q(phone__icontains=search_query) |
            models.Q(email__icontains=search_query)
        )
    if search_type:
        contacts = contacts.filter(contact_type=search_type)
    if search_location:
        contacts = contacts.filter(location__icontains=search_location)
    if search_band:
        contacts = contacts.filter(band__name__icontains=search_band)

    from django.core.paginator import Paginator
    paginator = Paginator(contacts, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'band': user_band,
        'page_obj': page_obj,
        'search_query': search_query,
        'search_type': search_type,
        'search_location': search_location,
        'search_band': search_band,
        'contact_types': Contact.CONTACT_TYPE_CHOICES
    }
    return render(request, 'core/banco_de_dados.html', context)

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

    band = get_object_or_404(Band, slug=band_slug)

    if request.user.band != band or not request.user.is_produtor():

        return HttpResponseForbidden("Apenas produtores vinculados à banda podem gerenciar pendências.")



    from django.utils import timezone

    from django.db.models import Q, F

    shows = Show.objects.filter(

        Q(band=band) & (Q(date__gte=timezone.localdate()) | Q(date__isnull=True))

    ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')



    from .forms import BandDashboardPendingItemForm

    form = BandDashboardPendingItemForm(request.POST, shows_qs=shows)



    if form.is_valid():

        pending_item = form.save(commit=False)

        pending_item.band = band

        pending_item.created_by = request.user

        pending_item.save()

        messages.success(request, "Pendência adicionada com sucesso.")

    else:

        for field in form.errors:

            messages.error(request, form.errors[field][0])

            break



    next_url = request.POST.get('next')

    if next_url:

        from django.utils.http import url_has_allowed_host_and_scheme

        if url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):

            return redirect(next_url)



    return redirect('dashboard', band_slug=band.slug)



@login_required

@band_required

@require_POST

def delete_dashboard_pending_item(request, band_slug, pending_id):

    band = get_object_or_404(Band, slug=band_slug)

    if request.user.band != band or not request.user.is_produtor():

        return HttpResponseForbidden("Apenas produtores vinculados à banda podem gerenciar pendências.")

    pending_item = get_object_or_404(BandDashboardPendingItem, id=pending_id, band=band)



    pending_item.delete()



    messages.success(request, "Pendência excluída com sucesso.")



    next_url = request.POST.get('next')

    if next_url:

        from django.utils.http import url_has_allowed_host_and_scheme

        if url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):

            return redirect(next_url)



    return redirect('dashboard', band_slug=band.slug)



@login_required

@band_required

@require_POST

def edit_dashboard_pending_item(request, band_slug, pending_id):

    band = get_object_or_404(Band, slug=band_slug)

    if request.user.band != band or not request.user.is_produtor():

        return HttpResponseForbidden("Apenas produtores vinculados à banda podem gerenciar pendências.")

    pending_item = get_object_or_404(BandDashboardPendingItem, id=pending_id, band=band)



    from django.utils import timezone

    from django.db.models import Q, F



    shows = Show.objects.filter(

        Q(band=band) & (Q(date__gte=timezone.localdate()) | Q(date__isnull=True) | Q(pk=pending_item.show_id))

    ).order_by(F('date').asc(nulls_last=True), 'show_time', 'pk')



    from .forms import BandDashboardPendingItemForm

    form = BandDashboardPendingItemForm(request.POST, instance=pending_item, shows_qs=shows, prefix=f"edit_{pending_item.id}")



    if form.is_valid():

        updated_item = form.save(commit=False)

        updated_item.band = band

        updated_item.save()

        messages.success(request, "Pendência atualizada com sucesso.")

    else:

        for field in form.errors:

            messages.error(request, form.errors[field][0])

            break



    next_url = request.POST.get('next')

    if next_url:

        from django.utils.http import url_has_allowed_host_and_scheme

        if url_has_allowed_host_and_scheme(url=next_url, allowed_hosts={request.get_host()}):

            return redirect(next_url)



    return redirect('dashboard', band_slug=band.slug)





from .models import Partner



@band_required

def partners_list_view(request, band_slug):

    partners = Partner.objects.filter(is_active=True)

    return render(request, 'core/partners.html', {'partners': partners, 'band': request.band})





@login_required

@band_required

def instalar_aplicativo_view(request, band_slug):

    return render(request, 'core/instalar_aplicativo.html', {'band': request.band})



@login_required

@band_required

def rider_list_view(request, band_slug):

    band = request.band



    if request.method == 'POST':

        if not request.user.is_produtor():

            raise PermissionDenied("Apenas produtores podem gerenciar Riders.")



        if 'add_rider' in request.POST:

            form = RiderDocumentForm(request.POST, request.FILES)

            if form.is_valid():

                rider = form.save(commit=False)

                rider.band = band

                rider.created_by = request.user

                rider.save()

                messages.success(request, 'Rider adicionado com sucesso!')

            else:

                messages.error(request, 'Erro ao adicionar Rider. Verifique os dados.')

            return redirect('rider_list', band_slug=band.slug)



        elif 'edit_rider' in request.POST:

            rider_id = request.POST.get('rider_id')

            rider = get_object_or_404(RiderDocument, id=rider_id, band=band)

            form = RiderDocumentForm(request.POST, request.FILES, instance=rider)

            if form.is_valid():

                form.save()

                messages.success(request, 'Rider atualizado com sucesso!')

            else:

                messages.error(request, 'Erro ao atualizar Rider.')

            return redirect('rider_list', band_slug=band.slug)



        elif 'delete_rider' in request.POST:

            rider_id = request.POST.get('rider_id')

            rider = get_object_or_404(RiderDocument, id=rider_id, band=band)

            rider.delete()

            messages.success(request, 'Rider excluído com sucesso!')

            return redirect('rider_list', band_slug=band.slug)



    riders = RiderDocument.objects.filter(band=band)

    form = RiderDocumentForm()



    context = {

        'band': band,

        'riders': riders,

        'form': form,

    }

    return render(request, 'core/rider_list.html', context)



# ==========================================

# VIEWS DE INTEGRANTES

# ==========================================

import json

from django.http import JsonResponse

from .models import Integrante

from .forms import IntegranteForm



@login_required

@band_required

def integrantes_list_view(request, band_slug):

    band = get_object_or_404(Band, slug=band_slug)



    if request.method == 'POST':

        if not request.user.is_produtor():

            return HttpResponseForbidden("Apenas produtores podem gerenciar integrantes.")



        action = request.POST.get('action')

        if action == 'add':

            form = IntegranteForm(request.POST)

            if form.is_valid():

                integrante = form.save(commit=False)

                integrante.band = band

                # Set order to the end

                from django.db.models import Max

                last_order = Integrante.objects.filter(band=band).aggregate(Max('order'))['order__max'] or 0

                integrante.order = last_order + 1

                integrante.save()

                messages.success(request, "Integrante adicionado com sucesso.")

            else:

                for field in form.errors:

                    messages.error(request, form.errors[field][0])

                    break

        elif action == 'edit':

            integrante_id = request.POST.get('integrante_id')

            integrante = get_object_or_404(Integrante, id=integrante_id, band=band)

            form = IntegranteForm(request.POST, instance=integrante)

            if form.is_valid():

                form.save()

                messages.success(request, "Integrante atualizado com sucesso.")

            else:

                for field in form.errors:

                    messages.error(request, form.errors[field][0])

                    break



        return redirect('integrantes_list', band_slug=band.slug)



    integrantes = Integrante.objects.filter(band=band)

    add_form = IntegranteForm()



    context = {

        'band': band,

        'integrantes': integrantes,

        'add_form': add_form,

    }

    return render(request, 'core/integrantes_list.html', context)



@login_required

@band_required

@require_POST

def integrante_delete_view(request, band_slug, pk):

    band = get_object_or_404(Band, slug=band_slug)

    if not request.user.is_produtor():

        return HttpResponseForbidden("Apenas produtores podem gerenciar integrantes.")



    integrante = get_object_or_404(Integrante, id=pk, band=band)

    integrante.delete()

    messages.success(request, "Integrante excluído com sucesso.")

    return redirect('integrantes_list', band_slug=band.slug)



@login_required

@band_required

@require_POST

def integrantes_reorder_view(request, band_slug):

    band = get_object_or_404(Band, slug=band_slug)

    if not request.user.is_produtor():

        return JsonResponse({'status': 'error', 'message': 'Permission denied'}, status=403)



    try:

        data = json.loads(request.body)

        order_list = data.get('order', [])



        for idx, item_id in enumerate(order_list):

            Integrante.objects.filter(id=item_id, band=band).update(order=idx)



        return JsonResponse({'status': 'success'})

    except Exception as e:

        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)



@login_required

@band_required

def integrantes_pdf_view(request, band_slug):

    band = get_object_or_404(Band, slug=band_slug)



    ids_param = request.GET.get('ids', '')

    if ids_param:

        ids_list = [int(id) for id in ids_param.split(',') if id.isdigit()]

        integrantes = Integrante.objects.filter(band=band, id__in=ids_list)

    else:

        integrantes = Integrante.objects.none()



    columns_param = request.GET.get('columns', 'role,category,cpf,vehicle,birth_date,miles_number')

    columns = columns_param.split(',') if columns_param else []



    context = {

        'band': band,

        'integrantes': integrantes,

        'columns': columns,

    }

    return render(request, 'core/integrantes_pdf.html', context)







from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from functools import wraps

from core.models import Band, RoomList, Room, Show
from core.forms import RoomListSelectShowForm, RoomListForm, RoomForm, ActionConfirmForm
from core.services import room_list_services
from core.services.room_list_services import RoomListServiceError, RoomListNotFoundError, BandAccessDeniedError

def room_list_produtor_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, band_slug, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login', band_slug=band_slug)

        band = get_object_or_404(Band, slug=band_slug)
        request.band = band

        if not request.user.is_active:
            raise PermissionDenied("Usuário inativo.")
        if getattr(request.user, 'band_id', None) != request.band.id:
            raise PermissionDenied("Acesso negado à banda.")
        if not request.user.is_produtor():
            raise PermissionDenied("Acesso restrito a produtores.")

        return view_func(request, band_slug, *args, **kwargs)
    return _wrapped_view

@room_list_produtor_required
def room_list_index(request, band_slug):
    room_lists = RoomList.objects.filter(band=request.band).select_related('show').order_by('show__date')
    return render(request, 'core/room_list/room_list_index.html', {
        'band': request.band,
        'room_lists': room_lists
    })

@room_list_produtor_required
def room_list_select_show(request, band_slug):
    if request.method == 'POST':
        form = RoomListSelectShowForm(band=request.band, data=request.POST)
        if form.is_valid():
            show = form.cleaned_data['show_id']
            return redirect('room_list_create', band_slug=band_slug, show_id=show.id)
    else:
        form = RoomListSelectShowForm(band=request.band)

    return render(request, 'core/room_list/room_list_select_show.html', {
        'band': request.band,
        'form': form
    })

@room_list_produtor_required
def room_list_create(request, band_slug, show_id):
    show = get_object_or_404(Show, id=show_id, band=request.band)

    if request.method == 'POST':
        room_list_instance = RoomList(show=show, band=request.band)
        form = RoomListForm(request.POST, instance=room_list_instance)
        if form.is_valid():
            try:
                room_list = room_list_services.create_room_list(
                    show_id=show.id,
                    band_id=request.band.id,
                    user=request.user,
                    **form.cleaned_data
                )
                messages.success(request, "Room List criada com sucesso.")
                return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = RoomListForm()

    return render(request, 'core/room_list/room_list_form.html', {
        'band': request.band,
        'form': form,
        'show': show,
        'action': 'Criar'
    })

@room_list_produtor_required
def room_list_edit(request, band_slug, pk):
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
    except RoomListNotFoundError:
        raise Http404("Room List não encontrada.")

    if request.method == 'POST':
        form = RoomListForm(request.POST, instance=room_list)
        if form.is_valid():
            try:
                room_list_services.update_room_list(
                    room_list_id=room_list.id,
                    user=request.user,
                    **form.cleaned_data
                )
                messages.success(request, "Room List atualizada com sucesso.")
                return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = RoomListForm(instance=room_list)

    return render(request, 'core/room_list/room_list_form.html', {
        'band': request.band,
        'form': form,
        'room_list': room_list,
        'action': 'Editar'
    })

@band_required
def room_list_manage(request, band_slug, pk):
    is_produtor = request.user.is_produtor()
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
    except RoomListNotFoundError:
        raise Http404("Room List não encontrada.")

    if not is_produtor and room_list.status == "RASCUNHO":
        raise PermissionDenied("Acesso restrito.")
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
    except RoomListNotFoundError:
        raise Http404("Room List não encontrada.")

    rooms = room_list.rooms.all().order_by('order', 'id')
    participants = room_list.participants.all()
    from core.models import Integrante
    active_integrantes = Integrante.objects.filter(band=request.band, is_active=True).order_by('name')

    return render(request, 'core/room_list/room_list_manage.html', {
        'active_integrantes': active_integrantes,
        'band': request.band,
        'room_list': room_list,
        'rooms': rooms,
        'participants': participants,
        'is_produtor': is_produtor,
    })

@room_list_produtor_required
def room_list_room_create(request, band_slug, pk):
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
    except RoomListNotFoundError:
        raise Http404("Room List não encontrada.")

    if request.method == 'POST':
        form = RoomForm(request.POST)
        if form.is_valid():
            try:
                data = form.cleaned_data.copy()
                room_list_services.create_room(
                    room_list_id=room_list.id,
                    room_type=data.pop('type'),
                    capacity=data.pop('capacity'),
                    number_or_name=data.pop('number_or_name'),
                    user=request.user,
                    **data
                )
                messages.success(request, "Quarto adicionado com sucesso.")
                return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = RoomForm()

    return render(request, 'core/room_list/room_form.html', {
        'band': request.band,
        'form': form,
        'room_list': room_list,
        'action': 'Adicionar'
    })

@room_list_produtor_required
def room_list_room_edit(request, band_slug, pk, room_id):
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
        room = room_list.rooms.get(id=room_id)
    except (RoomListNotFoundError, Room.DoesNotExist):
        raise Http404("Quarto ou Room List não encontrados.")

    if request.method == 'POST':
        form = RoomForm(request.POST, instance=room)
        if form.is_valid():
            try:
                room_list_services.update_room(
                    room_id=room.id,
                    room_list_id=room_list.id,
                    user=request.user,
                    **form.cleaned_data
                )
                messages.success(request, "Quarto atualizado com sucesso.")
                return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = RoomForm(instance=room)

    return render(request, 'core/room_list/room_form.html', {
        'band': request.band,
        'form': form,
        'room_list': room_list,
        'room': room,
        'action': 'Editar'
    })

@room_list_produtor_required
def room_list_room_delete(request, band_slug, pk, room_id):
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
        room = room_list.rooms.get(id=room_id)
    except (RoomListNotFoundError, Room.DoesNotExist):
        raise Http404("Quarto ou Room List não encontrados.")

    if request.method == 'POST':
        form = ActionConfirmForm(request.POST)
        if form.is_valid():
            try:
                room_list_services.delete_room(room.id, room_list.id, request.user)
                messages.success(request, "Quarto removido com sucesso.")
                return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = ActionConfirmForm()

    return render(request, 'core/room_list/room_confirm_delete.html', {
        'band': request.band,
        'room_list': room_list,
        'room': room,
        'form': form
    })

@room_list_produtor_required
def room_list_delete(request, band_slug, pk):
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
    except RoomListNotFoundError:
        raise Http404("Room List não encontrada.")

    if request.method == 'POST':
        form = ActionConfirmForm(request.POST)
        if form.is_valid():
            try:
                room_list_services.delete_room_list(room_list.id, request.user)
                messages.success(request, "Room List excluída com sucesso.")
                return redirect('room_list_index', band_slug=band_slug)
            except Exception as e:
                messages.error(request, str(e))

    return redirect('room_list_index', band_slug=band_slug)


from django.views.decorators.http import require_POST
from django.http import JsonResponse
import json

@room_list_produtor_required
@require_POST
def room_list_sync(request, band_slug, pk):
    is_fetch = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('Content-Type') == 'application/json' or request.headers.get('Accept') == 'application/json'

    if request.method != 'POST':
        return redirect('room_list_manage', band_slug=band_slug, pk=pk)

    integrantes_ids = request.POST.getlist('integrantes')
    if not integrantes_ids:
        if is_fetch:
            return JsonResponse({'status': 'error', 'message': 'Nenhum integrante selecionado.'}, status=400)
        messages.info(request, 'Nenhum integrante foi selecionado para adicionar.')
        return redirect('room_list_manage', band_slug=band_slug, pk=pk)

    try:
        _, added = room_list_services.add_integrantes_to_room_list(pk, request.user, integrantes_ids)
        msg = f'{added} integrante(s) adicionado(s) com sucesso.'
        if is_fetch:
            return JsonResponse({'status': 'success', 'message': msg})
        messages.success(request, msg)
        return redirect('room_list_manage', band_slug=band_slug, pk=pk)
    except Exception as e:
        if is_fetch:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        messages.error(request, f'Erro ao adicionar integrantes: {str(e)}')
        return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
def room_list_allocate(request, band_slug, pk, participant_id):
    room_id = request.POST.get('room_id')
    if room_id:
        room_id = int(room_id)
    is_fetch = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('Content-Type') == 'application/json'
    try:
        room_list_services.assign_participant_to_room(participant_id, room_id, request.user)
        if is_fetch:
            return JsonResponse({'status': 'success'})
        messages.success(request, 'Participante alocado.')
    except Exception as e:
        if is_fetch:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        messages.error(request, str(e))
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
def room_list_unassign(request, band_slug, pk, participant_id):
    is_fetch = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('Content-Type') == 'application/json'
    try:
        room_list_services.unassign_participant(participant_id, request.user)
        if is_fetch:
            return JsonResponse({'status': 'success'})
        messages.success(request, 'Participante desalocado.')
    except Exception as e:
        if is_fetch:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
        messages.error(request, str(e))
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
def room_list_publish(request, band_slug, pk):
    try:
        room_list_services.publish_room_list(pk, request.user)
        messages.success(request, 'Room List publicada com sucesso.')
    except (RoomListNotFoundError, BandAccessDeniedError) as e:
        raise Http404(str(e))
    except Exception as e:
        messages.error(request, str(e))
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
def room_list_reopen(request, band_slug, pk):
    try:
        room_list_services.reopen_room_list(pk, request.user)
        messages.success(request, 'Room List reaberta para edição.')
    except (RoomListNotFoundError, BandAccessDeniedError) as e:
        raise Http404(str(e))
    except Exception as e:
        messages.error(request, str(e))
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
def room_list_reactivate(request, band_slug, pk):
    try:
        room_list_services.reactivate_room_list(pk, request.user)
        messages.success(request, 'Room List reativada.')
    except (RoomListNotFoundError, BandAccessDeniedError) as e:
        raise Http404(str(e))
    except Exception as e:
        messages.error(request, str(e))
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
def room_list_archive(request, band_slug, pk):
    try:
        room_list_services.archive_room_list(pk, request.user)
        messages.success(request, 'Room List arquivada.')
    except (RoomListNotFoundError, BandAccessDeniedError) as e:
        raise Http404(str(e))
    except Exception as e:
        messages.error(request, str(e))
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
def room_list_mark_sent(request, band_slug, pk):
    try:
        room_list_services.mark_room_list_as_sent(pk, request.user)
        messages.success(request, 'Room List marcada como enviada.')
    except (RoomListNotFoundError, BandAccessDeniedError) as e:
        raise Http404(str(e))
    except Exception as e:
        messages.error(request, str(e))
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
def room_list_apply_template(request, band_slug, pk):
    try:
        room_list_services.apply_template_to_room_list(pk, request.user)
        messages.success(request, 'Modelo aplicado com sucesso.')
    except (RoomListNotFoundError, BandAccessDeniedError) as e:
        raise Http404(str(e))
    except Exception as e:
        messages.error(request, str(e))
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
def lodging_template_manage(request, band_slug):
    band = request.band
    from core.models import LodgingTemplate
    from core.forms import TemplateRoomFormSet

    template = LodgingTemplate.objects.filter(band=band).first()

    if request.method == 'POST':
        if request.POST.get('action') == 'delete':
            room_list_services.delete_lodging_template(band.id, request.user)
            messages.success(request, "Modelo excluído.")
            return redirect('lodging_template_manage', band_slug=band_slug)

        formset = TemplateRoomFormSet(request.POST, instance=template, band=band)
        if formset.is_valid():
            rooms_payload = []
            for form in formset:
                if form.cleaned_data and not form.cleaned_data.get('DELETE', False):
                    room_type = form.cleaned_data.get('type')
                    capacity = form.cleaned_data.get('capacity')
                    beds_config = form.cleaned_data.get('beds_config', '')
                    has_ac = form.cleaned_data.get('has_ac', True)
                    order = form.cleaned_data.get('order', 0)
                    participants = form.cleaned_data.get('participants', [])

                    rooms_payload.append({
                        'type': room_type,
                        'capacity': capacity,
                        'order': order,
                        'beds_config': beds_config,
                        'has_ac': has_ac,
                        'participants': [p.id for p in participants]
                    })
            try:
                room_list_services.create_or_replace_lodging_template(band.id, rooms_payload, request.user)
                messages.success(request, 'Modelo salvo com sucesso.')
                return redirect('lodging_template_manage', band_slug=band_slug)
            except Exception as e:
                messages.error(request, str(e))
        else:
            messages.error(request, "Erros no formulário. Verifique os campos.")
    else:
        formset = TemplateRoomFormSet(instance=template, band=band)

    return render(request, 'core/room_list/lodging_template_manage.html', {
        'band': request.band,
        'template': template,
        'formset': formset
    })


@login_required
@band_required
def integrantes_pdf_view(request, band_slug):
    band = get_object_or_404(Band, slug=band_slug)

    ids_param = request.GET.get('ids', '')
    if ids_param:
        ids_list = [int(id) for id in ids_param.split(',') if id.isdigit()]
        integrantes = Integrante.objects.filter(band=band, id__in=ids_list)
    else:
        integrantes = Integrante.objects.none()

    columns_param = request.GET.get('columns', 'role,category,cpf,vehicle,birth_date,miles_number')
    columns = columns_param.split(',') if columns_param else []

    context = {
        'band': band,
        'integrantes': integrantes,
        'columns': columns,
    }
    return render(request, 'core/integrantes_pdf.html', context)

@login_required
@band_required
def room_list_pdf_view(request, band_slug, pk):
    from core.models import RoomList
    from django.core.exceptions import PermissionDenied
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from xhtml2pdf import pisa
    import io

    try:
        room_list = RoomList.objects.select_related('show', 'band').prefetch_related(
            'rooms__participants'
        ).get(pk=pk, show__band=request.band)
    except RoomList.DoesNotExist:
        raise Http404("Room List não encontrada.")

    is_produtor = request.user.is_produtor()
    if not is_produtor and room_list.status == RoomList.StatusChoices.RASCUNHO:
        raise PermissionDenied("Acesso restrito. Room List em rascunho.")

    context = {
        'band': request.band,
        'room_list': room_list,
        'rooms': room_list.rooms.all(),
        'participants': room_list.participants.filter(room__isnull=False),
        'unallocated': room_list.participants.filter(room__isnull=True),
    }
    html_string = render_to_string('core/room_list/room_list_pdf.html', context, request=request)
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html_string.encode("UTF-8")), result)
    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="room_list.pdf"'
        response['Cache-Control'] = 'private, no-store'
        return response
    return HttpResponse('Erro ao gerar PDF', status=500)


@login_required
@band_required
def room_list_hotel_pdf_view(request, band_slug, pk):
    from core.models import RoomList
    from django.core.exceptions import PermissionDenied
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from xhtml2pdf import pisa
    import io

    is_produtor = request.user.is_produtor()
    if not is_produtor:
        raise PermissionDenied("Acesso exclusivo para produtores.")

    try:
        room_list = RoomList.objects.select_related('show', 'band').prefetch_related(
            'rooms__participants'
        ).get(pk=pk, show__band=request.band)
    except RoomList.DoesNotExist:
        raise Http404("Room List não encontrada.")

    context = {
        'band': request.band,
        'room_list': room_list,
        'rooms': room_list.rooms.all(),
        'participants': room_list.participants.filter(room__isnull=False),
        'unallocated': room_list.participants.filter(room__isnull=True),
        'total_rooms': room_list.rooms.count(),
        'total_participants': room_list.participants.count(),
        'is_hotel_pdf': True,
    }
    html_string = render_to_string('core/room_list/room_list_pdf.html', context, request=request)
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html_string.encode("UTF-8")), result)
    if not pdf.err:
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="room_list.pdf"'
        response['Cache-Control'] = 'private, no-store'
        response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response
    return HttpResponse('Erro ao gerar PDF', status=500)


@login_required
@band_required
@require_POST
def delete_room_view(request, band_slug, room_pk):
    from core.models import Room, RoomList
    from django.core.exceptions import PermissionDenied

    is_produtor = request.user.is_produtor()
    if not is_produtor:
        raise PermissionDenied("Acesso exclusivo para produtores.")

    room = get_object_or_404(Room, pk=room_pk, room_list__show__band=request.band)

    if room.room_list.status != RoomList.StatusChoices.RASCUNHO:
        messages.error(request, "Não é possível excluir quartos de uma Room List que não está em Rascunho.")
        return redirect('room_list_manage', band_slug=band_slug, pk=room.room_list.pk)

    room.delete()
    messages.success(request, "Quarto excluído com sucesso. Os ocupantes foram movidos para Não Alocados.")
    return redirect('room_list_manage', band_slug=band_slug, pk=room.room_list.pk)

@room_list_produtor_required
def room_list_participant_delete(request, band_slug, pk, participant_id):
    if request.method != 'POST':
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Método não permitido.')
    
    from django.shortcuts import get_object_or_404, redirect
    from django.contrib import messages
    from core.models import RoomList, RoomListParticipant
    
    room_list = get_object_or_404(RoomList, pk=pk, band__slug=band_slug)
    if room_list.status != 'RASCUNHO':
        messages.error(request, 'Não é possível excluir integrantes de uma Room List que não está em rascunho.')
        return redirect('room_list_manage', band_slug=band_slug, pk=pk)
        
    participant = get_object_or_404(RoomListParticipant, pk=participant_id, room_list=room_list)
    participant.delete()
    
    messages.success(request, f'Integrante {participant.snapshot_name} removido da lista com sucesso.')
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)


from django.utils import timezone


@login_required
@band_required
def band_notices_index(request, band_slug):
    if not request.user.is_produtor():
        messages.error(request, 'Acesso restrito.')
        return redirect('dashboard', band_slug=band_slug)
        
    notices = request.band.notices.all()
    from core.forms import BandNoticeForm
    form = BandNoticeForm()
    
    return render(request, 'core/notices/band_notices_index.html', {'notices': notices, 'band': request.band, 'form': form})

@login_required
@band_required
def band_notices_create(request, band_slug):
    if not request.user.is_produtor():
        return redirect('dashboard', band_slug=band_slug)
        
    if request.method == 'POST':
        from core.forms import BandNoticeForm
        form = BandNoticeForm(request.POST)
        if form.is_valid():
            notice = form.save(commit=False)
            notice.band = request.band
            notice.created_by = request.user
            notice.scheduled_at = form.cleaned_data['scheduled_at']
            
            if form.cleaned_data.get('fire_now'):
                from django.utils import timezone
                from core.services.notification_services import send_push_notification_to_band
                notice.sent_at = timezone.now()
                notice.save()
                try:
                    send_push_notification_to_band(
                        band=notice.band,
                        title='Aviso da Produção',
                        message=notice.message,
                        exclude_user=notice.created_by,
                        url=f'/{notice.band.slug}/painel/'
                    )
                except Exception as e:
                    pass
                messages.success(request, 'Aviso disparado com sucesso!')
            else:
                notice.save()
                messages.success(request, 'Aviso agendado com sucesso!')
                
            return redirect('band_notices_index', band_slug=band_slug)
        else:
            notices = request.band.notices.all()
            return render(request, 'core/notices/band_notices_index.html', {'notices': notices, 'band': request.band, 'form': form})
            
    return redirect('band_notices_index', band_slug=band_slug)

@login_required
@band_required
def band_notices_edit(request, band_slug, pk):
    if not request.user.is_produtor():
        return redirect('dashboard', band_slug=band_slug)
        
    from core.models import BandNotice
    from core.forms import BandNoticeForm
    from django.shortcuts import get_object_or_404
    
    notice = get_object_or_404(BandNotice, pk=pk, band=request.band)
    
    if request.method == 'POST':
        form = BandNoticeForm(request.POST, instance=notice)
        if form.is_valid():
            notice = form.save(commit=False)
            notice.scheduled_at = form.cleaned_data['scheduled_at']
            notice.save()
            messages.success(request, 'Aviso atualizado com sucesso!')
            return redirect('band_notices_index', band_slug=band_slug)
    else:
        from django.utils import timezone
        local_time = timezone.localtime(notice.scheduled_at)
        initial = {'date': local_time.date(), 'time': local_time.time()}
        form = BandNoticeForm(instance=notice, initial=initial)
        
    return render(request, 'core/notices/band_notices_form.html', {'form': form, 'band': request.band, 'notice': notice})

@login_required
@band_required
def band_notices_delete(request, band_slug, pk):
    if not request.user.is_produtor():
        return redirect('dashboard', band_slug=band_slug)
        
    if request.method != 'POST':
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied('Método não permitido.')
        
    from core.models import BandNotice
    from django.shortcuts import get_object_or_404
    
    notice = get_object_or_404(BandNotice, pk=pk, band=request.band)
    notice.delete()
    messages.success(request, 'Aviso excluído.')
    return redirect('band_notices_index', band_slug=band_slug)

