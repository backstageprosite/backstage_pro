import os
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import user_passes_test
from django.contrib import messages
from django.utils import timezone
from django.core.paginator import Paginator
from django.urls import reverse
from django.db.models import Q
from django.views import View
from django.utils.decorators import method_decorator

from core.models import SupportTicket, SupportTicketMessage, SupportTicketAttachment, Band

def is_admin_geral(user):
    return user.is_superuser

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


@method_decorator(user_passes_test(is_admin_geral), name='dispatch')
class AdminSupportListView(View):
    def get(self, request):
        tickets = SupportTicket.objects.select_related('band', 'created_by').order_by('-last_message_at')
        
        status_filter = request.GET.get('status')
        band_filter = request.GET.get('band_id')
        q_filter = request.GET.get('q', '').strip()
        
        if status_filter:
            tickets = tickets.filter(status=status_filter)
        if band_filter:
            tickets = tickets.filter(band_id=band_filter)
        if q_filter:
            tickets = tickets.filter(
                Q(band__name__icontains=q_filter) |
                Q(created_by__username__icontains=q_filter) |
                Q(messages__body__icontains=q_filter)
            ).distinct()
            
        # Calcula has_new_message para admin
        for t in tickets:
            t.has_new_message = False
            if t.status in ['NEW', 'WAITING_ADMIN']:
                if not t.admin_last_read_at or t.last_message_at > t.admin_last_read_at:
                    t.has_new_message = True
                    
        # Para ordenação secundária (novos primeiro), fazemos sort in memory já que é um campo custom
        tickets = sorted(tickets, key=lambda x: (not x.has_new_message, x.last_message_at), reverse=True)
        
        paginator = Paginator(tickets, 20)
        page_number = request.GET.get('page')
        page_obj = paginator.get_page(page_number)
        
        bands = Band.objects.all().order_by('name')
        
        context = {
            'page_obj': page_obj,
            'status_choices': SupportTicket.STATUS_CHOICES,
            'bands': bands,
        }
        return render(request, 'core/admin/admin_support_list.html', context)


@method_decorator(user_passes_test(is_admin_geral), name='dispatch')
class AdminSupportDetailView(View):
    def get(self, request, pk):
        ticket = get_object_or_404(SupportTicket, pk=pk)
        
        # Marca como lido pelo admin
        ticket.admin_last_read_at = timezone.now()
        if ticket.status == 'NEW':
            ticket.status = 'IN_PROGRESS'
        ticket.save(update_fields=['admin_last_read_at', 'status'])
        
        messages_qs = ticket.messages.all().prefetch_related('attachments', 'author')
        
        context = {
            'ticket': ticket,
            'messages': messages_qs,
        }
        return render(request, 'core/admin/admin_support_detail.html', context)
        
    def post(self, request, pk):
        ticket = get_object_or_404(SupportTicket, pk=pk)
        
        action = request.POST.get('action')
        
        if action == 'reply':
            body = request.POST.get('message', '').strip()
            files = request.FILES.getlist('attachments')

            if not body:
                messages.error(request, "A resposta não pode ser vazia.")
                return redirect('admin_painel:support_detail', pk=ticket.pk)
                
            if len(files) > 3:
                messages.error(request, "Você pode anexar no máximo 3 arquivos.")
                return redirect('admin_painel:support_detail', pk=ticket.pk)

            for f in files:
                if f.size > 10 * 1024 * 1024:
                    messages.error(request, f"O arquivo {f.name} excede o limite de 10 MB.")
                    return redirect('admin_painel:support_detail', pk=ticket.pk)
                ext = os.path.splitext(f.name)[1].lower()
                if ext not in ['.pdf', '.png', '.jpg', '.jpeg', '.webp']:
                    messages.error(request, f"O formato do arquivo {f.name} não é permitido.")
                    return redirect('admin_painel:support_detail', pk=ticket.pk)

            msg = SupportTicketMessage.objects.create(
                ticket=ticket,
                author=request.user,
                body=body,
                sender_type='ADMIN'
            )

            for f in files:
                SupportTicketAttachment.objects.create(
                    message=msg,
                    file=f,
                    original_name=f.name,
                    mime_type=get_safe_mime_type(f.name),
                    size_bytes=f.size
                )

            ticket.status = 'WAITING_PRODUCER'
            ticket.last_message_at = timezone.now()
            ticket.save(update_fields=['status', 'last_message_at'])

            messages.success(request, "Resposta enviada com sucesso!")
            
        elif action == 'status_in_progress':
            ticket.status = 'IN_PROGRESS'
            ticket.save(update_fields=['status'])
            messages.success(request, "Status alterado para Em análise.")
            
        elif action == 'status_resolved':
            ticket.status = 'RESOLVED'
            ticket.resolved_at = timezone.now()
            ticket.save(update_fields=['status', 'resolved_at'])
            messages.success(request, "Atendimento resolvido com sucesso.")
            
        elif action == 'status_archived':
            ticket.status = 'ARCHIVED'
            ticket.archived_at = timezone.now()
            ticket.save(update_fields=['status', 'archived_at'])
            messages.success(request, "Atendimento arquivado.")
            
        elif action == 'status_waiting_producer':
            ticket.status = 'WAITING_PRODUCER'
            ticket.save(update_fields=['status'])
            messages.success(request, "Status alterado para Aguardando Produtor.")

        return redirect('admin_painel:support_detail', pk=ticket.pk)

@user_passes_test(is_admin_geral)
def admin_support_delete(request, pk):
    if request.method != 'POST':
        messages.error(request, "A exclusão deve ser feita via POST.")
        return redirect('admin_painel:support_list')
        
    ticket = get_object_or_404(SupportTicket, pk=pk)
    band_name = ticket.band.name
    ticket.delete()
    
    messages.success(request, f"Atendimento da banda {band_name} excluído com sucesso.")
    return redirect('admin_painel:support_list')
