import os
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.core.exceptions import PermissionDenied

from core.models import (
    Band, SupportTicket, SupportTicketMessage, SupportTicketAttachment
)
from core.views import band_required

def get_safe_mime_type(filename):
    import mimetypes
    mime_type, _ = mimetypes.guess_type(filename)
    SAFE_MIMETYPES = [
        'application/pdf',
        'image/jpeg',
        'image/png',
        'image/gif',
        'image/webp',
    ]
    if mime_type in SAFE_MIMETYPES:
        return mime_type
    return 'application/octet-stream'


@login_required
@band_required
def support_list_view(request, band_slug):
    """
    Lista os chamados da banda.
    Somente produtor tem acesso.
    """
    if not hasattr(request.user, 'is_produtor') or not request.user.is_produtor():
        raise PermissionDenied("Acesso restrito aos produtores da banda.")

    band = request.band
    tickets = SupportTicket.objects.filter(band=band).order_by('-last_message_at')

    # Calcula se tem mensagem nova para o produtor
    for t in tickets:
        # Se admin_last_read_at, etc... mas o que importa para o produtor é se tem mensagem do admin não lida
        # Se a data da última mensagem for maior que a data de leitura do produtor
        t.has_new_message = False
        if t.status in ['WAITING_PRODUCER']:
            if not t.producer_last_read_at or t.last_message_at > t.producer_last_read_at:
                t.has_new_message = True

    context = {
        'band': band,
        'tickets': tickets,
    }
    return render(request, 'core/support_list.html', context)


@login_required
@band_required
def support_create_view(request, band_slug):
    """
    Criação de um novo chamado pelo produtor.
    """
    if not hasattr(request.user, 'is_produtor') or not request.user.is_produtor():
        raise PermissionDenied("Acesso restrito aos produtores da banda.")

    band = request.band

    if request.method == 'POST':
        body = request.POST.get('message', '').strip()
        files = request.FILES.getlist('attachments')

        if not body:
            messages.error(request, "A mensagem não pode ser vazia.")
            return redirect('support_list', band_slug=band.slug)
            
        if len(files) > 3:
            messages.error(request, "Você pode anexar no máximo 3 arquivos.")
            return redirect('support_list', band_slug=band.slug)

        # Validações dos arquivos
        for f in files:
            if f.size > 10 * 1024 * 1024:
                messages.error(request, f"O arquivo {f.name} excede o limite de 10 MB.")
                return redirect('support_list', band_slug=band.slug)
            
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in ['.pdf', '.png', '.jpg', '.jpeg', '.webp']:
                messages.error(request, f"O formato do arquivo {f.name} não é permitido.")
                return redirect('support_list', band_slug=band.slug)

        # Criar ticket
        ticket = SupportTicket.objects.create(
            band=band,
            created_by=request.user,
            status='NEW',
            producer_last_read_at=timezone.now()
        )

        # Criar mensagem
        msg = SupportTicketMessage.objects.create(
            ticket=ticket,
            author=request.user,
            body=body,
            sender_type='PRODUCER'
        )

        # Criar anexos
        for f in files:
            SupportTicketAttachment.objects.create(
                message=msg,
                file=f,
                original_name=f.name,
                mime_type=get_safe_mime_type(f.name),
                size_bytes=f.size
            )

        messages.success(request, "Mensagem enviada com sucesso!")
        return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)

    return redirect('support_list', band_slug=band.slug)


@login_required
@band_required
def support_detail_view(request, band_slug, pk):
    """
    Detalhe de um chamado.
    """
    if not hasattr(request.user, 'is_produtor') or not request.user.is_produtor():
        raise PermissionDenied("Acesso restrito aos produtores da banda.")

    band = request.band
    ticket = get_object_or_404(SupportTicket, pk=pk, band=band)

    # Marca como lido
    ticket.producer_last_read_at = timezone.now()
    ticket.save(update_fields=['producer_last_read_at'])

    if request.method == 'POST':
        # Responder
        if ticket.status in ['RESOLVED', 'ARCHIVED']:
            messages.error(request, "Este atendimento está encerrado e não pode receber novas respostas.")
            return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)

        body = request.POST.get('message', '').strip()
        files = request.FILES.getlist('attachments')

        if not body:
            messages.error(request, "A resposta não pode ser vazia.")
            return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)
            
        if len(files) > 3:
            messages.error(request, "Você pode anexar no máximo 3 arquivos.")
            return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)

        for f in files:
            if f.size > 10 * 1024 * 1024:
                messages.error(request, f"O arquivo {f.name} excede o limite de 10 MB.")
                return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)
            
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in ['.pdf', '.png', '.jpg', '.jpeg', '.webp']:
                messages.error(request, f"O formato do arquivo {f.name} não é permitido.")
                return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)

        # Salvar resposta
        msg = SupportTicketMessage.objects.create(
            ticket=ticket,
            author=request.user,
            body=body,
            sender_type='PRODUCER'
        )

        for f in files:
            SupportTicketAttachment.objects.create(
                message=msg,
                file=f,
                original_name=f.name,
                mime_type=get_safe_mime_type(f.name),
                size_bytes=f.size
            )

        ticket.status = 'WAITING_ADMIN'
        ticket.last_message_at = timezone.now()
        ticket.save(update_fields=['status', 'last_message_at'])

        messages.success(request, "Resposta enviada com sucesso!")
        return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)

    context = {
        'band': band,
        'ticket': ticket,
        'messages': ticket.messages.all().prefetch_related('attachments', 'author')
    }
    return render(request, 'core/support_detail.html', context)


@login_required
@band_required
def support_reopen_view(request, band_slug, pk):
    """
    Reabrir chamado resolvido.
    """
    if not hasattr(request.user, 'is_produtor') or not request.user.is_produtor():
        raise PermissionDenied("Acesso restrito aos produtores da banda.")

    if request.method != 'POST':
        raise PermissionDenied("Método inválido.")

    band = request.band
    ticket = get_object_or_404(SupportTicket, pk=pk, band=band)

    if ticket.status == 'ARCHIVED':
        messages.error(request, "Chamados arquivados não podem ser reabertos.")
        return redirect('support_list', band_slug=band.slug)

    if ticket.status == 'RESOLVED':
        body = request.POST.get('message', '').strip()
        if not body:
            messages.error(request, "Você deve enviar uma mensagem para reabrir o atendimento.")
            return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)

        msg = SupportTicketMessage.objects.create(
            ticket=ticket,
            author=request.user,
            body=body,
            sender_type='PRODUCER'
        )
        
        ticket.status = 'WAITING_ADMIN'
        ticket.last_message_at = timezone.now()
        ticket.save(update_fields=['status', 'last_message_at'])
        
        messages.success(request, "Atendimento reaberto com sucesso.")
        return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)
        
    messages.info(request, "O atendimento já está em andamento.")
    return redirect('support_detail', band_slug=band.slug, pk=ticket.pk)
