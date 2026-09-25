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

from .decorators import advanced_plan_required, empresario_required
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

from django.contrib.auth import update_session_auth_hash

from .models import Show, FinancialReceipt, Band, User, Contact, ContractDocument, ShowPayment, ShowTeamCost, BandDashboardPendingItem, AdministrativeBandNotice, RiderDocument, UserBandMembership, BandGeneralExpense

from .forms import FinancialReceiptForm, UserForm, UserEditForm, ContactForm, ShowForm, ContractDocumentFormSet, FinancialReceiptFormSet, ShowPaymentForm, ShowTeamCostForm, ContractDocumentForm, RiderDocumentForm, ProfileForm, ProfilePasswordChangeForm, MandatoryPasswordChangeForm, BandGeneralExpenseForm

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



@login_required
def profile_view(request):
    """
    BP-PEND-50: Área de Perfil para todas as contas autenticadas.
    Permite visualizar/editar foto de perfil, nome, e-mail, telefone,
    ver login (somente leitura) e alterar senha mantendo a sessão.
    """
    user = request.user
    active_tab = request.POST.get('active_tab', '#dados')

    # Foto/dados do perfil
    if request.method == 'POST' and 'update_profile' in request.POST:
        profile_form = ProfileForm(request.POST, request.FILES, instance=user)
        password_form = ProfilePasswordChangeForm(user=user)
        active_tab = '#dados'

        # Se houver pedido de remover foto de perfil
        if request.POST.get('remove_picture') == '1':
            if user.profile_picture:
                user.profile_picture.delete(save=False)
                user.profile_picture = None

        if profile_form.is_valid():
            profile_form.save()
            messages.success(request, "Perfil atualizado com sucesso!")
            return redirect('perfil')
        else:
            messages.error(request, "Por favor, corrija os erros no perfil.")
    elif request.method == 'POST' and 'change_password' in request.POST:
        profile_form = ProfileForm(instance=user)
        password_form = ProfilePasswordChangeForm(user=user, data=request.POST)
        active_tab = '#senha'
        if password_form.is_valid():
            password_form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Senha alterada com sucesso!")
            return redirect('perfil')
        else:
            messages.error(request, "Por favor, corrija os erros ao alterar a senha.")
    else:
        profile_form = ProfileForm(instance=user)
        password_form = ProfilePasswordChangeForm(user=user)

    band = getattr(request, 'band', None) or getattr(user, 'band', None)

    context = {
        'user': user,
        'band': band,
        'profile_form': profile_form,
        'password_form': password_form,
        'active_tab': active_tab,
    }
    return render(request, 'core/perfil.html', context)



@login_required
def first_access_password_change(request):
    """
    BP-PEND-51: Troca obrigatória de senha no primeiro acesso para usuários
    com senha provisória (must_change_password=True).
    """
    user = request.user
    if not user.must_change_password:
        if user.band:
            return redirect('dashboard', band_slug=user.band.slug)
        elif user.is_superuser:
            return redirect('admin_painel:dashboard')
        return redirect('perfil')

    if request.method == 'POST':
        form = MandatoryPasswordChangeForm(user=user, data=request.POST)
        if form.is_valid():
            form.save()
            update_session_auth_hash(request, user)
            messages.success(request, "Sua senha pessoal foi cadastrada com sucesso! Bem-vindo(a).")
            if user.band:
                return redirect('dashboard', band_slug=user.band.slug)
            elif user.is_superuser:
                return redirect('admin_painel:dashboard')
            return redirect('perfil')
    else:
        form = MandatoryPasswordChangeForm(user=user)

    band = getattr(request, 'band', None) or getattr(user, 'band', None)

    context = {
        'user': user,
        'band': band,
        'form': form,
    }
    return render(request, 'core/troca_senha_obrigatoria.html', context)



def band_required(view_func):

    @wraps(view_func)

    def _wrapped_view(request, band_slug, *args, **kwargs):

        band = get_object_or_404(Band, slug=band_slug)

        if not request.user.is_authenticated:

            return redirect('login', band_slug=band_slug)

        # BP-PEND-51: Obriga troca de senha provisória antes de acessar qualquer rota da banda (exceto logout)
        if request.user.must_change_password and view_func.__name__ != 'band_logout':
            return redirect('troca_senha_obrigatoria')

        # BP-PEND-62: Validação de segurança / isolamento com suporte a múltiplos vínculos
        if not request.user.has_access_to_band(band) and not request.user.is_superuser:

            raise PermissionDenied("Você não pertence a esta banda.")

        if not band.is_active and not request.user.is_superuser:

            raise PermissionDenied("O acesso desta banda ao Backstage Pro está temporariamente suspenso. Entre em contato com a administração.")

        # Restrição de acesso para assinaturas inativas/encerradas
        if not request.user.is_superuser:
            if not band.has_active_subscription:
                if view_func.__name__ not in ('minha_assinatura_view', 'band_logout'):
                    return redirect('minha_assinatura', band_slug=band.slug)

        # Guarda banda ativa na sessão
        request.session['active_band_id'] = band.id

        # Ajusta dinamicamente role do usuário para o contexto desta banda
        if not request.user.is_superuser:
            request.user.role = request.user.get_role_for_band(band)

        request.band = band

        return view_func(request, band_slug, *args, **kwargs)

    return _wrapped_view





def band_root_redirect_view(request, band_slug):

    if request.user.is_authenticated:

        if request.user.must_change_password:
            return redirect('troca_senha_obrigatoria')

        if request.user.is_superuser:

            return redirect('admin_painel:dashboard')

        # BP-PEND-62: Suporte a múltiplos vínculos
        active_memberships = request.user.get_active_memberships()
        count = active_memberships.count()

        if count >= 2:
            return redirect('selecionar_banda')
        elif count == 1:
            m = active_memberships.first()
            target_slug = m.band.slug
            if not m.band.has_active_subscription:
                return redirect('minha_assinatura', band_slug=target_slug)
            return redirect('dashboard', band_slug=target_slug)
        elif request.user.band:
            # Fallback legado
            target_slug = request.user.band.slug
            if not request.user.band.has_active_subscription:
                return redirect('minha_assinatura', band_slug=target_slug)
            return redirect('dashboard', band_slug=target_slug)

    band = get_object_or_404(Band, slug=band_slug)
    if not band.has_active_subscription:
        return redirect('minha_assinatura', band_slug=band_slug)
    return redirect('dashboard', band_slug=band_slug)



def get_post_login_redirect_url(user, default_band=None):
    """
    BP-PEND-71 / BP-PEND-62: Resolução centralizada e canônica de pós-login em /entrar/:
    - user.must_change_password -> troca_senha_obrigatoria
    - 2+ memberships ativas -> selecionar_banda
    - 1 membership ativa -> dashboard ou minha_assinatura da banda
    - Fallback legado (user.band) -> dashboard ou minha_assinatura
    - default_band (se fornecida e usuário tem acesso) -> dashboard ou minha_assinatura
    - Sem banda válida -> selecionar_banda com mensagem amigável de ausência de acesso
      (NUNCA redireciona staff/superuser para /painel/; Admin Geral usa /painel/login/)
    """
    if user.must_change_password:
        return reverse('troca_senha_obrigatoria')

    active_memberships = user.get_active_memberships()
    count = active_memberships.count()

    if count >= 2:
        return reverse('selecionar_banda')
    elif count == 1:
        m = active_memberships.first()
        if not m.band.has_active_subscription:
            return reverse('minha_assinatura', kwargs={'band_slug': m.band.slug})
        return reverse('dashboard', kwargs={'band_slug': m.band.slug})

    if user.band:
        if not user.band.has_active_subscription:
            return reverse('minha_assinatura', kwargs={'band_slug': user.band.slug})
        return reverse('dashboard', kwargs={'band_slug': user.band.slug})

    if default_band and user.has_access_to_band(default_band):
        if not default_band.has_active_subscription:
            return reverse('minha_assinatura', kwargs={'band_slug': default_band.slug})
        return reverse('dashboard', kwargs={'band_slug': default_band.slug})

    return reverse('selecionar_banda')


class CentralLoginView(LoginView):
    """
    BP-PEND-71: Entrada central e canônica (/entrar/) para todos os usuários das bandas.
    Totalmente neutra e desacoplada de slug de banda.
    """
    template_name = 'core/central_login.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(get_post_login_redirect_url(request.user))
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        user = self.request.user
        next_url = self.request.POST.get('next') or self.request.GET.get('next')
        if next_url and next_url.startswith('/'):
            return next_url
        return get_post_login_redirect_url(user)


def legacy_band_login_redirect(request, band_slug):
    """
    BP-PEND-71: Preserva retrocompatibilidade com links antigos /<band_slug>/login/
    redirecionando permanentemente/seguramente para a entrada central /entrar/.
    """
    next_url = request.GET.get('next')
    if request.user.is_authenticated:
        band = Band.objects.filter(slug=band_slug).first()
        return redirect(get_post_login_redirect_url(request.user, default_band=band))

    central_url = reverse('central_login')
    if next_url and next_url.startswith('/'):
        from urllib.parse import quote
        return redirect(f"{central_url}?next={quote(next_url)}")
    return redirect(central_url)


class BandLoginView(CentralLoginView):
    """
    Alias mantido para imports legados ou retrocompatibilidade.
    """
    pass


@require_POST
def central_logout(request):
    """
    BP-PEND-71: Logout central de usuários de bandas.
    Encerra a sessão, limpa contexto de banda ativa e redireciona para /entrar/.
    """
    request.session.pop('active_band_id', None)
    logout(request)
    return redirect('central_login')


@require_POST
def band_logout(request, band_slug=None):
    """
    BP-PEND-71: Encerra a sessão e redireciona para /entrar/ (nunca para o admin).
    """
    request.session.pop('active_band_id', None)
    logout(request)
    return redirect('central_login')



# ──────────────────────────────────────────────────────────────────────────────
# BP-PEND-62: MULTILOGIN — Seleção e Troca de Banda
# ──────────────────────────────────────────────────────────────────────────────

@login_required
def selecionar_banda_view(request):
    """
    Página de seleção de banda para usuários com múltiplos vínculos.
    Rota global: /selecionar-banda/
    """
    if request.user.must_change_password:
        return redirect('troca_senha_obrigatoria')

    memberships = request.user.get_active_memberships().select_related('band')

    # Se só tem 1 banda ativa, vai direto sem mostrar tela de seleção
    if memberships.count() == 1:
        m = memberships.first()
        request.session['active_band_id'] = m.band.id
        if not m.band.has_active_subscription:
            return redirect('minha_assinatura', band_slug=m.band.slug)
        return redirect('dashboard', band_slug=m.band.slug)

    if request.method == 'POST':
        band_id = request.POST.get('band_id')
        if not band_id:
            messages.error(request, "Selecione uma banda.")
            return redirect('selecionar_banda')

        try:
            membership = memberships.get(band_id=band_id)
        except memberships.model.DoesNotExist:
            raise PermissionDenied("Você não tem acesso a esta banda.")

        band = membership.band
        request.session['active_band_id'] = band.id

        if not band.has_active_subscription:
            return redirect('minha_assinatura', band_slug=band.slug)
        return redirect('dashboard', band_slug=band.slug)

    return render(request, 'core/selecionar_banda.html', {
        'memberships': memberships,
        'page_title': 'Selecionar Banda',
    })


@login_required
def trocar_banda_view(request):
    """
    Limpa a banda ativa da sessão e redireciona para seleção de banda.
    Rota global: /trocar-banda/
    """
    request.session.pop('active_band_id', None)
    return redirect('selecionar_banda')


@login_required

@band_required

def dashboard_view(request, band_slug):

    band = get_object_or_404(Band, slug=band_slug)

    shows_proximos = (
        Show.objects.filter(band=band, date__gte=datetime.date.today())
        .exclude(status=Show.STATUS_CANCELADO)
        .order_by('date', 'show_time')[:6]
    )

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
    BP-PEND-56: Shows com proposta comercial em 'DESISTENCIA' não aparecem na Agenda.
    """
    shows = Show.objects.filter(band=request.band).exclude(
        commercial_proposal__phase='DESISTENCIA'
    ).order_by('date')

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



    is_emp = request.user.is_superuser or request.user.is_empresario(request.band)

    if is_emp:
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
        'is_empresario': is_emp,
        'total_custos': total_custos,
        'resultado_previsto': resultado_previsto,
        'margem_prevista': margem_prevista,
        'total_recebido': total_recebido if is_emp else 0,
        'total_pendente': total_pendente if is_emp else 0,
        'percentual_recebido': percentual_recebido if is_emp else 0,
        'caixa_realizado': caixa_realizado if is_emp else 0,
    }

    return render(request, 'core/show_detail.html', context)



@band_required

@login_required

@empresario_required

def show_finance_detail_view(request, band_slug, pk):

    """

    Detalhes exclusivamente financeiros de um show específico.

    """

    if not (request.user.is_superuser or request.user.is_empresario(request.band)):

        return HttpResponseForbidden("Apenas empresários têm acesso ao financeiro do show.")



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

                receipt = receipt_form.save(commit=False)

                receipt.show = show

                receipt.created_by = request.user

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



    shows = Show.objects.filter(band=request.band).exclude(
        commercial_proposal__phase='DESISTENCIA'
    ).order_by('date')



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
    """
    BP-PEND-71: Recuperação automática por e-mail:
    - Aceita login (username) ou e-mail no mesmo campo.
    - Segurança contra enumeração de contas: resposta pública idêntica (neutra).
    - Se username: localiza a conta e, se possuir e-mail válido, envia instruções.
    - Se e-mail: se houver exatamente 1 usuário, envia; se houver duplicados, não arbitra.
    - Se não houver e-mail válido ou usuário não existir: resposta permanece neutra.
    - Utiliza token seguro do Django (PasswordResetTokenGenerator) e uidb64.
    """
    template_name = 'core/password_reset.html'
    email_template_name = 'emails/password_reset.html'
    subject_template_name = 'core/password_reset_subject.txt'
    success_url = '/esqueci-minha-senha/enviado/'
    from core.forms import PasswordResetRequestForm
    form_class = PasswordResetRequestForm

    def form_valid(self, form):
        identification = form.cleaned_data.get('identification', '').strip()
        user_model = User

        target_user = None
        # 1. Tenta identificar primeiro por username exato
        try:
            target_user = user_model.objects.get(username=identification)
        except user_model.DoesNotExist:
            target_user = None
        except user_model.MultipleObjectsReturned:
            target_user = None

        # 2. Se não encontrou por username, busca por e-mail (case-insensitive)
        if not target_user and '@' in identification:
            matching_users = list(user_model.objects.filter(email__iexact=identification))
            if len(matching_users) == 1:
                target_user = matching_users[0]
            elif len(matching_users) > 1:
                logger.warning(
                    "Recuperação de senha solicitada para e-mail duplicado (%s): %d contas encontradas. "
                    "Nenhuma conta arbitrária foi selecionada por segurança.",
                    identification, len(matching_users)
                )
                target_user = None

        # 3. Se um usuário válido com e-mail cadastrado foi identificado com precisão:
        if target_user and target_user.is_active and target_user.email and target_user.email.strip():
            self._send_password_reset_email(target_user)
        else:
            logger.info(
                "Solicitação de recuperação processada com resposta neutra (user_found=%s, has_email=%s)",
                bool(target_user), bool(target_user.email if target_user else False)
            )

        return redirect(self.get_success_url())

    def _send_password_reset_email(self, user):
        from django.utils.http import urlsafe_base64_encode
        from django.utils.encoding import force_bytes
        from django.contrib.auth.tokens import default_token_generator
        from core.services.email_service import get_canonical_base_url, enqueue_email, render_and_send_email_delivery
        from core.models import EmailDelivery

        token = default_token_generator.make_token(user)
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        base_url = get_canonical_base_url()
        reset_path = reverse('password_reset_confirm', kwargs={'uidb64': uid, 'token': token})
        reset_url = f"{base_url}{reset_path}"

        user_name = user.get_full_name() or user.first_name or user.username
        subject = "Redefinição de senha — Backstage Pro"
        idempotency_key = f"pwd-reset-{user.id}-{int(datetime.datetime.now().timestamp())}"

        context_data = {
            'user_name': user_name,
            'reset_url': reset_url,
            'base_url': base_url,
        }

        # Enfileira na fila transacional do sistema
        delivery, created = enqueue_email(
            email_type='PASSWORD_RESET',
            recipient_email=user.email.strip(),
            subject=subject,
            idempotency_key=idempotency_key,
            template_name='emails/password_reset',
            context_data=context_data,
            related_object_type='User',
            related_object_id=str(user.id),
            max_attempts=3
        )

        # Dispara o envio imediato da mensagem
        try:
            render_and_send_email_delivery(delivery)
        except Exception as e:
            logger.error("Erro ao enviar e-mail de recuperação para delivery %s: %s", delivery.id, str(e))


class CustomPasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'core/password_reset_done.html'


class CustomPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'core/password_reset_confirm.html'
    success_url = '/redefinir-senha/concluido/'


class CustomPasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'core/password_reset_complete.html'



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

    is_emp = request.user.is_superuser or request.user.is_empresario(band)
    context = {
        'band': band,
        'subscription': subscription,
        'is_empresario': is_emp,
    }
    return render(request, 'core/relatorios_index.html', context)


@login_required
@band_required
@empresario_required
def minha_assinatura_view(request, band_slug):
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários têm acesso à gestão da assinatura.")

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
            from django.db import transaction
            from django.utils import timezone
            from core.models import BandSubscription, SubscriptionCancellationFeedback
            from core.services.payments.asaas.client import AsaasClient

            reason = (request.POST.get('reason') or '').strip()
            if not reason or len(reason) > 1000:
                messages.error(request, "Informe o motivo do cancelamento (até 1.000 caracteres).")
                return redirect('minha_assinatura', band_slug=band.slug)
            if not subscription or request.POST.get('subscription_id') != str(subscription.id):
                messages.error(request, "A assinatura selecionada mudou. Atualize a página e tente novamente.")
                return redirect('minha_assinatura', band_slug=band.slug)

            # A trava impede duas confirmações simultâneas para a mesma assinatura.
            # O feedback é gravado somente após a confirmação do gateway, na mesma transação local.
            with transaction.atomic():
                sub_locked = BandSubscription.objects.select_for_update().filter(
                    pk=subscription.pk, band=band, is_deleted=False,
                ).first()
                if not sub_locked or sub_locked.status != 'ATIVO' or sub_locked.cancel_at_period_end or not sub_locked.auto_renew:
                    messages.info(request, "Esta assinatura já não possui renovação ativa para cancelar.")
                    return redirect('minha_assinatura', band_slug=band.slug)

                # Planos anuais parcelados não têm assinatura recorrente no Asaas.
                if (sub_locked.gateway_provider == 'ASAAS'
                        and sub_locked.gateway_subscription_id
                        and sub_locked.billing_cycle != 'ANUAL'):
                    try:
                        client = AsaasClient()
                        sub_info = client.get_subscription(sub_locked.gateway_subscription_id)
                    except Exception:
                        logger.exception("Erro ao consultar assinatura Asaas no cancelamento da banda %s", band.slug)
                        messages.error(request, "Não foi possível validar a assinatura no Asaas. Tente novamente.")
                        return redirect('minha_assinatura', band_slug=band.slug)

                    if not sub_info:
                        messages.error(request, "Não foi possível validar a assinatura no Asaas. Tente novamente.")
                        return redirect('minha_assinatura', band_slug=band.slug)
                    if sub_info.get('id') != sub_locked.gateway_subscription_id:
                        logger.error("Divergência de ID de assinatura: local=%s, remoto=%s",
                                     sub_locked.gateway_subscription_id, sub_info.get('id'))
                        messages.error(request, "Inconsistência na assinatura remota. Cancelamento abortado.")
                        return redirect('minha_assinatura', band_slug=band.slug)
                    remote_customer_id = sub_info.get('customer')
                    if (sub_locked.gateway_customer_id and remote_customer_id
                            and remote_customer_id != sub_locked.gateway_customer_id):
                        logger.error("Divergência de cliente da assinatura %s", sub_locked.gateway_subscription_id)
                        messages.error(request, "Inconsistência de titularidade. Cancelamento abortado.")
                        return redirect('minha_assinatura', band_slug=band.slug)

                    if sub_info.get('deleted') is not True and sub_info.get('status') != 'INACTIVE':
                        try:
                            success, resp_data = client.cancel_subscription(sub_locked.gateway_subscription_id)
                        except Exception:
                            logger.exception("Erro ao cancelar assinatura Asaas %s", sub_locked.gateway_subscription_id)
                            messages.error(request, "Não foi possível cancelar a renovação no Asaas. Tente novamente.")
                            return redirect('minha_assinatura', band_slug=band.slug)
                        if not success:
                            logger.error("Falha no cancelamento Asaas %s: %s", sub_locked.gateway_subscription_id, resp_data)
                            messages.error(request, "Não foi possível cancelar a renovação no Asaas. Nenhuma alteração foi realizada.")
                            return redirect('minha_assinatura', band_slug=band.slug)

                sub_locked.cancel_at_period_end = True
                sub_locked.auto_renew = False
                sub_locked.canceled_at = timezone.now()
                sub_locked.save(update_fields=['cancel_at_period_end', 'auto_renew', 'canceled_at', 'updated_at'])
                SubscriptionCancellationFeedback.objects.create(
                    subscription=sub_locked,
                    band=band,
                    requested_by=request.user,
                    band_name=band.name,
                    gateway_subscription_id=sub_locked.gateway_subscription_id or '',
                    reason=reason,
                )

            logger.info(
                "Assinatura %d da banda '%s' marcada para cancelamento pelo usuário %s.",
                subscription.id, band.slug, request.user.username,
            )
            try:
                from core.services.email_service import enqueue_email, resolve_subscription_recipient
                from core.models import EmailDelivery
                rec_email, rec_name = resolve_subscription_recipient(subscription)
                if rec_email:
                    idemp_k = f"sub-cancel-scheduled-{subscription.id}-{timezone.localdate().isoformat()}"
                    enqueue_email(
                        email_type=EmailDelivery.EmailType.SUBSCRIPTION_CANCELLATION_SCHEDULED,
                        recipient_email=rec_email,
                        subject="Cancelamento agendado - Backstage Pro",
                        idempotency_key=idemp_k,
                        template_name="emails/subscription_cancellation_scheduled",
                        context_data={
                            "user_name": rec_name,
                            "band_name": band.name,
                            "plan_name": subscription.plan_name,
                            "access_until_date": subscription.next_due_date.strftime("%d/%m/%Y") if subscription.next_due_date else "o fim do período",
                            "reactivate_url": f"/bandas/{band.slug}/assinatura/",
                        },
                        related_object_type="BandSubscription",
                        related_object_id=str(subscription.id),
                    )
            except Exception as eq_err:
                logger.error("Erro ao enfileirar email de cancelamento agendado: %s", eq_err)

            messages.success(request, "Cancelamento confirmado. Seu acesso permanece ativo até o fim do período contratado.")
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

    # Banner informativo de pré-renovação de 30 dias para contratos anuais com auto_renew ativo
    alert_pre_renewal = False
    pre_renewal_price_changed = False
    pre_renewal_current_price = None
    pre_renewal_next_price = None
    pre_renewal_date = None

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

        # Status, Inadimplência e Cancelamento
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
                    overdue_limit_date = subscription.next_due_date + timedelta(days=4)
            else:
                status_display = 'Ativo'
        elif subscription.is_canceled_period_expired or (st == 'DESATIVADO' and (subscription.cancel_at_period_end or subscription.billing_cycle == 'ANUAL')):
            status_display = 'Assinatura encerrada'
            can_reactivate = True
        elif st == 'DESATIVADO':
            status_display = 'Inativo'
            can_resubscribe = True
        else:
            status_display = subscription.get_status_display() if hasattr(subscription, 'get_status_display') else subscription.status
            can_resubscribe = True

        # Estados dos botões de ação para assinaturas ativas não suspensas:
        if subscription.status == 'ATIVO' and not subscription.is_financially_suspended:
            # Para planos recorrentes com renovação automática ativa (ex: Mensal), permite cancelar
            # Para compras anuais pré-pagas/parceladas sem recorrência (auto_renew=False), não exibe cancelamento
            if not subscription.cancel_at_period_end and subscription.auto_renew:
                can_cancel = True

            if subscription.billing_cycle == 'ANUAL' and subscription.auto_renew and not subscription.cancel_at_period_end:
                if subscription.next_due_date:
                    from django.utils import timezone
                    from core.models import SystemSettings, AnnualRenewalNotice
                    today = timezone.localdate()
                    diff_days = (subscription.next_due_date - today).days
                    if 0 <= diff_days <= 30:
                        alert_pre_renewal = True
                        pre_renewal_date = subscription.next_due_date
                        pre_renewal_current_price = subscription.contracted_value
                        # Verifica se há aviso com preço congelado ou obtém o preço canônico vigente
                        notice = AnnualRenewalNotice.objects.filter(
                            band_subscription=subscription,
                            renewal_date=subscription.next_due_date
                        ).first()
                        if notice and notice.notified_renewal_price:
                            pre_renewal_next_price = notice.notified_renewal_price
                        else:
                            pre_renewal_next_price = SystemSettings.get_canonical_plan_price(subscription.plan_name, 'ANUAL')

                        if pre_renewal_next_price != pre_renewal_current_price:
                            pre_renewal_price_changed = True

        # BLINDAGEM DE INTERFACE PARA PARCERIA:
        if subscription.is_partnership:
            can_cancel = False
            can_reactivate = False
            can_resubscribe = False
            can_regularize = False
            alert_overdue_tolerance = False
            alert_suspended = False
            alert_pre_renewal = False
            pre_renewal_price_changed = False
            status_display = 'Ativo'
    else:
        can_resubscribe = True

    # 4. Obter forma de pagamento ativa de forma segura e com escopo estrito na assinatura
    active_payment_method = None
    if subscription and not subscription.is_partnership:
        from core.models import GatewayPaymentMethod
        active_payment_method = GatewayPaymentMethod.objects.filter(
            subscription=subscription,
            gateway_provider='ASAAS',
            is_active=True
        ).order_by('-created_at').first()

    # 5. Localizar cobrança pendente/vencida com invoice_url para regularização imediata
    pending_invoice = None
    if subscription and not subscription.is_partnership:
        pending_invoice = subscription.records.filter(
            status='PENDENTE'
        ).exclude(
            gateway_invoice_url__isnull=True
        ).exclude(
            gateway_invoice_url=''
        ).order_by('-due_date', '-created_at').first()

    context = {
        'band': band,
        'subscription': subscription,
        'is_partnership': getattr(subscription, 'is_partnership', False) if subscription else False,
        'faturas': faturas,
        'active_payment_method': active_payment_method,
        'pending_invoice': pending_invoice,
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
        'alert_pre_renewal': alert_pre_renewal,
        'pre_renewal_price_changed': pre_renewal_price_changed,
        'pre_renewal_current_price': pre_renewal_current_price,
        'pre_renewal_next_price': pre_renewal_next_price,
        'pre_renewal_date': pre_renewal_date,
    }

    return render(request, 'core/minha_assinatura.html', context)



@login_required

@band_required

@login_required
@band_required
@advanced_plan_required
@empresario_required
def relatorios_view(request, band_slug):
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários têm acesso ao relatório financeiro.")

    band = get_object_or_404(Band, slug=band_slug)

    shows = Show.objects.filter(
        band=band,
        status__in=Show.STATUS_FINANCIALLY_ELIGIBLE
    ).prefetch_related('payments', 'team_costs').annotate(total_receipts=Sum('receipts__value')).order_by('date')

    general_expenses = BandGeneralExpense.objects.filter(band=band)

    # Filtros
    date_start = request.GET.get('date_start')
    date_end = request.GET.get('date_end')
    contract_type = request.GET.get('contract_type')
    payment_status = request.GET.get('payment_status')

    if date_start:
        shows = shows.filter(date__gte=date_start)
        general_expenses = general_expenses.filter(date__gte=date_start)

    if date_end:
        shows = shows.filter(date__lte=date_end)
        general_expenses = general_expenses.filter(date__lte=date_end)

    if contract_type:
        shows = shows.filter(contract_type__icontains=contract_type)

    if payment_status:
        shows = shows.filter(payment_status=payment_status)

    total_receita = Decimal('0')
    total_custos_shows = Decimal('0')
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
        total_custos_shows += show_custos
        total_recebido_geral += show_recebido

    # Total de Despesas Gerais da Banda
    total_despesas_gerais = sum((g.value for g in general_expenses if g.value), Decimal('0'))
    total_custos = total_custos_shows + total_despesas_gerais

    resultado_previsto_total = total_receita - total_custos
    caixa_realizado_geral = total_recebido_geral - total_custos
    total_pendente_geral = total_receita - total_recebido_geral

    margem_prevista_geral = 0
    if total_receita > 0:
        margem_prevista_geral = (resultado_previsto_total / total_receita) * Decimal('100')

    general_expense_form = BandGeneralExpenseForm(initial={'date': datetime.date.today()})

    context = {
        'band': band,
        'shows': shows,
        'qtd_shows': shows.count(),
        'general_expenses': general_expenses,
        'qtd_general_expenses': general_expenses.count(),
        'total_despesas_gerais': total_despesas_gerais,
        'total_custos_shows': total_custos_shows,
        'total_receita': total_receita,
        'total_custos': total_custos,
        'total_recebido_geral': total_recebido_geral,
        'total_pendente_geral': total_pendente_geral,
        'caixa_realizado_geral': caixa_realizado_geral,
        'resultado_previsto_total': resultado_previsto_total,
        'margem_prevista_geral': margem_prevista_geral,
        'general_expense_form': general_expense_form,
    }

    return render(request, 'core/relatorios.html', context)


@login_required
@band_required
@advanced_plan_required
@empresario_required
def general_expense_create_view(request, band_slug):
    """
    BP-PEND-77: Criação de Despesa Geral da Banda sem vínculo com Show.
    """
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários podem cadastrar despesas gerais da banda.")

    band = get_object_or_404(Band, slug=band_slug)

    if request.method == 'POST':
        form = BandGeneralExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.band = band
            expense.created_by = request.user
            expense.save()
            messages.success(request, f"Despesa geral '{expense.description}' cadastrada com sucesso!")
        else:
            messages.error(request, f"Erro ao cadastrar despesa geral: {form.errors.as_text()}")

    # Redireciona preservando parâmetros GET de filtro caso existam
    redirect_url = reverse('relatorio_financeiro', args=[band.slug])
    query_string = request.META.get('QUERY_STRING')
    if query_string:
        redirect_url = f"{redirect_url}?{query_string}"
    return redirect(redirect_url)


@login_required
@band_required
@advanced_plan_required
@empresario_required
def general_expense_edit_view(request, band_slug, pk):
    """
    BP-PEND-77: Edição de Despesa Geral da Banda.
    """
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários podem editar despesas gerais da banda.")

    band = get_object_or_404(Band, slug=band_slug)
    expense = get_object_or_404(BandGeneralExpense, pk=pk, band=band)

    if request.method == 'POST':
        form = BandGeneralExpenseForm(request.POST, request.FILES, instance=expense)
        if form.is_valid():
            # Se não enviou novo arquivo, manter o existente
            if not request.FILES.get('file') and expense.file:
                form.instance.file = expense.file
            form.save()
            messages.success(request, f"Despesa geral '{expense.description}' atualizada com sucesso!")
        else:
            messages.error(request, f"Erro ao atualizar despesa geral: {form.errors.as_text()}")

    redirect_url = reverse('relatorio_financeiro', args=[band.slug])
    query_string = request.META.get('QUERY_STRING')
    if query_string:
        redirect_url = f"{redirect_url}?{query_string}"
    return redirect(redirect_url)


@login_required
@band_required
@advanced_plan_required
@empresario_required
def general_expense_delete_view(request, band_slug, pk):
    """
    BP-PEND-77: Exclusão de Despesa Geral da Banda.
    """
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários podem excluir despesas gerais da banda.")

    band = get_object_or_404(Band, slug=band_slug)
    expense = get_object_or_404(BandGeneralExpense, pk=pk, band=band)

    if request.method == 'POST':
        desc = expense.description
        if expense.file:
            try:
                if os.path.isfile(expense.file.path):
                    os.remove(expense.file.path)
            except Exception:
                pass
        expense.delete()
        messages.success(request, f"Despesa geral '{desc}' excluída com sucesso!")

    redirect_url = reverse('relatorio_financeiro', args=[band.slug])
    query_string = request.META.get('QUERY_STRING')
    if query_string:
        redirect_url = f"{redirect_url}?{query_string}"
    return redirect(redirect_url)


def _compute_financial_aggregates(band, date_start=None, date_end=None, payment_status=None):
    """
    Função utilitária compartilhada para consolidar indicadores e séries mensais
    respeitando as regras operacionais e de elegibilidade do sistema (Show.STATUS_FINANCIALLY_ELIGIBLE)
    e incluindo Despesas Gerais da Banda (BP-PEND-77).
    """
    from decimal import Decimal
    from collections import defaultdict
    import datetime

    shows_qs = Show.objects.filter(
        band=band,
        status__in=Show.STATUS_FINANCIALLY_ELIGIBLE
    ).prefetch_related('payments', 'team_costs', 'receipts').order_by('date')

    general_expenses_qs = BandGeneralExpense.objects.filter(band=band).order_by('date')

    if date_start:
        try:
            d_start = datetime.datetime.strptime(date_start, '%Y-%m-%d').date()
            shows_qs = shows_qs.filter(date__gte=d_start)
            general_expenses_qs = general_expenses_qs.filter(date__gte=d_start)
        except ValueError:
            pass

    if date_end:
        try:
            d_end = datetime.datetime.strptime(date_end, '%Y-%m-%d').date()
            shows_qs = shows_qs.filter(date__lte=d_end)
            general_expenses_qs = general_expenses_qs.filter(date__lte=d_end)
        except ValueError:
            pass

    if payment_status:
        shows_qs = shows_qs.filter(payment_status=payment_status)

    today = datetime.date.today()

    total_faturamento = Decimal('0')
    total_recebido = Decimal('0')
    total_custos_logistica = Decimal('0')
    total_custos_equipe = Decimal('0')
    total_em_atraso = Decimal('0')

    # Agrupamentos mensais: chave "YYYY-MM"
    monthly_data = defaultdict(lambda: {
        'faturamento': Decimal('0'),
        'recebido': Decimal('0'),
        'a_receber': Decimal('0'),
        'custos': Decimal('0'),
    })

    # Status de shows
    status_counts = {'PAGO': 0, 'PARCIAL': 0, 'PENDENTE': 0}

    # Shows com dados processados para tabelas
    processed_shows = []

    for s in shows_qs:
        fee = s.fee or Decimal('0')
        logistica = sum((r.value for r in s.receipts.all() if r.value), Decimal('0'))
        equipe = sum((t.value for t in s.team_costs.all() if t.value), Decimal('0'))
        custos_show = logistica + equipe

        rec = sum((p.value for p in s.payments.all() if p.status == 'RECEBIDO' and p.value), Decimal('0'))
        pend = fee - rec
        if pend < Decimal('0'):
            pend = Decimal('0')

        # Verificação de pagamentos em atraso do show
        for p in s.payments.all():
            if p.status == 'ATRASADO' and p.value:
                total_em_atraso += p.value
            elif p.status == 'PENDENTE' and p.expected_date and p.expected_date < today and p.value:
                total_em_atraso += p.value

        # Status count
        if s.payment_status in status_counts:
            status_counts[s.payment_status] += 1
        else:
            status_counts['PENDENTE'] += 1

        total_faturamento += fee
        total_recebido += rec
        total_custos_logistica += logistica
        total_custos_equipe += equipe

        # Dados mensais pelo mês do show (se tiver data)
        if s.date:
            month_key = s.date.strftime('%Y-%m')
            monthly_data[month_key]['faturamento'] += fee
            monthly_data[month_key]['recebido'] += rec
            monthly_data[month_key]['a_receber'] += pend
            monthly_data[month_key]['custos'] += custos_show

        s.computed_fee = fee
        s.computed_logistica = logistica
        s.computed_equipe = equipe
        s.computed_custos = custos_show
        s.computed_recebido = rec
        s.computed_pendente = pend
        s.computed_resultado = fee - custos_show
        s.computed_caixa_realizado = rec - custos_show
        processed_shows.append(s)

    # Processar despesas gerais da banda nos agrupamentos mensais e custos totais
    total_despesas_gerais = Decimal('0')
    for g in general_expenses_qs:
        g_val = g.value or Decimal('0')
        total_despesas_gerais += g_val
        if g.date:
            m_key = g.date.strftime('%Y-%m')
            monthly_data[m_key]['custos'] += g_val

    total_custos_shows = total_custos_logistica + total_custos_equipe
    total_custos_geral = total_custos_shows + total_despesas_gerais
    total_a_receber = total_faturamento - total_recebido
    if total_a_receber < Decimal('0'):
        total_a_receber = Decimal('0')

    resultado_previsto = total_faturamento - total_custos_geral
    caixa_realizado = total_recebido - total_custos_geral

    # Organizar séries mensais ordenadas
    sorted_months = sorted(monthly_data.keys())
    chart_months_labels = []
    chart_faturamento_data = []
    chart_recebido_data = []
    chart_a_receber_data = []
    chart_custos_data = []

    MESES_ABREV = {
        1: 'Jan', 2: 'Fev', 3: 'Mar', 4: 'Abr', 5: 'Mai', 6: 'Jun',
        7: 'Jul', 8: 'Ago', 9: 'Set', 10: 'Out', 11: 'Nov', 12: 'Dez'
    }

    for m_key in sorted_months:
        y, m = m_key.split('-')
        label = f"{MESES_ABREV.get(int(m), m)}/{y[2:]}"
        chart_months_labels.append(label)
        chart_faturamento_data.append(float(monthly_data[m_key]['faturamento']))
        chart_recebido_data.append(float(monthly_data[m_key]['recebido']))
        chart_a_receber_data.append(float(monthly_data[m_key]['a_receber']))
        chart_custos_data.append(float(monthly_data[m_key]['custos']))

    # Top 10 shows por cachê/faturamento
    top_shows = sorted(processed_shows, key=lambda x: x.computed_fee, reverse=True)[:10]
    chart_top_shows_labels = [s.event_name or s.title or f"Show {s.date.strftime('%d/%m') if s.date else s.id}" for s in top_shows]
    chart_top_shows_data = [float(s.computed_fee) for s in top_shows]

    return {
        'shows_qs': shows_qs,
        'general_expenses_qs': general_expenses_qs,
        'processed_shows': processed_shows,
        'total_faturamento': total_faturamento,
        'total_recebido': total_recebido,
        'total_a_receber': total_a_receber,
        'total_em_atraso': total_em_atraso,
        'total_custos_logistica': total_custos_logistica,
        'total_custos_equipe': total_custos_equipe,
        'total_custos_shows': total_custos_shows,
        'total_despesas_gerais': total_despesas_gerais,
        'total_custos_geral': total_custos_geral,
        'resultado_previsto': resultado_previsto,
        'caixa_realizado': caixa_realizado,
        'status_counts': status_counts,
        'chart_months_labels': chart_months_labels,
        'chart_faturamento_data': chart_faturamento_data,
        'chart_recebido_data': chart_recebido_data,
        'chart_a_receber_data': chart_a_receber_data,
        'chart_custos_data': chart_custos_data,
        'chart_top_shows_labels': chart_top_shows_labels,
        'chart_top_shows_data': chart_top_shows_data,
    }



@login_required
@band_required
@advanced_plan_required
@empresario_required
def relatorio_financeiro_graficos_view(request, band_slug):
    """
    BP-PEND-64: Nova página analítica com cards consolidados e gráficos visuais (Chart.js)
    isolada da tabela operacional do Financeiro.
    """
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários têm acesso aos gráficos financeiros.")

    band = get_object_or_404(Band, slug=band_slug)
    date_start = request.GET.get('date_start', '')
    date_end = request.GET.get('date_end', '')
    payment_status = request.GET.get('payment_status', '')

    data = _compute_financial_aggregates(band, date_start, date_end, payment_status)

    context = {
        'band': band,
        'date_start': date_start,
        'date_end': date_end,
        'payment_status': payment_status,
        **data,
    }
    return render(request, 'core/financeiro/graficos.html', context)


@login_required
@band_required
@advanced_plan_required
@empresario_required
def relatorio_financeiro_graficos_export_view(request, band_slug):
    """
    BP-PEND-64: Página otimizada para impressão/PDF da visão de Gráficos e Indicadores,
    com cabeçalho da banda, data/hora de geração, botões de ação e rodapé padrão.
    """
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários têm acesso à exportação dos gráficos.")

    band = get_object_or_404(Band, slug=band_slug)
    date_start = request.GET.get('date_start', '')
    date_end = request.GET.get('date_end', '')
    payment_status = request.GET.get('payment_status', '')

    data = _compute_financial_aggregates(band, date_start, date_end, payment_status)
    user_name = request.user.get_full_name() or request.user.username

    context = {
        'band': band,
        'date_start': date_start,
        'date_end': date_end,
        'payment_status': payment_status,
        'pdf_logo_base64': get_image_base64(band.logo),
        'user_name': user_name,
        **data,
    }
    return render(request, 'core/financeiro/graficos_export_pdf.html', context)


@login_required
@band_required
@advanced_plan_required
@empresario_required
def relatorio_financeiro_pdf_view(request, band_slug):
    """
    BP-PEND-64: Geração sob demanda de 5 tipos de relatórios financeiros diagramados em PDF:
    1. Resumo Financeiro
    2. Contas a Receber
    3. Recebimentos
    4. Resultado por Show
    5. Fechamento do Período
    """
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários têm acesso aos relatórios em PDF.")

    band = get_object_or_404(Band, slug=band_slug)
    date_start = request.GET.get('date_start', '')
    date_end = request.GET.get('date_end', '')
    report_type = request.GET.get('report_type', 'resumo')

    data = _compute_financial_aggregates(band, date_start, date_end)
    user_name = request.user.get_full_name() or request.user.username

    # Montar listagens específicas por tipo
    a_receber_items = []
    recebimentos_items = []

    for s in data['processed_shows']:
        # 1. Parcelas registradas em ShowPayment
        has_pending_payment = False
        sum_pending_payments = Decimal('0')

        for p in s.payments.all():
            if p.status in ['PENDENTE', 'ATRASADO']:
                has_pending_payment = True
                val = p.value or Decimal('0')
                sum_pending_payments += val
                a_receber_items.append({
                    'show': s,
                    'payment': p,
                    'description': p.description or 'Parcela pendente',
                    'payment_method_display': p.get_payment_method_display(),
                    'value': val,
                    'expected_date': p.expected_date,
                    'is_overdue': (p.status == 'ATRASADO') or (p.expected_date and p.expected_date < datetime.date.today()),
                })
            elif p.status == 'RECEBIDO':
                recebimentos_items.append({
                    'show': s,
                    'payment': p,
                })

        # 2. Se o show possui saldo pendente (computed_pendente > 0)
        # e não possui parcelas pendentes cadastradas cobrindo esse saldo,
        # adiciona item sintético com o saldo a receber do show
        if s.computed_pendente > Decimal('0'):
            saldo_remanescente = s.computed_pendente - sum_pending_payments
            if not has_pending_payment or saldo_remanescente > Decimal('0'):
                valor_item = saldo_remanescente if has_pending_payment else s.computed_pendente
                is_show_overdue = bool(s.date and s.date < datetime.date.today())
                a_receber_items.append({
                    'show': s,
                    'payment': None,
                    'description': 'Saldo a receber do cachê' if has_pending_payment else 'Cachê a receber (a faturar)',
                    'payment_method_display': s.contract_type or 'A combinar',
                    'value': valor_item,
                    'expected_date': s.date,
                    'is_overdue': is_show_overdue,
                })

    # Ordenar parcelas a receber por data prevista (asc)
    a_receber_items.sort(key=lambda x: (x['expected_date'] or datetime.date.max, x['show'].id))

    # Total consolidado exato dos itens a receber listados
    total_a_receber_relatorio = sum((item['value'] for item in a_receber_items), Decimal('0'))

    # Ordenar recebimentos por data de recebimento ou criação (desc)
    recebimentos_items.sort(
        key=lambda x: (x['payment'].receipt_date or x['payment'].expected_date or datetime.date.min),
        reverse=True
    )

    report_titles = {
        'resumo': ('RESUMO FINANCEIRO', 'Visão consolidada de faturamento, recebimentos e custos'),
        'a_receber': ('CONTAS A RECEBER', 'Detalhamento de parcelas pendentes e atrasadas'),
        'recebimentos': ('RECEBIMENTOS EFETIVADOS', 'Histórico detalhado de pagamentos recebidos no período'),
        'resultado_show': ('RESULTADO POR SHOW', 'Discriminação de cachês, equipe, logística e lucro por show'),
        'fechamento': ('FECHAMENTO DO PERÍODO', 'Demonstrativo e conciliação de caixa do período selecionado'),
    }

    doc_title, doc_subtitle = report_titles.get(report_type, ('RELATÓRIO FINANCEIRO', 'Demonstrativo do Período'))

    context = {
        'band': band,
        'report_type': report_type,
        'doc_title': doc_title,
        'doc_subtitle': doc_subtitle,
        'date_start': date_start,
        'date_end': date_end,
        'user_name': user_name,
        'pdf_logo_base64': get_image_base64(band.logo),
        'a_receber_items': a_receber_items,
        'recebimentos_items': recebimentos_items,
        'total_a_receber_relatorio': total_a_receber_relatorio,
        **data,
    }
    return render(request, 'core/financeiro/financeiro_pdf.html', context)


@login_required
@band_required
@advanced_plan_required
@empresario_required
def commercial_index_view(request, band_slug):
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários têm acesso ao módulo Comercial.")

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
@empresario_required
def commercial_save_view(request, band_slug, pk=None):
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários podem cadastrar ou editar orçamentos.")

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

        from core.services.commercial_sync import sync_proposal_to_show, map_phase_to_show_status
        if proposal.show:
            sync_proposal_to_show(proposal, actor=request.user)
        else:
            # Caso raro de criação sem show vinculado via commercial_save_view
            target_status = map_phase_to_show_status(proposal.phase)
            new_show = Show.objects.create(
                band=band,
                title=proposal.name,
                date=proposal.date,
                show_time=proposal.time,
                status=target_status,
                fee=proposal.fee,
                venue=proposal.location,
                contractor_phone=proposal.contact,
                contractor_name=proposal.contact_name
            )
            proposal.show = new_show
            proposal.save(update_fields=['show'])
            schedule_show_notifications(old_show=None, new_show=new_show, actor=request.user, is_creation=True)

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
@empresario_required
def commercial_pdf_view(request, band_slug):
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários podem exportar a agenda comercial.")

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
@empresario_required
def commercial_delete_view(request, band_slug, pk):
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários podem excluir solicitações.")

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
@empresario_required
def commercial_delete_document_view(request, band_slug, pk, doc_pk):
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Apenas empresários podem excluir anexos.")

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
@empresario_required
def commercial_check_conflict_view(request, band_slug):
    if not (request.user.is_superuser or request.user.is_empresario(request.band)):
        return HttpResponseForbidden("Acesso restrito ao perfil de Empresário.")

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

    # Processamento do Modal Global de Upload de Documento (BP-PEND-69: Exclusivo para ContractDocument)
    if request.method == 'POST' and request.POST.get('action') == 'add_file_global':
        show_id = request.POST.get('show_id')
        description = request.POST.get('description', '').strip()
        uploaded_file = request.FILES.get('file')

        if not show_id:
            messages.error(request, "Por favor, selecione um show.")
            return redirect('arquivos', band_slug=band.slug)

        show = get_object_or_404(Show, pk=show_id, band=band)

        if not description:
            messages.error(request, "A descrição do documento é obrigatória.")
            return redirect('arquivos', band_slug=band.slug)

        if not uploaded_file:
            messages.error(request, "Nenhum arquivo selecionado para upload.")
            return redirect('arquivos', band_slug=band.slug)

        try:
            from core.file_policy import validate_file_size_and_type, check_show_limits
            from django.core.exceptions import ValidationError

            # 1. Valida tamanho individual e tipo/extensão
            validate_file_size_and_type(uploaded_file)

            # 2. Valida quota de documentos por show (7 documentos e 35 MB total)
            check_show_limits(show, [uploaded_file.size])

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
            messages.error(request, f"Erro ao salvar documento: {str(e)}")

        return redirect('arquivos', band_slug=band.slug)

    from core.file_policy import MAX_SHOW_FILES, MAX_FILE_SIZE_MB, MAX_SHOW_STORAGE_MB
    from django.db.models import Q
    from django.utils import timezone
    from collections import OrderedDict
    import datetime

    # 1. Shows disponíveis para o modal de novo documento (lista leve sem loops de storage)
    all_band_shows = Show.objects.filter(band=band).order_by('-date', 'title').only('id', 'title', 'date', 'city')

    # 2. Shows que possuem ao menos 1 arquivo (documentos, comprovantes de despesas ou comprovantes de recebimentos)
    shows_with_files_qs = Show.objects.filter(
        band=band
    ).filter(
        Q(documents__isnull=False) |
        Q(receipts__file__isnull=False) |
        Q(payments__file__isnull=False) & ~Q(payments__file='')
    ).distinct().prefetch_related(
        'documents',
        'receipts',
        'payments'
    ).order_by('-date', 'title')

    # 3. Construção da hierarquia: Ano -> Mês -> Lista de Shows
    # Nomes dos meses em português
    MONTH_NAMES = {
        1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril',
        5: 'Maio', 6: 'Junho', 7: 'Julho', 8: 'Agosto',
        9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'
    }

    now = timezone.localdate()
    current_year = now.year
    current_month = now.month

    # Estrutura: years_data = { 2026: { 'months': { 9: { 'name': 'Setembro', 'shows': [...] } } } }
    years_dict = OrderedDict()
    all_filtered_shows_list = []

    for s in shows_with_files_qs:
        # Filtra comprovantes de recebimentos com arquivo em memória (já com prefetch)
        payment_files = [p for p in s.payments.all() if p.file]
        receipt_files = [r for r in s.receipts.all() if r.file]
        doc_files = list(s.documents.all())

        # Se por algum motivo não houver nenhum arquivo real, ignora
        if not doc_files and not receipt_files and not payment_files:
            continue

        s.prefetched_doc_files = doc_files
        s.prefetched_receipt_files = receipt_files
        s.prefetched_payment_files = payment_files
        s.total_files_count = len(doc_files) + len(receipt_files) + len(payment_files)

        all_filtered_shows_list.append(s)

        s_date = s.date or datetime.date(2000, 1, 1)
        s_year = s_date.year
        s_month = s_date.month

        if s_year not in years_dict:
            years_dict[s_year] = {
                'year': s_year,
                'is_current_year': (s_year == current_year),
                'total_files': 0,
                'months': OrderedDict()
            }

        if s_month not in years_dict[s_year]['months']:
            years_dict[s_year]['months'][s_month] = {
                'month_num': s_month,
                'month_name': MONTH_NAMES.get(s_month, f'Mês {s_month}'),
                'is_current_month': (s_year == current_year and s_month == current_month),
                'total_files': 0,
                'shows': []
            }

        years_dict[s_year]['months'][s_month]['shows'].append(s)
        years_dict[s_year]['months'][s_month]['total_files'] += s.total_files_count
        years_dict[s_year]['total_files'] += s.total_files_count

    # Converte dicionários ordenados em listas para iteração limpa e estável nos templates
    years_tree = []
    for y_key, y_val in years_dict.items():
        months_list = list(y_val['months'].values())
        # Ordena meses do mais recente para o mais antigo dentro do ano
        months_list.sort(key=lambda m: m['month_num'], reverse=True)
        y_val['months_list'] = months_list
        years_tree.append(y_val)

    # Ordena anos do mais recente para o mais antigo
    years_tree.sort(key=lambda y: y['year'], reverse=True)

    context = {
        'band': band,
        'years_tree': years_tree,
        'shows': all_filtered_shows_list,
        'all_band_shows': all_band_shows,
        'current_year': current_year,
        'current_month': current_month,
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

    from core.models import GoogleCalendarIntegration
    google_calendar_integration = GoogleCalendarIntegration.objects.filter(band=band).first()

    context = {
        'band': band,
        'google_calendar_integration': google_calendar_integration,
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



    is_emp = request.user.is_superuser or request.user.is_empresario(band)

    if request.method == 'POST':

        form = ShowForm(request.POST, request.FILES)

        if (not band.is_advanced) or (not is_emp):
            for f in ['contractor_name', 'contractor_phone', 'contract_type', 'fee', 'payment_status']:
                form.fields.pop(f, None)

        link_commercial = request.POST.get('link_commercial') == '1' and is_emp

        if form.is_valid():

            with transaction.atomic():

                show = form.save(commit=False)

                show.band = band

                # Criação mantém notification_revision=0

                show.save()

                if band.is_advanced and link_commercial:
                    from core.services.commercial_sync import link_show_to_commercial
                    link_show_to_commercial(show, user=request.user)

                # Agenda notificação de NEW_SHOW

                from core.services.show_notifications import schedule_show_notifications

                schedule_show_notifications(old_show=None, new_show=show, actor=request.user, is_creation=True)

                # Google Calendar (BP-PEND-48)
                from core.services.google_calendar import sync_show_to_google_calendar
                transaction.on_commit(lambda s=show: sync_show_to_google_calendar(s, request=request))



            messages.success(request, "Show adicionado com sucesso!")

            if 'save_and_continue' in request.POST:

                return redirect('shows_edit', band_slug=band.slug, pk=show.id)

            return redirect('calendario', band_slug=band.slug)

    else:
        link_commercial = False
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
        if (not band.is_advanced) or (not is_emp):
            for f in ['contractor_name', 'contractor_phone', 'contract_type', 'fee', 'payment_status']:
                form.fields.pop(f, None)
    context = {

        'band': band,

        'form': form,

        'is_edit': False,

        'link_commercial': link_commercial,

        'is_empresario': is_emp,

    }

    return render(request, 'core/show_form.html', context)



@login_required

@band_required

def show_edit_view(request, band_slug, pk):

    if not request.user.is_produtor():

        return HttpResponseForbidden("Apenas produtores podem editar shows.")



    band = get_object_or_404(Band, slug=band_slug)

    show_to_edit = get_object_or_404(Show, pk=pk, band=band)

    is_emp = request.user.is_superuser or request.user.is_empresario(band)

    if request.method == 'POST':

        with transaction.atomic():

            # Bloqueio concorrente

            show_to_edit = Show.objects.select_for_update().get(pk=pk, band=band)



            # Snapshot antigo

            old_date = show_to_edit.date

            old_show_time = show_to_edit.show_time

            old_status = show_to_edit.status

            # Se não for empresário, preserva os dados comerciais existentes
            preserved_contractor_name = show_to_edit.contractor_name
            preserved_contractor_phone = show_to_edit.contractor_phone
            preserved_contract_type = show_to_edit.contract_type
            preserved_fee = show_to_edit.fee
            preserved_payment_status = show_to_edit.payment_status

            form = ShowForm(request.POST, request.FILES, instance=show_to_edit)
            if (not band.is_advanced) or (not is_emp):
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
                            'files_size_mb': round(files_size / 1024 / 1024, 2) if files_size else 0,
                            'is_empresario': is_emp,
                        }
                        return render(request, 'core/show_form.html', context)

                # Detectar eventos relevantes

                new_date = form.cleaned_data.get('date')

                new_show_time = form.cleaned_data.get('show_time')

                new_status = form.cleaned_data.get('status')



                has_relevant_event = (
                    (old_date != new_date and old_status != 'PRE_RESERVADO' and new_status != 'PRE_RESERVADO') or
                    (old_show_time != new_show_time and old_status == 'CONFIRMADO' and new_status != 'PRE_RESERVADO') or
                    (old_status == 'CONFIRMADO' and new_status == 'CANCELADO') or
                    (old_status != 'CONFIRMADO' and new_status == 'CONFIRMADO')
                )

                if has_relevant_event:

                    show_to_edit.notification_revision += 1



                saved_show = form.save(commit=False)
                if not is_emp:
                    saved_show.contractor_name = preserved_contractor_name
                    saved_show.contractor_phone = preserved_contractor_phone
                    saved_show.contract_type = preserved_contract_type
                    saved_show.fee = preserved_fee
                    saved_show.payment_status = preserved_payment_status
                saved_show.save()
                form.save_m2m()

                if doc_formset:
                    doc_formset.save()

                from core.services import room_list_services
                room_list_services.sync_room_list_from_show(show_to_edit)



                if has_relevant_event:
                    from core.services.show_notifications import schedule_show_notifications
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

                if band.is_advanced:
                    from core.services.commercial_sync import sync_show_to_proposal
                    sync_show_to_proposal(show_to_edit, actor=request.user)

                # Google Calendar (BP-PEND-48)
                from core.services.google_calendar import sync_show_to_google_calendar
                transaction.on_commit(lambda s=show_to_edit: sync_show_to_google_calendar(s, request=request))

                messages.success(request, "Show atualizado com sucesso!")

                if 'save_and_continue' in request.POST:
                    active_tab = request.POST.get('active_tab', '#geral')
                    url = reverse('shows_edit', kwargs={'band_slug': band.slug, 'pk': show_to_edit.id})
                    return redirect(f"{url}{active_tab}")

                return redirect('calendario', band_slug=band.slug)

    else:

        form = ShowForm(instance=show_to_edit)
        if (not band.is_advanced) or (not is_emp):
            for f in ['contractor_name', 'contractor_phone', 'contract_type', 'fee', 'payment_status']:
                form.fields.pop(f, None)
        if (not band.is_advanced) or (not is_emp):
            doc_formset = None
        else:
            doc_formset = ContractDocumentFormSet(instance=show_to_edit)



    from core.file_policy import get_show_files_info
    files_count, files_size = get_show_files_info(show_to_edit)

    from core.models import CommercialProposal
    is_linked_commercial = CommercialProposal.objects.filter(show=show_to_edit).exists()

    context = {
        'band': band,
        'form': form,
        'is_edit': True,
        'show_to_edit': show_to_edit,
        'doc_formset': doc_formset,
        'files_count': files_count,
        'files_size_mb': round(files_size / 1024 / 1024, 2) if files_size else 0,
        'is_linked_commercial': is_linked_commercial,
        'is_empresario': is_emp,
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
@advanced_plan_required
def show_link_commercial_view(request, band_slug, pk):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores podem vincular shows ao comercial.")

    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    band = request.band
    show = get_object_or_404(Show, pk=pk, band=band)

    from core.services.commercial_sync import link_show_to_commercial
    proposal, created = link_show_to_commercial(show, user=request.user)

    is_ajax = (
        request.headers.get('x-requested-with') == 'XMLHttpRequest' or
        request.content_type == 'application/json' or
        'application/json' in request.headers.get('accept', '')
    )

    if is_ajax:
        from django.http import JsonResponse
        return JsonResponse({
            'ok': True,
            'linked': True,
            'proposal_id': proposal.id,
            'created': created,
            'message': 'Show vinculado ao Comercial com sucesso!'
        })

    messages.success(request, "Show vinculado ao Comercial com sucesso!")
    return redirect('shows_edit', band_slug=band.slug, pk=show.id)



def build_whatsapp_access_data(band=None, user=None, raw_password="", is_admin_created=False):
    import re
    from urllib.parse import quote

    phone_raw = (user.phone or '').strip() if user else ''
    digits = re.sub(r'\D', '', phone_raw)
    phone_normalized = ''

    if digits:
        if len(digits) in (10, 11):
            phone_normalized = '55' + digits
        elif len(digits) in (12, 13) and digits.startswith('55'):
            phone_normalized = digits
        else:
            phone_normalized = digits

    user_name = (user.first_name if user else '') or (user.username if user else '')
    username = user.username if user else ''
    band_obj = band or (user.band if user else None)

    # Usando escapes Unicode para garantir consistencia independente de encoding do arquivo/SO
    w_hand = "\U0001F44B"
    w_link = "\U0001F517"
    w_user = "\U0001F464"
    w_key = "\U0001F511"

    if is_admin_created:
        # Prioridade de link no Painel Admin Geral:
        # 1. Se possuir banda vinculada: https://backstagepro.site/[band.slug]/login/
        # 2. Se is_staff ou sem banda: https://backstagepro.site/painel/login/
        if band_obj:
            login_url = f"https://backstagepro.site/{band_obj.slug}/login/"
            intro_text = f"Sua conta foi criada e você já pode acessar o painel da banda *{band_obj.name}*."
        else:
            login_url = "https://backstagepro.site/painel/login/"
            intro_text = "Sua conta de acesso ao Painel Administrativo Geral foi criada."

        message_text = (
            f"Olá, {user_name}! {w_hand}\n\n"
            f"Seja bem-vindo ao Backstage Pro!\n\n"
            f"{intro_text}\n\n"
            f"{w_link} *Acesso:*\n"
            f"{login_url}\n\n"
            f"{w_user} *Login:* {username}\n\n"
            f"{w_key} *Senha provisória:* {raw_password}\n\n"
            f"No primeiro acesso, o sistema solicitará que você crie uma nova senha pessoal.\n\n"
            f"Backstage Pro\n"
            f"Gestão profissional para bandas e artistas."
        )
    else:
        # Mensagem padrão do cadastro de integrantes no painel da banda
        band_slug = band_obj.slug if band_obj else ''
        band_name = band_obj.name if band_obj else ''
        login_url = f"https://backstagepro.site/{band_slug}/login/"

        message_text = (
            f"Olá, {user_name}! {w_hand}\n\n"
            f"Você foi cadastrado no painel da banda *{band_name}* no Backstage Pro.\n\n"
            f"Segue abaixo seus dados para acesso:\n\n"
            f"{w_link} *Acesso:*\n"
            f"{login_url}\n\n"
            f"{w_user} *Login:* {username}\n\n"
            f"{w_key} *Senha provisória:* {raw_password}\n\n"
            f"No primeiro acesso, o sistema solicitará que você crie uma nova senha pessoal.\n\n"
            f"Backstage Pro\n"
            f"Gestão profissional para bandas e artistas."
        )

    whatsapp_url = ""
    whatsapp_mobile_url = ""
    whatsapp_app_url = ""
    whatsapp_web_url = ""
    if phone_normalized:
        encoded_text = quote(message_text, safe='')
        whatsapp_mobile_url = f"https://wa.me/{phone_normalized}?text={encoded_text}"
        whatsapp_app_url = f"whatsapp://send?phone={phone_normalized}&text={encoded_text}"
        whatsapp_web_url = f"https://web.whatsapp.com/send?phone={phone_normalized}&text={encoded_text}"
        whatsapp_url = whatsapp_mobile_url

    return {
        'has_phone': bool(phone_normalized),
        'whatsapp_url': whatsapp_url,
        'whatsapp_mobile_url': whatsapp_mobile_url,
        'whatsapp_app_url': whatsapp_app_url,
        'whatsapp_web_url': whatsapp_web_url,
    }


def build_whatsapp_charge_data(responsible_name, band_name, plan_type, billing_cycle, amount_str, checkout_url, phone=""):
    """
    BP-PEND-61: Constrói mensagem e links (mobile, app, web) para compartilhamento de cobrança via WhatsApp.
    Preserva emojis Unicode e formatação canônica de cobrança por banda.
    """
    import re
    from urllib.parse import quote

    phone_raw = (phone or '').strip()
    digits = re.sub(r'\D', '', phone_raw)
    phone_normalized = ''

    if digits:
        if len(digits) in (10, 11):
            phone_normalized = '55' + digits
        elif len(digits) in (12, 13) and digits.startswith('55'):
            phone_normalized = digits
        else:
            phone_normalized = digits

    # Escapes Unicode para garantir consistência e evitar problemas de encoding
    w_hand = "\U0001F44B"
    w_mic = "\U0001F3A4"
    w_box = "\U0001F4E6"
    w_cycle = "\U0001F504"
    w_money = "\U0001F4B0"
    w_link = "\U0001F517"

    resp_name = (responsible_name or '').strip() or 'Cliente'
    b_name = (band_name or '').strip()

    p_upper = (plan_type or '').strip().upper()
    plan_display = 'AVANÇADO' if 'AVANC' in p_upper else 'BÁSICO'

    c_upper = (billing_cycle or '').strip().upper()
    cycle_display = 'ANUAL' if 'ANUAL' in c_upper else 'MENSAL'

    val_display = str(amount_str).strip()

    message_text = (
        f"Olá, {resp_name}! {w_hand}\n\n"
        f"Segue o link de pagamento referente à assinatura do Backstage Pro:\n\n"
        f"{w_mic} *Banda:* {b_name}\n"
        f"{w_box} *Plano:* {plan_display}\n"
        f"{w_cycle} *Ciclo:* {cycle_display}\n"
        f"{w_money} *Valor:* R$ {val_display}\n\n"
        f"{w_link} *Link para pagamento:*\n"
        f"{checkout_url}\n\n"
        f"Após a confirmação do pagamento, a assinatura desta banda será atualizada automaticamente.\n\n"
        f"Backstage Pro\n"
        f"Gestão profissional para bandas e artistas."
    )

    whatsapp_url = ""
    whatsapp_mobile_url = ""
    whatsapp_app_url = ""
    whatsapp_web_url = ""

    if phone_normalized:
        encoded_text = quote(message_text, safe='')
        whatsapp_mobile_url = f"https://wa.me/{phone_normalized}?text={encoded_text}"
        whatsapp_app_url = f"whatsapp://send?phone={phone_normalized}&text={encoded_text}"
        whatsapp_web_url = f"https://web.whatsapp.com/send?phone={phone_normalized}&text={encoded_text}"
        whatsapp_url = whatsapp_mobile_url

    return {
        'has_phone': bool(phone_normalized),
        'phone_normalized': phone_normalized,
        'message_text': message_text,
        'whatsapp_url': whatsapp_url,
        'whatsapp_mobile_url': whatsapp_mobile_url,
        'whatsapp_app_url': whatsapp_app_url,
        'whatsapp_web_url': whatsapp_web_url,
    }


def build_admin_user_whatsapp_access_data(user, raw_password="", is_provisional=False):
    """
    BP-PEND-ADMIN: Prepara a mensagem amigável e profissional e links do WhatsApp
    para compartilhamento de credenciais provisórias pelo Admin Geral.
    Adapta para zero, uma ou múltiplas bandas vinculadas e explica o multilogin.
    """
    import re
    from urllib.parse import quote

    phone_raw = (user.phone or '').strip() if user else ''
    digits = re.sub(r'\D', '', phone_raw)
    phone_normalized = ''

    if digits:
        if len(digits) in (10, 11):
            phone_normalized = '55' + digits
        elif len(digits) in (12, 13) and digits.startswith('55'):
            phone_normalized = digits
        else:
            phone_normalized = digits

    user_name = (user.first_name if user else '') or (user.username if user else '')
    username = user.username if user else ''

    # Bandas vinculadas
    band_names = []
    if user:
        membs = list(user.band_memberships.filter(is_active=True, band__is_active=True).select_related('band').order_by('band__name'))
        if membs:
            band_names = [m.band.name for m in membs]
        elif user.band:
            band_names = [user.band.name]

    # Resolução da URL de Login central canônica (BP-PEND-71)
    from django.urls import reverse
    login_path = reverse('central_login')
    login_url = f"https://backstagepro.site{login_path}"

    # Emojis Unicode seguros
    w_hand = "\U0001F44B"
    w_music = "\U0001F3B6"
    w_rocket = "\U0001F680"
    w_link = "\U0001F517"
    w_user = "\U0001F464"
    w_key = "\U0001F510"
    w_mic = "\U0001F3A4"

    # Bloco de bandas
    if len(band_names) == 0:
        bandas_bloco = ""
        multilogin_bloco = ""
    elif len(band_names) == 1:
        bandas_bloco = f"{w_mic} Banda vinculada: {band_names[0]}\n\n"
        multilogin_bloco = "Com esse mesmo login e senha, você poderá acessar o sistema Backstage Pro.\n\n"
    else:
        bandas_str = ", ".join(band_names)
        bandas_bloco = f"{w_mic} Bandas vinculadas: {bandas_str}\n\n"
        multilogin_bloco = (
            "Com esse mesmo login e senha, você poderá acessar todas as bandas vinculadas à sua conta "
            "e alternar entre elas pelo seletor de bandas do Backstage Pro.\n\n"
        )

    # Se explicitamente marcado como provisória ou se o usuário não possui senha utilizável
    use_provisional = bool(is_provisional or (user and not user.has_usable_password()))

    # Formatação do bloco de credenciais de senha
    if not use_provisional:
        senha_bloco = (
            f"{w_key} Senha: utilize a senha já cadastrada na sua conta.\n\n"
            f"Caso não se lembre da senha, utilize a opção “Esqueci minha senha” na tela de login.\n\n"
        )
    else:
        senha_bloco = (
            f"{w_key} Senha provisória: {raw_password}\n\n"
            f"Por segurança, recomendamos que você altere sua senha após o primeiro acesso.\n\n"
        )

    message_text = (
        f"Olá, {user_name}! {w_hand}\n\n"
        f"Seja bem-vindo(a) ao Backstage Pro! {w_music}{w_rocket}\n\n"
        f"Seu acesso ao sistema já está disponível:\n\n"
        f"{w_link} Acessar o Backstage Pro:\n"
        f"{login_url}\n\n"
        f"{w_user} Login: {username}\n"
        f"{senha_bloco}"
        f"{bandas_bloco}"
        f"{multilogin_bloco}"
        f"Qualquer dúvida, estamos à disposição.\n\n"
        f"Backstage Pro"
    )

    whatsapp_url = ""
    whatsapp_mobile_url = ""
    whatsapp_app_url = ""
    whatsapp_web_url = ""

    if phone_normalized:
        encoded_text = quote(message_text, safe='')
        whatsapp_mobile_url = f"https://wa.me/{phone_normalized}?text={encoded_text}"
        whatsapp_app_url = f"whatsapp://send?phone={phone_normalized}&text={encoded_text}"
        whatsapp_web_url = f"https://web.whatsapp.com/send?phone={phone_normalized}&text={encoded_text}"
        whatsapp_url = whatsapp_mobile_url

    modal_heading = f"Acesso pronto para envio ({username})"
    if not use_provisional:
        modal_subheading = "Os dados de acesso e orientações de login estão prontos para compartilhamento."
    else:
        modal_subheading = "A senha provisória foi definida e os dados de acesso estão prontos para compartilhamento."

    return {
        'has_phone': bool(phone_normalized),
        'phone_normalized': phone_normalized,
        'message_text': message_text,
        'whatsapp_url': whatsapp_url,
        'whatsapp_mobile_url': whatsapp_mobile_url,
        'whatsapp_app_url': whatsapp_app_url,
        'whatsapp_web_url': whatsapp_web_url,
        'is_share': True,
        'modal_title': 'Compartilhar Acesso',
        'modal_heading': modal_heading,
        'modal_subheading': modal_subheading,
        'has_usable_password': not use_provisional,
    }


@login_required
@band_required
def usuarios_list_view(request, band_slug):
    if not request.user.is_produtor():
        return HttpResponseForbidden("Apenas produtores.")

    band = get_object_or_404(Band, slug=band_slug)
    usuarios = User.objects.filter(band=band).order_by('first_name', 'username')
    whatsapp_access_data = request.session.pop('whatsapp_access_data', None)
    is_emp = request.user.is_superuser or request.user.is_empresario(band)

    context = {
        'band': band,
        'usuarios': usuarios,
        'whatsapp_access_data': whatsapp_access_data,
        'is_empresario': is_emp,
    }
    return render(request, 'core/usuarios.html', context)


@login_required
@band_required
def usuario_create_view(request, band_slug):
    if not request.user.is_produtor() and not request.user.is_superuser:
        return HttpResponseForbidden("Apenas produtores podem adicionar usuários.")

    band = get_object_or_404(Band, slug=band_slug)
    is_emp = request.user.is_superuser or request.user.is_empresario(band)

    if request.method == 'POST':
        # BP-PEND-82: Apenas Empresário ou superusuário pode atribuir o perfil EMPRESARIO
        requested_role = request.POST.get('role')
        if requested_role == 'EMPRESARIO' and not is_emp:
            messages.error(request, "Apenas empresários ou administradores podem atribuir o perfil de Empresário.")
            return redirect('usuarios_list', band_slug=band.slug)

        form = UserForm(request.POST)
        if form.is_valid():
            raw_password = form.cleaned_data.get('password')
            user = form.save(commit=False)
            user.band = band
            user.save()

            # BP-PEND-82: Sincroniza UserBandMembership
            from core.models import UserBandMembership
            UserBandMembership.objects.update_or_create(
                user=user,
                band=band,
                defaults={'role': user.role, 'is_active': user.is_active}
            )

            if user.role == 'INTEGRANTE':
                request.session['whatsapp_access_data'] = build_whatsapp_access_data(
                    band=band,
                    user=user,
                    raw_password=raw_password
                )

            messages.success(request, "Usuário criado com sucesso!")
            return redirect('usuarios_list', band_slug=band.slug)
        else:
            if request.POST.get('from_modal'):
                usuarios = User.objects.filter(band=band).order_by('first_name', 'username')
                context = {
                    'band': band,
                    'usuarios': usuarios,
                    'add_user_form': form,
                    'open_add_modal': True,
                    'whatsapp_access_data': None,
                    'is_empresario': is_emp,
                }
                return render(request, 'core/usuarios.html', context)

    else:

        form = UserForm()



    context = {

        'band': band,

        'form': form,

        'is_edit': False,

        'is_empresario': is_emp,

    }

    return render(request, 'core/usuario_form.html', context)



@login_required

@band_required

def usuario_edit_view(request, band_slug, pk):

    if not request.user.is_produtor() and not request.user.is_superuser:

        return HttpResponseForbidden("Apenas produtores podem editar usuários.")



    band = get_object_or_404(Band, slug=band_slug)

    user_to_edit = get_object_or_404(User, pk=pk, band=band)

    is_emp = request.user.is_superuser or request.user.is_empresario(band)



    if request.method == 'POST':

        new_role = request.POST.get('role')
        new_is_active = bool(request.POST.get('is_active'))

        # BP-PEND-82: Apenas Empresário ou superusuário pode atribuir o perfil EMPRESARIO
        if new_role == 'EMPRESARIO' and not is_emp:
            messages.error(request, "Apenas empresários ou administradores podem atribuir o perfil de Empresário.")
            return redirect('usuarios_list', band_slug=band.slug)

        # BP-PEND-82: Trava do último empresário ativo
        was_emp = user_to_edit.is_empresario_for_band(band)
        is_still_emp = (new_role == 'EMPRESARIO' and new_is_active)
        if was_emp and not is_still_emp:
            active_emp_count = band.get_active_empresarios().exclude(pk=user_to_edit.pk).count()
            if active_emp_count == 0:
                messages.error(request, "A banda não pode ficar sem nenhum Empresário ativo.")
                return redirect('usuarios_list', band_slug=band.slug)

        form = UserEditForm(request.POST, instance=user_to_edit)

        if form.is_valid():

            updated_user = form.save()

            # BP-PEND-82: Sincroniza UserBandMembership
            from core.models import UserBandMembership
            UserBandMembership.objects.update_or_create(
                user=updated_user,
                band=band,
                defaults={'role': updated_user.role, 'is_active': updated_user.is_active}
            )

            messages.success(request, "Usuário atualizado com sucesso!")

            return redirect('usuarios_list', band_slug=band.slug)

    else:

        form = UserEditForm(instance=user_to_edit)



    context = {

        'band': band,

        'form': form,

        'is_edit': True,

        'user_to_edit': user_to_edit,

        'is_empresario': is_emp,

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

        # BP-PEND-82: Trava do último empresário ativo ao excluir
        if user_to_delete.is_empresario_for_band(band):
            active_emp_count = band.get_active_empresarios().exclude(pk=user_to_delete.pk).count()
            if active_emp_count == 0:
                messages.error(request, "A banda não pode ficar sem nenhum Empresário ativo.")
                return redirect('usuarios_list', band_slug=band.slug)

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
            if user_to_edit.role == 'INTEGRANTE':
                user_to_edit.must_change_password = True

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

@empresario_required

def payment_create_view(request, band_slug, show_id):

    if not (request.user.is_superuser or request.user.is_empresario(request.band)):

        return HttpResponseForbidden("Apenas empresários podem adicionar recebimentos.")



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

    band = get_object_or_404(Band, slug=band_slug)

    receipt = get_object_or_404(FinancialReceipt, pk=pk, show__band=band)

    is_emp = request.user.is_superuser or request.user.is_empresario(band)

    # PRODUTOR só pode editar se foi ele quem criou o comprovante
    if not is_emp:
        if not request.user.is_produtor(band) or receipt.created_by_id != request.user.id:
            return HttpResponseForbidden("Você não tem permissão para editar este comprovante.")

    show = receipt.show

    if request.method == 'POST':

        form = FinancialReceiptForm(request.POST, request.FILES, instance=receipt)

        if form.is_valid():

            form.save()

            messages.success(request, "Comprovante atualizado com sucesso!")

            next_url = request.GET.get('next')

            if next_url in ['financeiro', 'show_finance_detail']:
                if is_emp:
                    return redirect('show_finance_detail', band_slug=band.slug, pk=show.id)
                return redirect('show_detail', band_slug=band.slug, pk=show.id)

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

@empresario_required

def payment_edit_view(request, band_slug, pk):

    if not (request.user.is_superuser or request.user.is_empresario(request.band)):

        return HttpResponseForbidden("Apenas empresários podem editar recebimentos.")



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

@empresario_required

def payment_delete_view(request, band_slug, pk):

    if not (request.user.is_superuser or request.user.is_empresario(request.band)):

        return HttpResponseForbidden("Apenas empresários podem excluir recebimentos.")



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

@login_required

@band_required

def teamcost_delete_view(request, band_slug, pk):

    band = get_object_or_404(Band, slug=band_slug)

    if not band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")

    team_cost = get_object_or_404(ShowTeamCost, pk=pk, show__band=band)

    is_emp = request.user.is_superuser or request.user.is_empresario(band)

    # PRODUTOR só pode excluir custos que ele próprio criou
    if not is_emp:
        if not request.user.is_produtor(band) or team_cost.created_by_id != request.user.id:
            return HttpResponseForbidden("Você não tem permissão para excluir este custo de equipe.")

    show_id = team_cost.show.id

    if request.method == 'POST':

        team_cost.delete()

        messages.success(request, "Custo com equipe removido com sucesso!")

        if request.GET.get('next') in ['financeiro', 'show_finance_detail']:
            if is_emp:
                return redirect('show_finance_detail', band_slug=band.slug, pk=show_id)
            return redirect('manage_team_costs', band_slug=band.slug, show_id=show_id)

        return redirect('manage_team_costs', band_slug=band.slug, show_id=show_id)

    context = {

        'band': band,

        'team_cost': team_cost

    }

    return render(request, 'core/teamcost_confirm_delete.html', context)


@login_required

@band_required

def teamcost_edit_view(request, band_slug, pk):

    band = get_object_or_404(Band, slug=band_slug)

    team_cost = get_object_or_404(ShowTeamCost, pk=pk, show__band=band)

    is_emp = request.user.is_superuser or request.user.is_empresario(band)

    # PRODUTOR só pode editar custos que ele próprio criou
    if not is_emp:
        if not request.user.is_produtor(band) or team_cost.created_by_id != request.user.id:
            return HttpResponseForbidden("Você não tem permissão para editar este custo de equipe.")

    show = team_cost.show

    if request.method == 'POST':

        form = ShowTeamCostForm(request.POST, instance=team_cost)

        if form.is_valid():

            form.save()

            messages.success(request, "Custo com equipe atualizado com sucesso!")

            next_url = request.GET.get('next')

            if next_url in ['financeiro', 'show_finance_detail']:
                if is_emp:
                    return redirect('show_finance_detail', band_slug=band.slug, pk=show.id)
                return redirect('manage_team_costs', band_slug=band.slug, show_id=show.id)

            return redirect('manage_team_costs', band_slug=band.slug, show_id=show.id)

    if is_emp:
        return redirect('show_finance_detail', band_slug=band.slug, pk=show.id)
    return redirect('manage_team_costs', band_slug=band.slug, show_id=show.id)





@login_required
@band_required
def receipt_delete_view(request, band_slug, pk):
    band = get_object_or_404(Band, slug=band_slug)

    if not band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")

    receipt = get_object_or_404(FinancialReceipt, pk=pk, show__band=band)

    is_emp = request.user.is_superuser or request.user.is_empresario(band)

    # PRODUTOR só pode excluir comprovante que ele mesmo criou
    if not is_emp:
        if not request.user.is_produtor(band) or receipt.created_by_id != request.user.id:
            return HttpResponseForbidden("Você não tem permissão para excluir este comprovante.")

    show_id = receipt.show.id

    if request.method == 'POST':
        receipt.delete()
        messages.success(request, "Comprovante excluído com sucesso!")

        next_url = request.GET.get('next')

        if next_url in ['financeiro', 'show_finance_detail']:
            if is_emp:
                return redirect('show_finance_detail', band_slug=band.slug, pk=show_id)
            return redirect('show_detail', band_slug=band.slug, pk=show_id)

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
    q = request.GET.get('q', '').strip()
    partners = Partner.objects.filter(is_active=True)

    if q:
        from django.db.models import Q
        partners = partners.filter(
            Q(name__icontains=q) |
            Q(segment__icontains=q) |
            Q(phone__icontains=q) |
            Q(instagram__icontains=q)
        )

    return render(request, 'core/partners.html', {
        'partners': partners,
        'band': request.band,
        'search_query': q,
    })





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
                return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)
        else:
            errors = []
            for field, errs in form.errors.items():
                label = form.fields[field].label if field in form.fields else field
                errors.append(f"{label}: {', '.join(errs)}")
            messages.error(request, "Erro ao atualizar quarto: " + "; ".join(errors))
            return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)
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
    from core.services.room_list_services import get_room_list_pdf_filename

    try:
        room_list = RoomList.objects.select_related('show', 'band').prefetch_related(
            'rooms__participants__original_integrante'
        ).get(pk=pk, show__band=request.band)
    except RoomList.DoesNotExist:
        raise Http404("Room List não encontrada.")

    is_produtor = request.user.is_produtor()
    if not is_produtor and room_list.status == RoomList.StatusChoices.RASCUNHO:
        raise PermissionDenied("Acesso restrito. Room List em rascunho.")

    page_title = get_room_list_pdf_filename(room_list, extension="")

    context = {
        'band': request.band,
        'pdf_logo_base64': get_image_base64(request.band.logo),
        'ac_badge_base64': get_static_image_base64('img/room-ac-badge.png'),
        'current_datetime': __import__('django.utils.timezone').utils.timezone.localtime().strftime('%d/%m/%Y às %H:%M'),
        'room_list': room_list,
        'rooms': room_list.rooms.all(),
        'participants': room_list.participants.filter(room__isnull=False),
        'unallocated': room_list.participants.filter(room__isnull=True),
        'page_title': page_title,
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
    from core.services.room_list_services import get_room_list_pdf_filename

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
        filename = get_room_list_pdf_filename(room_list)
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
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
    from core.services.room_list_services import get_room_list_pdf_filename

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
        filename = get_room_list_pdf_filename(room_list)
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
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
    if not request.user.is_produtor(request.band):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden('Apenas produtores podem excluir avisos.')

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

