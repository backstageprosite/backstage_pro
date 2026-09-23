import os
import mimetypes
from django.http import FileResponse, Http404
from .decorators import advanced_plan_required
from django.shortcuts import get_object_or_404, redirect, render
from django.core.exceptions import PermissionDenied
from django.utils.text import get_valid_filename
from django.contrib.auth.decorators import login_required
from functools import wraps

from core.models import Band, ContractDocument, FinancialReceipt, ShowPayment, BillingRecord, SupportTicketAttachment, RiderDocument, BandGeneralExpense

def is_admin_geral(user):
    """Identifica o Admin Geral nativo do Django."""
    return user.is_superuser

def sanitize_filename(filename):
    """
    Garante que o nome do arquivo seja seguro.
    - Normaliza barras
    - Extrai basename
    - Remove CR, LF e controles
    - Fallback para 'documento.bin' se ficar vazio
    """
    if not filename:
        return "documento.bin"

    # Trocar contrabarras
    filename = filename.replace("\\", "/")
    # Extrair apenas o último componente (basename)
    basename = filename.split("/")[-1]

    # Remover CR e LF agressivamente
    basename = basename.replace("\r", "").replace("\n", "")

    # Passar pelo validador do Django
    from django.core.exceptions import SuspiciousFileOperation
    try:
        safe_name = get_valid_filename(basename)
    except SuspiciousFileOperation:
        return "documento.bin"

    if not safe_name:
        return "documento.bin"

    return safe_name

def get_safe_mime_type(filename):
    """
    Retorna o MIME type apropriado.
    Tipos perigosos (HTML, SVG, JS, Executáveis) são rebaixados para octet-stream.
    """
    mime_type, _ = mimetypes.guess_type(filename)

    # Lista de tipos explicitamente seguros e recomendados
    SAFE_MIMETYPES = [
        'application/pdf',
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'text/plain',
        'text/csv',
    ]

    if mime_type in SAFE_MIMETYPES:
        return mime_type

    return 'application/octet-stream'

def serve_private_file(file_field, as_attachment=True):
    """
    Helper seguro para abrir e servir um arquivo do FieldFile.
    """
    if not file_field or not file_field.name:
        raise Http404("Arquivo não existe no registro.")

    try:
        file_obj = file_field.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404("Arquivo não encontrado fisicamente no servidor.")

    filename = sanitize_filename(file_field.name)
    mime_type = get_safe_mime_type(filename)

    response = FileResponse(file_obj, as_attachment=as_attachment, filename=filename, content_type=mime_type)

    # Headers de Segurança
    response['Cache-Control'] = 'private, no-store, no-cache, must-revalidate'
    response['X-Content-Type-Options'] = 'nosniff'

    return response

def private_download_required(view_func):
    """
    Decorador que garante:
    - Usuário autenticado
    - Acesso à banda validado (relacionamento cruzado bloqueado)
    - Perfil correto (Produtor ou Admin Geral)
    """
    @wraps(view_func)
    def _wrapped_view(request, band_slug, *args, **kwargs):
        if not request.user.is_authenticated:
            # Garante redirecionamento para o login correto com um 'next' interno
            next_url = request.path
            login_url = redirect('login', band_slug=band_slug).url
            return redirect(f"{login_url}?next={next_url}")

        band = get_object_or_404(Band, slug=band_slug)

        # Validar inatividade da banda
        if not band.is_active and not is_admin_geral(request.user):
            raise PermissionDenied("O acesso desta banda ao Backstage Pro está suspenso.")

        # Admin master acessa tudo.
        if is_admin_geral(request.user):
            pass
        else:
            # Usuário comum deve pertencer à banda
            if request.user.band != band:
                # 404 para não revelar existência do arquivo em acesso cruzado
                raise Http404("Página não encontrada.")

            # Verifica perfil (apenas Produtor pode baixar documentos financeiros/contratos)
            if hasattr(request.user, 'is_produtor') and not request.user.is_produtor():
                raise PermissionDenied("Seu perfil de Integrante não tem permissão para baixar este documento.")

        request.band = band
        return view_func(request, band_slug, *args, **kwargs)
    return _wrapped_view


@private_download_required
def download_contract(request, band_slug, pk):
    """Download protegido de ContractDocument"""
    if not request.band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")
    doc = get_object_or_404(ContractDocument, pk=pk, show__band=request.band)
    return serve_private_file(doc.file, as_attachment=True)

@private_download_required
def preview_contract(request, band_slug, pk):
    """Preview protegido de ContractDocument (as_attachment=False)"""
    if not request.band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")
    doc = get_object_or_404(ContractDocument, pk=pk, show__band=request.band)
    return serve_private_file(doc.file, as_attachment=False)


@private_download_required
@advanced_plan_required
def download_receipt(request, band_slug, pk):
    """Download protegido de FinancialReceipt"""
    doc = get_object_or_404(FinancialReceipt, pk=pk, show__band=request.band)
    return serve_private_file(doc.file, as_attachment=True)

@private_download_required
@advanced_plan_required
def preview_receipt(request, band_slug, pk):
    """Preview protegido de FinancialReceipt (as_attachment=False)"""
    doc = get_object_or_404(FinancialReceipt, pk=pk, show__band=request.band)
    return serve_private_file(doc.file, as_attachment=False)


@private_download_required
@advanced_plan_required
def download_payment(request, band_slug, pk):
    """Download protegido de ShowPayment"""
    doc = get_object_or_404(ShowPayment, pk=pk, show__band=request.band)
    return serve_private_file(doc.file, as_attachment=True)

@private_download_required
@advanced_plan_required
def preview_payment(request, band_slug, pk):
    """Preview protegido de ShowPayment (as_attachment=False)"""
    doc = get_object_or_404(ShowPayment, pk=pk, show__band=request.band)
    return serve_private_file(doc.file, as_attachment=False)

@private_download_required
def download_billing(request, band_slug, pk):
    """Download protegido de BillingRecord"""
    doc = get_object_or_404(BillingRecord, pk=pk, band=request.band)
    return serve_private_file(doc.proof_file, as_attachment=True)

@private_download_required
def preview_billing(request, band_slug, pk):
    """Preview protegido de BillingRecord (as_attachment=False)"""
    doc = get_object_or_404(BillingRecord, pk=pk, band=request.band)
    return serve_private_file(doc.proof_file, as_attachment=False)

@private_download_required
def download_support_attachment(request, band_slug, pk):
    """Download protegido de SupportTicketAttachment"""
    doc = get_object_or_404(SupportTicketAttachment, pk=pk, message__ticket__band=request.band)
    return serve_private_file(doc.file, as_attachment=True)

@private_download_required
def preview_support_attachment(request, band_slug, pk):
    """Preview protegido de SupportTicketAttachment (as_attachment=False)"""
    doc = get_object_or_404(SupportTicketAttachment, pk=pk, message__ticket__band=request.band)
    return serve_private_file(doc.file, as_attachment=False)

@private_download_required
@advanced_plan_required
def download_rider(request, band_slug, pk):
    """Download protegido de RiderDocument"""
    doc = get_object_or_404(RiderDocument, pk=pk, band=request.band)
    return serve_private_file(doc.file, as_attachment=True)

@private_download_required
@advanced_plan_required
def preview_rider(request, band_slug, pk):
    """Preview protegido de RiderDocument (as_attachment=False)"""
    doc = get_object_or_404(RiderDocument, pk=pk, band=request.band)
    return serve_private_file(doc.file, as_attachment=False)

@private_download_required
@advanced_plan_required
def download_commercial_document(request, band_slug, pk):
    """Download protegido de CommercialProposalDocument"""
    from core.models import CommercialProposalDocument
    doc = get_object_or_404(CommercialProposalDocument, pk=pk, proposal__band=request.band)
    return serve_private_file(doc.file, as_attachment=True)

@private_download_required
@advanced_plan_required
def preview_commercial_document(request, band_slug, pk):
    """Preview protegido de CommercialProposalDocument (as_attachment=False)"""
    from core.models import CommercialProposalDocument
    doc = get_object_or_404(CommercialProposalDocument, pk=pk, proposal__band=request.band)
    return serve_private_file(doc.file, as_attachment=False)

@private_download_required
@advanced_plan_required
def download_general_expense(request, band_slug, pk):
    """Download protegido de BandGeneralExpense (BP-PEND-77)"""
    doc = get_object_or_404(BandGeneralExpense, pk=pk, band=request.band)
    return serve_private_file(doc.file, as_attachment=True)

@private_download_required
@advanced_plan_required
def preview_general_expense(request, band_slug, pk):
    """Preview protegido de BandGeneralExpense (BP-PEND-77)"""
    doc = get_object_or_404(BandGeneralExpense, pk=pk, band=request.band)
    return serve_private_file(doc.file, as_attachment=False)

@private_download_required
def internal_file_viewer(request, band_slug, file_type, pk):
    """
    Página HTML interna do visualizador PWA controlada pelo Django.
    """
    from django.urls import reverse
    band = request.band

    # receipt, payment, rider, general_expense are Advanced-only modules. Deny at the object level.
    _advanced_only_types = {'receipt', 'payment', 'rider', 'general_expense'}
    if file_type in _advanced_only_types and not band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")

    if file_type == 'contract':
        if not band.is_advanced:
            raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")
        doc = get_object_or_404(ContractDocument, pk=pk, show__band=band)
        preview_url = reverse('preview_contract', args=[band.slug, pk])
        download_url = reverse('download_contract', args=[band.slug, pk])
        filename = doc.file.name
    elif file_type == 'receipt':
        doc = get_object_or_404(FinancialReceipt, pk=pk, show__band=band)
        preview_url = reverse('preview_receipt', args=[band.slug, pk])
        download_url = reverse('download_receipt', args=[band.slug, pk])
        filename = doc.file.name
    elif file_type == 'payment':
        doc = get_object_or_404(ShowPayment, pk=pk, show__band=band)
        preview_url = reverse('preview_payment', args=[band.slug, pk])
        download_url = reverse('download_payment', args=[band.slug, pk])
        filename = doc.file.name
    elif file_type == 'general_expense':
        doc = get_object_or_404(BandGeneralExpense, pk=pk, band=band)
        preview_url = reverse('preview_general_expense', args=[band.slug, pk])
        download_url = reverse('download_general_expense', args=[band.slug, pk])
        filename = doc.file.name
    elif file_type == 'billing':
        doc = get_object_or_404(BillingRecord, pk=pk, band=band)
        preview_url = reverse('preview_billing', args=[band.slug, pk])
        download_url = reverse('download_billing', args=[band.slug, pk])
        filename = doc.proof_file.name
    elif file_type == 'support':
        doc = get_object_or_404(SupportTicketAttachment, pk=pk, message__ticket__band=band)
        preview_url = reverse('preview_support_attachment', args=[band.slug, pk])
        download_url = reverse('download_support_attachment', args=[band.slug, pk])
        filename = doc.file.name
    elif file_type == 'rider':
        doc = get_object_or_404(RiderDocument, pk=pk, band=band)
        preview_url = reverse('preview_rider', args=[band.slug, pk])
        download_url = reverse('download_rider', args=[band.slug, pk])
        filename = doc.file.name
    else:
        raise Http404("Tipo de arquivo inválido.")

    if not filename:
        raise Http404("Arquivo não existe no registro.")

    safe_filename = filename.split('/')[-1]

    context = {
        'band': band,
        'preview_url': preview_url,
        'download_url': download_url,
        'filename': safe_filename,
    }

    return render(request, 'core/file_viewer.html', context)


def public_band_logo(request, band_slug):
    """
    Exibe a logo pública da banda de forma segura.
    Servido apenas para bandas ativas.
    """
    band = get_object_or_404(Band, slug=band_slug)

    # Rota pública não serve logo inativa para ninguém.
    if not band.is_active:
        raise Http404("Logo não disponível.")

    if not band.logo or not band.logo.name:
        raise Http404("Esta banda não possui logo.")

    try:
        file_obj = band.logo.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404("Logo não encontrada fisicamente.")

    mime_type = get_safe_mime_type(band.logo.name)

    # Para visualização pública no navegador, as_attachment=False
    response = FileResponse(file_obj, as_attachment=False)
    response['Content-Type'] = mime_type
    response['X-Content-Type-Options'] = 'nosniff'

    response['Cache-Control'] = 'public, max-age=86400'

    return response


def admin_band_logo(request, band_slug):
    """
    Rota administrativa exclusiva para servir logos de bandas, mesmo inativas.
    Restrita ao Admin Geral.
    """
    if not request.user.is_authenticated or not is_admin_geral(request.user):
        raise PermissionDenied("Acesso exclusivo para Admin Geral.")

    band = get_object_or_404(Band, slug=band_slug)

    if not band.logo or not band.logo.name:
        raise Http404("Esta banda não possui logo.")

    try:
        file_obj = band.logo.open("rb")
    except (FileNotFoundError, OSError, ValueError):
        raise Http404("Logo não encontrada fisicamente.")

    mime_type = get_safe_mime_type(band.logo.name)

    response = FileResponse(file_obj, as_attachment=False, content_type=mime_type)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store, must-revalidate'
    response['Vary'] = 'Cookie'

    return response

def public_rider_download(request, band_slug, uuid):
    """
    Download público seguro para Rider (sem login) através do UUID.
    O plano é verificado via doc.band — não há confiança em dados enviados pelo cliente.
    """
    doc = get_object_or_404(RiderDocument, uuid=uuid)

    # Valida inatividade da banda
    if not doc.band.is_active:
        raise Http404("Documento não disponível.")

    # Proteção de plano: Rider é módulo exclusivo do plano Avançado.
    if not doc.band.is_advanced:
        raise PermissionDenied("Este recurso está disponível apenas no plano Avançado.")

    return serve_private_file(doc.file, as_attachment=True)

def public_room_list_download(request, band_slug, token):
    from django.core.signing import Signer, BadSignature
    from django.shortcuts import get_object_or_404, Http404
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from xhtml2pdf import pisa
    import io
    from core.models import RoomList
    from core.views import get_image_base64
    
    signer = Signer()
    try:
        room_list_id = signer.unsign(token)
    except BadSignature:
        raise Http404("Link inválido ou expirado.")

    room_list = get_object_or_404(RoomList.objects.select_related('show', 'band').prefetch_related(
        'rooms__participants__original_integrante'
    ), pk=room_list_id)

    if room_list.status != 'PUBLICADA':
        raise Http404("Room List não disponível.")

    if not room_list.band.is_active:
        raise Http404("Banda inativa.")

    context = {
        'band': room_list.band,
        'pdf_logo_base64': get_image_base64(room_list.band.logo),
        'current_datetime': __import__('django.utils.timezone').utils.timezone.localtime().strftime('%d/%m/%Y ààs %H:%M'),
        'room_list': room_list,
        'rooms': room_list.rooms.all(),
        'participants': room_list.participants.filter(room__isnull=False),
        'unassigned_participants': room_list.participants.filter(room__isnull=True, needs_lodging=True),
        'not_needing_lodging': room_list.participants.filter(needs_lodging=False),
        'request': request,
    }

    html_string = render_to_string('core/room_list/room_list_pdf.html', context)
    result = io.BytesIO()
    pdf = pisa.pisaDocument(io.BytesIO(html_string.encode("UTF-8")), result)
    
    if not pdf.err:
        from core.services.room_list_services import get_room_list_pdf_filename
        filename = get_room_list_pdf_filename(room_list)
        response = HttpResponse(result.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        response['Cache-Control'] = 'public, max-age=3600'
        return response
    return HttpResponse("Erro ao gerar o PDF.", status=500)

