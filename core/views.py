from django.views.decorators.http import require_POST
import logging
import datetime
import base64
import os

logger = logging.getLogger(__name__)

def get_image_base64(image_field):
    if not image_field or not image_field.name:
        return ""
    try:
        if hasattr(image_field, 'path') and os.path.exists(image_field.path):
            with open(image_field.path, 'rb') as f:
                return "data:image/png;base64," + base64.b64encode(f.read()).decode('utf-8')
    except Exception:
        pass
    return ""

def get_static_image_base64(relative_path):
    try:
        from django.conf import settings
        full_path = os.path.join(settings.BASE_DIR, 'core', 'static', 'core', relative_path)
        if os.path.exists(full_path):
            with open(full_path, 'rb') as f:
                return "data:image/png;base64," + base64.b64encode(f.read()).decode('utf-8')
    except Exception:
        pass
    return ""

from .decorators import advanced_plan_required
from django.shortcuts import render, get_object_or_404, redirect

from django.db import transaction, models
from django.db.models import Sum, Case, When, IntegerField
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib.auth import logout
from django.contrib.auth import views as auth_views
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from functools import wraps
from django.http import HttpResponseForbidden, HttpResponseNotAllowed, JsonResponse

from .models import Show, FinancialReceipt, Band, User, Contact, ContractDocument, ShowPayment, ShowTeamCost, BandDashboardPendingItem, AdministrativeBandNotice, RiderDocument

from .forms import FinancialReceiptForm, UserForm, UserEditForm, ContactForm, ShowForm, ContractDocumentFormSet, FinancialReceiptFormSet, ShowPaymentForm, ShowTeamCostForm, ContractDocumentForm, RiderDocumentForm

from decimal import Decimal



def landing_page_view(request):

    """

    Landing page principal de vendas do Backstage Pro.

    """

    from .models import LandingPageBandLogo, SystemSettings

    landing_band_logos = LandingPageBandLogo.objects.filter(is_active=True)
    settings_obj = SystemSettings.get_settings()

    basic_monthly = float(settings_obj.plan_basic_monthly or Decimal('19.90'))
    basic_annual = float(settings_obj.plan_basic_annual or Decimal('199.90'))
    advanced_monthly = float(settings_obj.plan_advanced_monthly or Decimal('49.90'))
    advanced_annual = float(settings_obj.plan_advanced_annual or Decimal('499.90'))

    # Cálculos
    basic_equiv = basic_annual / 12.0
    basic_savings = (basic_monthly * 12.0) - basic_annual

    advanced_equiv = advanced_annual / 12.0
    advanced_savings = (advanced_monthly * 12.0) - advanced_annual

    plan_prices = {
        'basic_monthly': basic_monthly,
        'basic_annual': basic_annual,
        'basic_equiv': basic_equiv,
        'basic_savings': basic_savings,
        'advanced_monthly': advanced_monthly,
        'advanced_annual': advanced_annual,
        'advanced_equiv': advanced_equiv,
        'advanced_savings': advanced_savings,
    }

    context = {
        'landing_band_logos': landing_band_logos,
        'plan_prices': plan_prices,
    }

    return render(request, 'core/landing.html', context)



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

        # Restrição de acesso para assinaturas inativas/encerradas
        if not request.user.is_superuser:
            if not band.has_active_subscription:
                if view_func.__name__ not in ('minha_assinatura_view', 'band_logout'):
                    return redirect('minha_assinatura', band_slug=band.slug)

        request.band = band

        return view_func(request, band_slug, *args, **kwargs)

    return _wrapped_view





def band_root_redirect_view(request, band_slug):

    if request.user.is_authenticated:

        if request.user.is_superuser:

            return redirect('admin_painel:dashboard')

        if request.user.band:
            target_slug = request.user.band.slug
            if not request.user.band.has_active_subscription:
                return redirect('minha_assinatura', band_slug=target_slug)
            return redirect('dashboard', band_slug=target_slug)

    band = get_object_or_404(Band, slug=band_slug)
    if not band.has_active_subscription:
        return redirect('minha_assinatura', band_slug=band_slug)
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

                if not band.has_active_subscription:
                    return redirect('minha_assinatura', band_slug=band.slug)

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
            if not user.band.has_active_subscription:
                return reverse('minha_assinatura', kwargs={'band_slug': user.band.slug})
            return reverse('dashboard', kwargs={'band_slug': user.band.slug})

        band_slug = self.kwargs.get('band_slug')
        band = get_object_or_404(Band, slug=band_slug)
        if not band.has_active_subscription:
            return reverse('minha_assinatura', kwargs={'band_slug': band_slug})
        return reverse('dashboard', kwargs={'band_slug': band_slug})



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

    user_is_band_producer = request.user.band == band and request.user.role in ['PRODUTOR', 'EMPRESARIO']



    if user_is_band_producer:
        from django.db.models import Q, F

        total_users = User.objects.filter(band=band).count()

        total_contacts = Contact.objects.filter(band=band).count()



        if band.is_advanced:
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
        else:
            dashboard_pending_items = None
            pending_item_form = None



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
        'pendencias_bloqueadas': not band.is_advanced,
    }

    return render(request, 'core/dashboard.html', context)



@login_required

@band_required

@advanced_plan_required
def pending_list_view(request, band_slug):

    band = request.band



    user_can_manage_band = request.user.is_superuser or (request.user.band == band and request.user.is_produtor())

    if not user_can_manage_band:

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

    user_is_band_producer = request.user.is_superuser or (request.user.band == band and request.user.is_produtor())



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
        from django.contrib import messages
        from django.shortcuts import redirect
        messages.error(request, 'Você não tem permissão para exportar PDFs.')
        return redirect('calendario', band_slug=band_slug)

    from django.shortcuts import get_object_or_404, render
    from core.models import Show
    show = get_object_or_404(Show, pk=pk, band=request.band)

    try:
        from core.services.weather_services import get_weather_for_show
        weather = get_weather_for_show(show.city, show.date)
    except Exception:
        weather = None

    public_room_list_token = None
    if show.room_lists.exists():
        try:
            from django.core.signing import Signer
            public_room_list_token = Signer().sign(str(show.room_lists.first().id))
        except Exception:
            pass

    context = {
        'public_room_list_token': public_room_list_token,
        'show': show,
        'weather': weather,
        'request': request,
        'pdf_logo_base64': get_image_base64(request.band.logo),
    }
    return render(request, 'core/show_pdf.html', context)

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



    context = {
        'shows': shows,
        'band': request.band,
        'today': datetime.date.today(),
        'request': request,
        'pdf_logo_base64': get_image_base64(request.band.logo),
    }
    return render(request, 'core/agenda_pdf.html', context)



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
    subscription = band.subscriptions.filter(is_deleted=False).order_by(
        models.Case(
            models.When(status='ATIVO', then=0),
            default=1,
            output_field=models.IntegerField(),
        ),
        '-created_at'
    ).first()

    context = {'band': band, 'subscription': subscription}
    return render(request, 'core/relatorios_index.html', context)


@login_required
@band_required
def minha_assinatura_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores têm acesso aos relatórios.")

    band = get_object_or_404(Band, slug=band_slug)

    # 1. Selecionar a assinatura principal de forma determinística
    # Prioridade: não deletada, status ATIVO, mais recente por created_at
    active_subs = band.subscriptions.filter(is_deleted=False, status='ATIVO').order_by('-created_at')
    if active_subs.count() > 1:
        logger.warning(
            "Ambiguidade: Band '%s' (slug=%s) possui %d assinaturas ATIVAS. Exibindo a mais recente (ID=%d).",
            band.name, band.slug, active_subs.count(), active_subs.first().id
        )

    subscription = active_subs.first()
    if not subscription:
        subscription = band.subscriptions.filter(is_deleted=False).order_by('-created_at').first()

    # Processar ações solicitadas pelo produtor
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'cancel_subscription':
            if subscription and subscription.status == 'ATIVO' and not subscription.cancel_at_period_end:
                from django.utils import timezone
                subscription.cancel_at_period_end = True
                subscription.auto_renew = False
                subscription.canceled_at = timezone.now()
                subscription.save(update_fields=['cancel_at_period_end', 'auto_renew', 'canceled_at', 'updated_at'])

                # Log para auditoria
                logger.info(
                    "Assinatura %d da banda '%s' marcada para cancelamento ao fim do período pelo usuário %s.",
                    subscription.id, band.slug, request.user.username
                )
                messages.success(request, "Cancelamento confirmado com sucesso. O seu acesso permanecerá ativo até o fim do período contratado.")
                return redirect('minha_assinatura', band_slug=band.slug)

        elif action == 'reactivate_subscription':
            if subscription and subscription.status == 'ATIVO' and subscription.cancel_at_period_end:
                subscription.cancel_at_period_end = False
                subscription.auto_renew = True
                subscription.canceled_at = None
                subscription.save(update_fields=['cancel_at_period_end', 'auto_renew', 'canceled_at', 'updated_at'])

                # Log para auditoria
                logger.info(
                    "Assinatura %d da banda '%s' reativada pelo usuário %s.",
                    subscription.id, band.slug, request.user.username
                )
                messages.success(request, "Assinatura reativada com sucesso! A renovação automática continuará normalmente.")
                return redirect('minha_assinatura', band_slug=band.slug)

    # 2. Histórico de cobranças (BillingRecord) ordenado pelo mais recente
    faturas = []
    if subscription:
        faturas = subscription.records.all().order_by('-due_date', '-created_at')
    else:
        # Fallback: se houver faturas da banda sem subscription ativa
        faturas = band.billing_records.all().order_by('-due_date', '-created_at')

    # 3. Nomes amigáveis calculados para o resumo da assinatura
    plan_display = None
    cycle_display = None
    payment_method_display = None
    status_display = None
    can_cancel = False
    can_reactivate = False
    can_resubscribe = False
    can_regularize = False
    alert_overdue_tolerance = False
    alert_suspended = False
    overdue_limit_date = None

    if subscription:
        # Sincronizar encerramento automático se aplicável
        subscription.check_and_sync_auto_expiration()
        subscription.refresh_from_db()

        # Plano (exibir estritamente Básico ou Avançado)
        p_name = (subscription.plan_name or '').strip().upper()
        if 'BASICO' in p_name or 'BÁSICO' in p_name:
            plan_display = 'Básico'
        elif 'AVANCADO' in p_name or 'AVANÇADO' in p_name:
            plan_display = 'Avançado'
        else:
            plan_display = 'Básico' if getattr(band, 'is_basic', True) else 'Avançado'

        # Ciclo
        c_name = (subscription.billing_cycle or '').strip().upper()
        if c_name == 'MENSAL':
            cycle_display = 'Mensal'
        elif c_name == 'SEMESTRAL':
            cycle_display = 'Semestral'
        elif c_name == 'ANUAL':
            cycle_display = 'Anual'
        elif c_name == 'PERSONALIZADO':
            cycle_display = 'Personalizado'
        else:
            cycle_display = subscription.get_billing_cycle_display() if hasattr(subscription, 'get_billing_cycle_display') else subscription.billing_cycle

        # Forma de pagamento
        pm_pref = (subscription.payment_method_preference or '').strip().upper()
        if pm_pref == 'CARTAO' or pm_pref == 'CARTÃO':
            payment_method_display = 'Cartão de crédito'
        elif pm_pref == 'PIX':
            payment_method_display = 'Pix'
        elif pm_pref == 'BOLETO':
            payment_method_display = 'Boleto'
        elif pm_pref == 'TRANSFERENCIA' or pm_pref == 'TRANSFERÊNCIA':
            payment_method_display = 'Transferência'
        elif pm_pref == 'DINHEIRO':
            payment_method_display = 'Dinheiro'
        else:
            payment_method_display = subscription.get_payment_method_preference_display() if hasattr(subscription, 'get_payment_method_preference_display') else (subscription.payment_method_preference or '-')

        # Status e Inadimplência
        st = (subscription.status or '').strip().upper()

        if st == 'ATIVO':
            if subscription.is_financially_suspended:
                status_display = 'Suspensa'
                alert_suspended = True
                can_regularize = True
            elif subscription.is_overdue_tolerance:
                status_display = 'Pagamento em atraso'
                alert_overdue_tolerance = True
                if subscription.next_due_date:
                    from datetime import timedelta
                    overdue_limit_date = subscription.next_due_date + timedelta(days=5)
            else:
                status_display = 'Ativo'
        elif st == 'DESATIVADO':
            status_display = 'Inativo'
            can_resubscribe = True
        else:
            status_display = subscription.get_status_display() if hasattr(subscription, 'get_status_display') else subscription.status
            can_resubscribe = True

        # Estados dos botões de ação para assinaturas ativas não suspensas:
        if subscription.status == 'ATIVO' and not subscription.is_financially_suspended:
            if subscription.cancel_at_period_end:
                can_reactivate = True
            else:
                can_cancel = True
    else:
        can_resubscribe = True

    context = {
        'band': band,
        'subscription': subscription,
        'faturas': faturas,
        'plan_display': plan_display,
        'cycle_display': cycle_display,
        'payment_method_display': payment_method_display,
        'status_display': status_display,
        'alert_overdue_tolerance': alert_overdue_tolerance,
        'alert_suspended': alert_suspended,
        'overdue_limit_date': overdue_limit_date,
        'can_cancel': can_cancel,
        'can_reactivate': can_reactivate,
        'can_resubscribe': can_resubscribe,
        'can_regularize': can_regularize,
    }

    return render(request, 'core/minha_assinatura.html', context)



@login_required

@band_required

@advanced_plan_required
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
@advanced_plan_required
def commercial_index_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores têm acesso ao módulo Comercial.")

    band = request.band
    from core.models import CommercialProposal, CommercialProposalDocument
    from core.forms import CommercialProposalForm
    from django.db.models import F

    # Filtros da URL
    q_name = request.GET.get('name', '').strip()
    q_start_date = (request.GET.get('date') or request.GET.get('start_date') or '').strip()
    q_end_date = request.GET.get('end_date', '').strip()
    q_phase = request.GET.get('phase', '').strip()
    q_origin = request.GET.get('origin', '').strip()

    qs = CommercialProposal.objects.filter(band=band).select_related('show').prefetch_related('documents')

    if q_name:
        qs = qs.filter(name__icontains=q_name)
    if q_start_date:
        try:
            qs = qs.filter(date__gte=q_start_date)
        except ValueError:
            pass
    if q_end_date:
        try:
            qs = qs.filter(date__lte=q_end_date)
        except ValueError:
            pass
    if q_phase and q_phase != 'TODAS':
        qs = qs.filter(phase=q_phase)
    if q_origin:
        qs = qs.filter(origin__icontains=q_origin)

    # Ordenação cronológica com horário nulo no final
    qs = qs.order_by('date', F('time').asc(nulls_last=True), 'id')

    proposals_orcamento = qs.filter(phase=CommercialProposal.Phase.RESERVA)
    proposals_fechados = qs.filter(phase=CommercialProposal.Phase.FECHADO)
    proposals_desistencias = qs.filter(phase=CommercialProposal.Phase.DESISTENCIA)

    count_orcamento = proposals_orcamento.count()
    count_fechados = proposals_fechados.count()
    count_desistencias = proposals_desistencias.count()

    form = CommercialProposalForm()

    context = {
        'band': band,
        'proposals_orcamento': proposals_orcamento,
        'proposals_fechados': proposals_fechados,
        'proposals_desistencias': proposals_desistencias,
        'count_orcamento': count_orcamento,
        'count_fechados': count_fechados,
        'count_desistencias': count_desistencias,
        'form': form,
    }
    return render(request, 'core/comercial/comercial_index.html', context)


@login_required
@band_required
@advanced_plan_required
def commercial_save_view(request, band_slug, pk=None):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem cadastrar ou editar orçamentos.")

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    band = request.band
    from core.models import CommercialProposal, CommercialProposalDocument, Show
    from core.forms import CommercialProposalForm
    from core.file_policy import validate_file_size_and_type
    from core.services.show_notifications import schedule_show_notifications
    from django.db import transaction
    from django.core.exceptions import ValidationError

    proposal = None
    if pk:
        proposal = get_object_or_404(CommercialProposal, pk=pk, band=band)

    form = CommercialProposalForm(request.POST, instance=proposal)
    if not form.is_valid():
        from django.http import JsonResponse
        errors = {field: [str(e) for e in errs] for field, errs in form.errors.items()}
        return JsonResponse({'ok': False, 'errors': errors}, status=400)

    # Validação de anexos antes de salvar
    uploaded_files = request.FILES.getlist('documents')
    for f in uploaded_files:
        try:
            validate_file_size_and_type(f)
        except ValidationError as ve:
            from django.http import JsonResponse
            return JsonResponse({'ok': False, 'errors': {'documents': [str(ve.message)]}}, status=400)

    with transaction.atomic():
        is_new_proposal = proposal is None
        proposal = form.save(commit=False)
        proposal.band = band
        if is_new_proposal:
            proposal.created_by = request.user
        proposal.save()

        # Sincronização atômica com o model Show vinculado
        old_show = None
        new_show = None
        is_show_creation = False

        if proposal.phase in [CommercialProposal.Phase.RESERVA, CommercialProposal.Phase.FECHADO]:
            target_status = 'CONFIRMADO' if proposal.phase == CommercialProposal.Phase.FECHADO else 'PRE_RESERVADO'
            if proposal.show:
                old_show = Show.objects.select_for_update().get(pk=proposal.show.id)
                old_show_snapshot = Show(
                    id=old_show.id,
                    band=old_show.band,
                    title=old_show.title,
                    date=old_show.date,
                    show_time=old_show.show_time,
                    status=old_show.status,
                    fee=old_show.fee,
                    venue=old_show.venue,
                    notification_revision=old_show.notification_revision
                )
                new_show = old_show
                new_show.title = proposal.name
                new_show.date = proposal.date
                new_show.show_time = proposal.time
                new_show.status = target_status
                new_show.fee = proposal.fee
                new_show.contractor_phone = proposal.contact
                if proposal.phase == CommercialProposal.Phase.FECHADO and proposal.location:
                    new_show.venue = proposal.location
                new_show.save()
                schedule_show_notifications(old_show=old_show_snapshot, new_show=new_show, actor=request.user, is_creation=False)
            else:
                is_show_creation = True
                new_show = Show.objects.create(
                    band=band,
                    title=proposal.name,
                    date=proposal.date,
                    show_time=proposal.time,
                    status=target_status,
                    fee=proposal.fee,
                    venue=proposal.location if (proposal.phase == CommercialProposal.Phase.FECHADO and proposal.location) else None,
                    contractor_phone=proposal.contact
                )
                proposal.show = new_show
                proposal.save(update_fields=['show'])
                schedule_show_notifications(old_show=None, new_show=new_show, actor=request.user, is_creation=True)

        elif proposal.phase == CommercialProposal.Phase.DESISTENCIA:
            if proposal.show:
                old_show = Show.objects.select_for_update().get(pk=proposal.show.id)
                if old_show.status != 'CANCELADO':
                    old_show_snapshot = Show(
                        id=old_show.id,
                        band=old_show.band,
                        title=old_show.title,
                        date=old_show.date,
                        show_time=old_show.show_time,
                        status=old_show.status,
                        fee=old_show.fee,
                        venue=old_show.venue,
                        notification_revision=old_show.notification_revision
                    )
                    old_show.status = 'CANCELADO'
                    old_show.title = proposal.name
                    old_show.date = proposal.date
                    old_show.show_time = proposal.time
                    old_show.fee = proposal.fee
                    old_show.save()
                    schedule_show_notifications(old_show=old_show_snapshot, new_show=old_show, actor=request.user, is_creation=False)

        # Salva os arquivos anexados
        for f in uploaded_files:
            CommercialProposalDocument.objects.create(
                proposal=proposal,
                file=f,
                original_name=f.name,
                uploaded_by=request.user
            )

    from django.http import JsonResponse
    msg = "Solicitação atualizada com sucesso!" if not is_new_proposal else "Solicitação cadastrada com sucesso!"
    messages.success(request, msg)
    return JsonResponse({'ok': True, 'redirect_url': reverse('commercial_index', args=[band.slug])})


@login_required
@band_required
@advanced_plan_required
def commercial_pdf_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem exportar a agenda comercial.")

    band = request.band
    from core.models import CommercialProposal
    from django.db.models import F
    from datetime import datetime

    data_inicio = request.GET.get('data_inicio', '').strip()
    data_fim = request.GET.get('data_fim', '').strip()
    selected_phases = request.GET.getlist('phase')

    # Validação: Se nenhuma fase foi selecionada
    if not selected_phases:
        messages.error(request, "Selecione ao menos um status para gerar o PDF.")
        return redirect('commercial_index', band_slug=band.slug)

    # Mapeamento seguro de fases
    phase_filter_values = []
    for ph in selected_phases:
        if ph in ['ORCAMENTO', 'RESERVA']:
            phase_filter_values.append(CommercialProposal.Phase.RESERVA)
        elif ph == 'FECHADO':
            phase_filter_values.append(CommercialProposal.Phase.FECHADO)
        elif ph == 'DESISTENCIA':
            phase_filter_values.append(CommercialProposal.Phase.DESISTENCIA)

    if not phase_filter_values:
        messages.error(request, "Selecione ao menos um status para gerar o PDF.")
        return redirect('commercial_index', band_slug=band.slug)

    qs = CommercialProposal.objects.filter(band=band, phase__in=phase_filter_values)

    if data_inicio:
        try:
            inicio = datetime.strptime(data_inicio, '%Y-%m-%d').date()
            qs = qs.filter(date__gte=inicio)
        except ValueError:
            pass

    if data_fim:
        try:
            fim = datetime.strptime(data_fim, '%Y-%m-%d').date()
            qs = qs.filter(date__lte=fim)
        except ValueError:
            pass

    # Ordenação cronológica por data e hora
    proposals = qs.order_by('date', F('time').asc(nulls_last=True), 'id')

    # Se nenhum resultado for retornado
    if not proposals.exists():
        messages.warning(request, "Nenhum registro comercial encontrado para os filtros selecionados.")
        return redirect('commercial_index', band_slug=band.slug)

    # Estruturação com agrupamento hierárquico determinístico: ANO -> MÊS (em Português)
    MESES_PT_BR = {
        1: 'JANEIRO',
        2: 'FEVEREIRO',
        3: 'MARÇO',
        4: 'ABRIL',
        5: 'MAIO',
        6: 'JUNHO',
        7: 'JULHO',
        8: 'AGOSTO',
        9: 'SETEMBRO',
        10: 'OUTUBRO',
        11: 'NOVEMBRO',
        12: 'DEZEMBRO'
    }

    from collections import defaultdict
    years_dict = defaultdict(lambda: defaultdict(list))

    for prop in proposals:
        ano = prop.date.year
        mes = prop.date.month
        years_dict[ano][mes].append(prop)

    # Construir lista ordenada hierárquica final
    grouped_years = []
    for ano in sorted(years_dict.keys()):
        months_list = []
        for mes in sorted(years_dict[ano].keys()):
            months_list.append({
                'month_num': mes,
                'month_name': MESES_PT_BR.get(mes, f"MÊS {mes}"),
                'proposals': years_dict[ano][mes]
            })
        if months_list:
            grouped_years.append({
                'year': ano,
                'months': months_list
            })

    user_name = request.user.get_full_name() or request.user.username

    context = {
        'band': band,
        'grouped_years': grouped_years,
        'proposals': proposals,
        'count_fechados': proposals.filter(phase=CommercialProposal.Phase.FECHADO).count(),
        'count_desistencias': proposals.filter(phase=CommercialProposal.Phase.DESISTENCIA).count(),
        'pdf_logo_base64': get_image_base64(band.logo),
        'user_name': user_name,
    }
    return render(request, 'core/comercial/pdf_comercial.html', context)


@login_required
@band_required
@advanced_plan_required
def commercial_delete_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem excluir solicitações.")

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    band = request.band
    from core.models import CommercialProposal
    from django.db import transaction

    proposal = get_object_or_404(CommercialProposal, pk=pk, band=band)

    with transaction.atomic():
        # Exclui arquivos físicos dos anexos
        for doc in proposal.documents.all():
            if doc.file:
                try:
                    doc.file.delete(save=False)
                except Exception:
                    pass

        # Exclui show vinculado se criado por esta solicitação
        if proposal.show:
            linked_show = proposal.show
            proposal.show = None
            proposal.save(update_fields=['show'])
            linked_show.delete()

        proposal.delete()

    messages.success(request, "Solicitação e show vinculado excluídos com sucesso.")
    return redirect('commercial_index', band_slug=band.slug)


@login_required
@band_required
@advanced_plan_required
def commercial_delete_document_view(request, band_slug, pk, doc_pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem excluir anexos.")

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    band = request.band
    from core.models import CommercialProposalDocument
    doc = get_object_or_404(CommercialProposalDocument, pk=doc_pk, proposal__pk=pk, proposal__band=band)

    if doc.file:
        try:
            doc.file.delete(save=False)
        except Exception:
            pass
    doc.delete()

    from django.http import JsonResponse
    return JsonResponse({'ok': True, 'message': 'Anexo excluído com sucesso.'})


@login_required
@band_required
@advanced_plan_required
def commercial_check_conflict_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Acesso restrito.")

    band = request.band
    date_str = request.GET.get('date', '').strip()
    proposal_id = request.GET.get('proposal_id', '').strip()

    if not date_str:
        from django.http import JsonResponse
        return JsonResponse({'has_conflict': False})

    from core.models import Show, CommercialProposal
    from datetime import datetime
    try:
        query_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        from django.http import JsonResponse
        return JsonResponse({'has_conflict': False})

    excluded_show_id = None
    if proposal_id and proposal_id.isdigit():
        prop = CommercialProposal.objects.filter(pk=int(proposal_id), band=band).first()
        if prop and prop.show_id:
            excluded_show_id = prop.show_id

    # Busca shows ativos (CONFIRMADO ou PRE_RESERVADO) na mesma data para a mesma banda
    active_shows = Show.objects.filter(
        band=band,
        date=query_date,
        status__in=['CONFIRMADO', 'PRE_RESERVADO']
    )
    if excluded_show_id:
        active_shows = active_shows.exclude(id=excluded_show_id)

    conflict_list = [
        {
            'title': s.title or s.event_name or 'Show',
            'time': s.show_time.strftime('%H:%M') if s.show_time else 'Sem horário definido',
            'status': s.get_status_display()
        }
        for s in active_shows
    ]

    from django.http import JsonResponse
    return JsonResponse({
        'has_conflict': len(conflict_list) > 0,
        'conflicts': conflict_list,
        'message': 'Atenção: Já existe um show para essa data, confira os horários.' if conflict_list else ''
    })






@login_required
@band_required
@advanced_plan_required
def arquivos_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores têm acesso aos arquivos.")

    band = get_object_or_404(Band, slug=band_slug)

    # Processamento do Modal Global de Upload de Arquivo
    if request.method == 'POST' and request.POST.get('action') == 'add_file_global':
        show_id = request.POST.get('show_id')
        category_type = request.POST.get('category_type') # 'documento' ou 'comprovante'
        description = request.POST.get('description', '').strip()
        uploaded_file = request.FILES.get('file')

        if not show_id:
            messages.error(request, "Por favor, selecione um show.")
            return redirect('arquivos', band_slug=band.slug)

        show = get_object_or_404(Show, pk=show_id, band=band)

        if not description:
            messages.error(request, "A descrição do arquivo é obrigatória.")
            return redirect('arquivos', band_slug=band.slug)

        if not uploaded_file:
            messages.error(request, "Nenhum arquivo selecionado para upload.")
            return redirect('arquivos', band_slug=band.slug)

        try:
            from core.file_policy import validate_file_size_and_type, check_show_limits, MAX_SHOW_FILES, MAX_FILE_SIZE_MB, MAX_SHOW_STORAGE_MB
            from django.core.exceptions import ValidationError

            # 1. Valida tamanho individual e tipo/extensão
            validate_file_size_and_type(uploaded_file)

            # 2. Valida quota por show (quantidade e tamanho total em MB)
            check_show_limits(show, [uploaded_file.size])

            if category_type == 'comprovante':
                file_date = request.POST.get('date') or None
                raw_value = request.POST.get('value', '0').replace('.', '').replace(',', '.').strip()
                try:
                    val = Decimal(raw_value) if raw_value else Decimal('0.00')
                except Exception:
                    val = Decimal('0.00')

                receipt = FinancialReceipt(
                    show=show,
                    description=description,
                    date=file_date,
                    category="Comprovante",
                    value=val,
                    file=uploaded_file
                )
                receipt.full_clean()
                receipt.save()
                messages.success(request, f"Comprovante adicionado com sucesso ao show {show.title or 'selecionado'}!")
            else:
                doc = ContractDocument(
                    show=show,
                    description=description,
                    file=uploaded_file
                )
                doc.full_clean()
                doc.save()
                messages.success(request, f"Documento adicionado com sucesso ao show {show.title or 'selecionado'}!")
        except ValidationError as e:
            messages.error(request, e.message if hasattr(e, 'message') else str(e))
        except Exception as e:
            messages.error(request, f"Erro ao salvar arquivo: {str(e)}")

        return redirect('arquivos', band_slug=band.slug)

    from core.file_policy import get_show_files_info, MAX_SHOW_FILES, MAX_FILE_SIZE_MB, MAX_SHOW_STORAGE_MB

    all_band_shows = Show.objects.filter(band=band).order_by('-date', 'title')
    for s in all_band_shows:
        f_count, f_size = get_show_files_info(s)
        s.storage_files_count = f_count
        s.storage_files_size_mb = round(f_size / (1024 * 1024), 2) if f_size else 0

    shows_with_files = Show.objects.filter(band=band).prefetch_related('documents', 'receipts')
    shows_list = [show for show in shows_with_files if show.documents.exists() or show.receipts.exists()]

    context = {
        'band': band,
        'shows': shows_list,
        'all_band_shows': all_band_shows,
        'max_show_files': MAX_SHOW_FILES,
        'max_file_size_mb': MAX_FILE_SIZE_MB,
        'max_show_storage_mb': MAX_SHOW_STORAGE_MB,
    }
    return render(request, 'core/arquivos.html', context)



@login_required
@band_required
def configuracoes_view(request, band_slug):
    band = get_object_or_404(Band, slug=band_slug)

    if request.method == 'POST':
        if not request.user.is_produtor():
            return HttpResponseForbidden("Apenas produtores podem alterar a identidade visual da banda.")

        action = request.POST.get('action')
        if action == 'remove_logo':
            if band.logo:
                try:
                    band.logo.delete(save=False)
                except Exception:
                    pass
                band.logo = None
                band.save(update_fields=['logo'])
                messages.success(request, "Logo da banda removida com sucesso!")
            return redirect('configuracoes', band_slug=band.slug)

        if 'logo' in request.FILES:
            band.logo = request.FILES['logo']
            band.save()
            messages.success(request, "Logo da banda atualizada com sucesso!")
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

        if not band.is_advanced:
            for f in ['contractor_name', 'contractor_phone', 'contract_type', 'fee', 'payment_status']:
                form.fields.pop(f, None)

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
        initial_data = {}
        date_param = request.GET.get('date')
        if date_param:
            import datetime
            try:
                # Valida se a data fornecida é estritamente no formato YYYY-MM-DD
                parsed_date = datetime.date.fromisoformat(date_param)
                initial_data['date'] = parsed_date
            except (ValueError, TypeError):
                pass

        form = ShowForm(initial=initial_data)
        if not band.is_advanced:
            for f in ['contractor_name', 'contractor_phone', 'contract_type', 'fee', 'payment_status']:
                form.fields.pop(f, None)
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
            if not band.is_advanced:
                for f in ['contractor_name', 'contractor_phone', 'contract_type', 'fee', 'payment_status']:
                    form.fields.pop(f, None)
                doc_formset = None
            else:
                doc_formset = ContractDocumentFormSet(request.POST, request.FILES, instance=show_to_edit)

            is_doc_valid = doc_formset.is_valid() if doc_formset else True

            if form.is_valid() and is_doc_valid:

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

                    (old_status == 'CONFIRMADO' and new_status == 'CANCELADO') or

                    (old_status != 'CONFIRMADO' and new_status == 'CONFIRMADO')

                )



                if has_relevant_event:

                    show_to_edit.notification_revision += 1



                form.save()
                if doc_formset:
                    doc_formset.save()

                from core.services import room_list_services
                room_list_services.sync_room_list_from_show(show_to_edit)



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
                    active_tab = request.POST.get('active_tab', '#geral')
                    url = reverse('shows_edit', kwargs={'band_slug': band.slug, 'pk': show_to_edit.id})
                    return redirect(f"{url}{active_tab}")

                return redirect('calendario', band_slug=band.slug)

    else:

        form = ShowForm(instance=show_to_edit)
        if not band.is_advanced:
            for f in ['contractor_name', 'contractor_phone', 'contract_type', 'fee', 'payment_status']:
                form.fields.pop(f, None)
        if not band.is_advanced:
            doc_formset = None
        else:
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

    band = getattr(request, 'band', None) or get_object_or_404(Band, slug=band_slug)

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

    band = getattr(request, 'band', None) or get_object_or_404(Band, slug=band_slug)

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
    has_duplicate_error = False
    other_errors_exist = False
    if form.errors:
        for field_name, err_list in form.errors.as_data().items():
            for err in err_list:
                if getattr(err, 'code', None) == 'duplicate_shared_contact':
                    has_duplicate_error = True
                else:
                    other_errors_exist = True

    context = {
        'band': band,
        'form': form,
        'is_edit': False,
        'has_duplicate_error': has_duplicate_error,
        'other_errors_exist': other_errors_exist
    }
    return render(request, 'core/contato_form.html', context)

@login_required
@band_required
def contato_edit_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem editar contatos.")

    band = getattr(request, 'band', None) or get_object_or_404(Band, slug=band_slug)
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

    has_duplicate_error = False
    other_errors_exist = False
    if form.errors:
        for field_name, err_list in form.errors.as_data().items():
            for err in err_list:
                if getattr(err, 'code', None) == 'duplicate_shared_contact':
                    has_duplicate_error = True
                else:
                    other_errors_exist = True

    context = {
        'band': band,
        'form': form,
        'is_edit': True,
        'contact_to_edit': contact_to_edit,
        'has_duplicate_error': has_duplicate_error,
        'other_errors_exist': other_errors_exist
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

    from django.db.models import Count, Exists, OuterRef, Prefetch, Q
    from .models import ContactLike

    contacts = Contact.objects.filter(
        is_shared_globally=True,
        band__is_active=True,
        is_hidden=False
    ).select_related('band', 'shared_by').annotate(
        likes_count=Count('likes', distinct=True)
    ).prefetch_related(
        Prefetch(
            'likes',
            queryset=ContactLike.objects.select_related('user', 'band').order_by('-created_at'),
            to_attr='prefetched_likes'
        )
    ).order_by('name')

    if request.user.is_authenticated:
        contacts = contacts.annotate(
            is_liked_by_user=Exists(
                ContactLike.objects.filter(
                    contact_id=OuterRef('pk'),
                    user=request.user
                )
            )
        )

    if user_band:
        contacts = contacts.annotate(
            is_already_copied=Exists(
                Contact.objects.filter(
                    band=user_band,
                    copied_from_id=OuterRef('pk')
                )
            )
        )

    search_query = request.GET.get('q', '').strip()
    search_type = request.GET.get('tipo', '').strip()
    search_location = request.GET.get('local', '').strip()
    search_band = request.GET.get('banda', '').strip()

    if search_query:
        contacts = contacts.filter(name__icontains=search_query)
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
def contact_copy_from_global_view(request, band_slug, pk):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem copiar contatos.")

    band = getattr(request, 'band', None)
    if not band:
        return HttpResponseForbidden("Banda não identificada no contexto.")

    original_contact = get_object_or_404(
        Contact,
        pk=pk,
        is_shared_globally=True,
        is_hidden=False,
        band__is_active=True
    )

    from django.db import transaction, IntegrityError
    from django.http import JsonResponse

    # Se o contato já pertence à própria banda atual
    if original_contact.band == band:
        return JsonResponse({
            'ok': True,
            'status': 'already_copied',
            'contact_id': original_contact.id,
            'message': 'Este contato já pertence à sua banda.'
        })

    # Verifica se já foi copiado
    existing_copy = Contact.objects.filter(band=band, copied_from=original_contact).first()
    if existing_copy:
        return JsonResponse({
            'ok': True,
            'status': 'already_copied',
            'contact_id': existing_copy.id,
            'message': 'Este contato já foi copiado.'
        })

    try:
        with transaction.atomic():
            copy_contact = Contact.objects.create(
                band=band,
                name=original_contact.name,
                contact_type=original_contact.contact_type,
                phone=original_contact.phone,
                email=original_contact.email,
                location=original_contact.location,
                link=original_contact.link,
                notes='',
                public_information=original_contact.public_information,
                is_shared_globally=False,
                is_hidden=False,
                copied_from=original_contact
            )
            return JsonResponse({
                'ok': True,
                'status': 'copied',
                'contact_id': copy_contact.id,
                'message': 'Contato copiado para a página Contatos.'
            })
    except IntegrityError:
        existing_copy = Contact.objects.filter(band=band, copied_from=original_contact).first()
        return JsonResponse({
            'ok': True,
            'status': 'already_copied',
            'contact_id': existing_copy.id if existing_copy else original_contact.id,
            'message': 'Este contato já foi copiado.'
        })


@login_required
@band_required
def contact_toggle_like_view(request, band_slug, pk):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem curtir ou descurtir contatos.")

    band = getattr(request, 'band', None)
    if not band or not band.is_active:
        return HttpResponseForbidden("Banda ativa não identificada no contexto.")

    from .models import ContactLike
    from django.db import transaction
    from django.http import JsonResponse

    # O contato deve estar compartilhado globalmente, visível e pertencer a uma banda ativa
    contact = get_object_or_404(
        Contact,
        pk=pk,
        is_shared_globally=True,
        is_hidden=False,
        band__is_active=True
    )

    # Como a curtida representa validação por terceiros, o produtor não pode curtir um contato pertencente à própria banda
    if contact.band == band:
        return JsonResponse({
            'ok': False,
            'message': 'Você não pode curtir um contato pertencente à sua própria banda.'
        }, status=400)

    with transaction.atomic():
        existing_like = ContactLike.objects.filter(contact=contact, user=request.user).first()
        if existing_like:
            existing_like.delete()
            is_liked = False
        else:
            ContactLike.objects.create(
                contact=contact,
                user=request.user,
                band=band
            )
            is_liked = True

        likes_count = ContactLike.objects.filter(contact=contact).count()
        likes_qs = ContactLike.objects.filter(contact=contact).select_related('user', 'band').order_by('-created_at')
        likes_list = [
            {
                'producer_name': like.user.get_full_name() or like.user.username,
                'band_name': like.band.name
            }
            for like in likes_qs
        ]

    return JsonResponse({
        'ok': True,
        'is_liked': is_liked,
        'likes_count': likes_count,
        'likes_list': likes_list,
        'contact_id': contact.id
    })


@login_required
@band_required
def contato_delete_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem excluir contatos.")

    band = getattr(request, 'band', None) or get_object_or_404(Band, slug=band_slug)
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

    if not band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")

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

    if not band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")

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

    if not band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")

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

    if not band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")

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

@advanced_plan_required
def add_dashboard_pending_item(request, band_slug):

    band = get_object_or_404(Band, slug=band_slug)

    if (request.user.band != band and not request.user.is_superuser) or not request.user.is_produtor():

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

@advanced_plan_required
def delete_dashboard_pending_item(request, band_slug, pending_id):

    band = get_object_or_404(Band, slug=band_slug)

    if (request.user.band != band and not request.user.is_superuser) or not request.user.is_produtor():

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

@advanced_plan_required
def edit_dashboard_pending_item(request, band_slug, pending_id):

    band = get_object_or_404(Band, slug=band_slug)

    if (request.user.band != band and not request.user.is_superuser) or not request.user.is_produtor():

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

@advanced_plan_required
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
        if getattr(request.user, 'band_id', None) != request.band.id and not request.user.is_superuser:
            raise PermissionDenied("Acesso negado à banda.")
        if not request.user.is_produtor():
            raise PermissionDenied("Acesso restrito a produtores.")

        return view_func(request, band_slug, *args, **kwargs)
    return _wrapped_view

@room_list_produtor_required
@advanced_plan_required
def room_list_index(request, band_slug):
    room_lists = RoomList.objects.filter(band=request.band).select_related('show').order_by('show__date')
    select_show_form = RoomListSelectShowForm(band=request.band)
    room_list_form = RoomListForm()
    return render(request, 'core/room_list/room_list_index.html', {
        'band': request.band,
        'room_lists': room_lists,
        'select_show_form': select_show_form,
        'room_list_form': room_list_form,
    })

@room_list_produtor_required
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
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
                next_url = request.GET.get('next') or request.POST.get('next')
                if next_url:
                    return redirect(next_url)
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
@advanced_plan_required
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
@advanced_plan_required
def room_list_room_create(request, band_slug, pk):
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
    except RoomListNotFoundError:
        raise Http404("Room List não encontrada.")

    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity', 1))
            room_number = request.POST.get('number_or_name', '').strip()
            if not room_number:
                room_number = 'Sem número'
                
            room_type = request.POST.get('type')
            capacity = request.POST.get('capacity', 1)
            beds_config = request.POST.get('beds_config', '')
            has_ac = request.POST.get('has_ac') == 'on'
            
            from core.models import Room
            for i in range(1, quantity + 1):
                final_name = room_number
                if quantity > 1:
                    final_name = f"{room_number}_{i:02d}"
                
                # Ensure uniqueness to avoid DuplicateRoomNumberError
                counter = i if quantity > 1 else 1
                while Room.objects.filter(room_list=room_list, number_or_name=final_name).exists():
                    final_name = f"{room_number}_{counter:02d}"
                    counter += 1
                
                room_list_services.create_room(
                    room_list_id=room_list.id,
                    room_type=room_type,
                    capacity=int(capacity),
                    number_or_name=final_name,
                    user=request.user,
                    beds_config=beds_config,
                    has_ac=has_ac
                )
            msg = f"1 quarto adicionado com sucesso." if quantity == 1 else f"{quantity} quartos adicionados com sucesso."
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, str(e))
        return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)

    # In case they GET this view directly, redirect them to manage.
    return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)

@room_list_produtor_required
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
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
        messages.error(request, str(e))
        if is_fetch:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
@advanced_plan_required
def room_list_unassign(request, band_slug, pk, participant_id):
    is_fetch = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('Content-Type') == 'application/json'
    try:
        room_list_services.unassign_participant(participant_id, request.user)
        if is_fetch:
            return JsonResponse({'status': 'success'})
        messages.success(request, 'Participante desalocado.')
    except Exception as e:
        messages.error(request, str(e))
        if is_fetch:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
    return redirect('room_list_manage', band_slug=band_slug, pk=pk)

@room_list_produtor_required
@require_POST
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
def lodging_template_manage(request, band_slug):
    from core.models import LodgingTemplate
    band = request.band
    template, created = LodgingTemplate.objects.get_or_create(band=band)
    
    return render(request, 'core/room_list/lodging_template_manage.html', {
        'band': band,
        'template': template,
    })

@room_list_produtor_required
@advanced_plan_required
def lodging_template_room_create(request, band_slug, pk):
    from core.models import LodgingTemplate, TemplateRoom
    template = get_object_or_404(LodgingTemplate, pk=pk, band=request.band)
    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity', 1))
            room_number = request.POST.get('number_or_name', '').strip()
            if not room_number:
                room_number = 'Sem número'
                
            room_type = request.POST.get('type')
            capacity = request.POST.get('capacity', 1)
            beds_config = request.POST.get('beds_config', '')
            has_ac = request.POST.get('has_ac') == 'on'
            
            for i in range(1, quantity + 1):
                final_name = room_number
                if quantity > 1:
                    final_name = f"{room_number}_{i:02d}"
                
                counter = i if quantity > 1 else 1
                while TemplateRoom.objects.filter(template=template, number_or_name=final_name).exists():
                    final_name = f"{room_number}_{counter:02d}"
                    counter += 1
                
                TemplateRoom.objects.create(
                    template=template,
                    number_or_name=final_name,
                    type=room_type,
                    capacity=int(capacity),
                    beds_config=beds_config,
                    has_ac=has_ac
                )
            
            msg = f"1 quarto adicionado com sucesso." if quantity == 1 else f"{quantity} quartos adicionados com sucesso."
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, f"Erro ao criar quartos: {str(e)}")
    return redirect('lodging_template_manage', band_slug=band_slug)

@room_list_produtor_required
@advanced_plan_required
def lodging_template_room_update(request, band_slug, pk, room_id):
    from core.models import LodgingTemplate, TemplateRoom
    template = get_object_or_404(LodgingTemplate, pk=pk, band=request.band)
    room = get_object_or_404(TemplateRoom, pk=room_id, template=template)
    
    if request.method == 'POST':
        try:
            room_number = request.POST.get('number_or_name', '').strip()
            if not room_number:
                room_number = 'Sem número'
                
            # Allow same name if it's the current room
            if TemplateRoom.objects.filter(template=template, number_or_name=room_number).exclude(pk=room.pk).exists():
                messages.error(request, f"Já existe um quarto '{room_number}' neste modelo.")
            else:
                room.number_or_name = room_number
                room.type = request.POST.get('type')
                room.capacity = int(request.POST.get('capacity', 1))
                room.beds_config = request.POST.get('beds_config', '')
                room.has_ac = request.POST.get('has_ac') == 'on'
                room.save()
                messages.success(request, "Quarto atualizado com sucesso.")
        except Exception as e:
            messages.error(request, f"Erro ao atualizar quarto: {str(e)}")
            
    return redirect('lodging_template_manage', band_slug=band_slug)

@room_list_produtor_required
@advanced_plan_required
def lodging_template_room_delete(request, band_slug, pk, room_id):
    from core.models import LodgingTemplate, TemplateRoom
    template = get_object_or_404(LodgingTemplate, pk=pk, band=request.band)
    room = get_object_or_404(TemplateRoom, pk=room_id, template=template)
    
    if request.method == 'POST':
        room.delete()
        messages.success(request, "Quarto excluído com sucesso.")
        
    return redirect('lodging_template_manage', band_slug=band_slug)



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
@advanced_plan_required
def room_list_preview_view(request, band_slug, pk):
    from core.models import RoomList
    from django.core.exceptions import PermissionDenied

    try:
        room_list = RoomList.objects.select_related('show', 'band').prefetch_related(
            'rooms__participants__original_integrante'
        ).get(pk=pk, show__band=request.band)
    except RoomList.DoesNotExist:
        raise Http404("Room List não encontrada.")

    is_produtor = request.user.is_produtor()
    if not is_produtor and room_list.status == RoomList.StatusChoices.RASCUNHO:
        raise PermissionDenied("Acesso restrito. Room List em rascunho.")

    context = {
        'band': request.band,
        'pdf_logo_base64': get_image_base64(request.band.logo),
        'ac_badge_base64': get_static_image_base64('img/room-ac-badge.png'),
        'current_datetime': __import__('django.utils.timezone').utils.timezone.localtime().strftime('%d/%m/%Y às %H:%M'),
        'room_list': room_list,
        'rooms': room_list.rooms.all(),
        'participants': room_list.participants.filter(room__isnull=False),
        'unallocated': room_list.participants.filter(room__isnull=True),
    }
    return render(request, 'core/room_list/room_list_preview.html', context)


@login_required
@band_required
@advanced_plan_required
def room_list_pdf_view(request, band_slug, pk):
    from core.models import RoomList
    from django.core.exceptions import PermissionDenied
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from xhtml2pdf import pisa
    import io

    try:
        room_list = RoomList.objects.select_related('show', 'band').prefetch_related(
            'rooms__participants__original_integrante'
        ).get(pk=pk, show__band=request.band)
    except RoomList.DoesNotExist:
        raise Http404("Room List não encontrada.")

    is_produtor = request.user.is_produtor()
    if not is_produtor and room_list.status == RoomList.StatusChoices.RASCUNHO:
        raise PermissionDenied("Acesso restrito. Room List em rascunho.")

    context = {
        'band': request.band,
        'pdf_logo_base64': get_image_base64(request.band.logo),
        'ac_badge_base64': get_static_image_base64('img/room-ac-badge.png'),
        'current_datetime': __import__('django.utils.timezone').utils.timezone.localtime().strftime('%d/%m/%Y às %H:%M'),
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
@advanced_plan_required
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
            'rooms__participants__original_integrante'
        ).get(pk=pk, show__band=request.band)
    except RoomList.DoesNotExist:
        raise Http404("Room List não encontrada.")

    context = {
        'band': request.band,
        'pdf_logo_base64': get_image_base64(request.band.logo),
        'ac_badge_base64': get_static_image_base64('img/room-ac-badge.png'),
        'current_datetime': __import__('django.utils.timezone').utils.timezone.localtime().strftime('%d/%m/%Y às %H:%M'),
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
@advanced_plan_required
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
@advanced_plan_required
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
@advanced_plan_required
def band_notices_index(request, band_slug):
    notices = request.band.notices.all()
    from core.forms import BandNoticeForm
    form = BandNoticeForm()

    return render(request, 'core/notices/band_notices_index.html', {'notices': notices, 'band': request.band, 'form': form})

@login_required
@band_required
@advanced_plan_required
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
                from core.services.notifications import notify_band_users
                notice.sent_at = timezone.now()
                notice.save()
                try:
                    notify_band_users(
                        band=notice.band,
                        event_type='AVISO',
                        title='Aviso da Produção',
                        message=notice.message,
                        target_url=f'/{notice.band.slug}/painel/',
                        event_key_base=f'aviso_{notice.id}',
                        actor=notice.created_by
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
@advanced_plan_required
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
@advanced_plan_required
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

@room_list_produtor_required
@advanced_plan_required
@require_POST
def lodging_template_observations_update(request, band_slug):
    from core.models import LodgingTemplate
    band = request.band
    template, created = LodgingTemplate.objects.get_or_create(band=band)
    
    observations = request.POST.get('default_observations', '')
    if len(observations) > 2000:
        messages.error(request, "As observações não podem exceder 2000 caracteres.")
    else:
        template.default_observations = observations
        template.save()
        messages.success(request, "Observações padrão salvas com sucesso.")
        
    return redirect('lodging_template_manage', band_slug=band.slug)

@room_list_produtor_required
@advanced_plan_required
@require_POST
def room_list_observations_update(request, band_slug, pk):
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
    except Exception:
        raise Http404("Room List não encontrada.")

    observations = request.POST.get('observations', '')
    if len(observations) > 2000:
        messages.error(request, "As observações não podem exceder 2000 caracteres.")
    else:
        try:
            room_list_services.update_room_list(
                room_list_id=room_list.id,
                user=request.user,
                observations=observations
            )
            messages.success(request, "Observações salvas com sucesso.")
        except Exception as e:
            messages.error(request, str(e))

    return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)

