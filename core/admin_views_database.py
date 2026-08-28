from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import user_passes_test
from django.utils.decorators import method_decorator
from django.contrib import messages
from django.core.paginator import Paginator
from django.views.generic import ListView
from django.http import HttpResponseForbidden
from django.db.models import ProtectedError

from .models import Contact
from .forms import ContactForm
from .admin_views import AdminRequiredMixin, is_admin_geral

class AdminDatabaseListView(AdminRequiredMixin, ListView):
    model = Contact
    template_name = 'core/admin/database/database_list.html'
    context_object_name = 'contacts'
    paginate_by = 25

    def get_queryset(self):
        qs = Contact.objects.select_related('band', 'shared_by').order_by('-id')

        # Filters
        nome = self.request.GET.get('nome', '').strip()
        tipo = self.request.GET.get('tipo', '').strip()
        local = self.request.GET.get('local', '').strip()
        banda = self.request.GET.get('banda', '').strip()
        situacao = self.request.GET.get('situacao', '').strip()

        if nome:
            qs = qs.filter(name__icontains=nome)
        if tipo:
            qs = qs.filter(contact_type=tipo)
        if local:
            qs = qs.filter(location__icontains=local)
        if banda:
            qs = qs.filter(band__name__icontains=banda)

        if situacao == 'visiveis':
            qs = qs.filter(is_hidden=False)
        elif situacao == 'ocultos':
            qs = qs.filter(is_hidden=True)

        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Keep query parameters for pagination and form defaults
        context['search_nome'] = self.request.GET.get('nome', '')
        context['search_tipo'] = self.request.GET.get('tipo', '')
        context['search_local'] = self.request.GET.get('local', '')
        context['search_banda'] = self.request.GET.get('banda', '')
        context['search_situacao'] = self.request.GET.get('situacao', 'todos')

        context['contact_types'] = Contact.CONTACT_TYPE_CHOICES
        return context

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_database_edit(request, pk):
    contact = get_object_or_404(Contact, pk=pk)
    original_band = contact.band
    original_shared_by = contact.shared_by
    original_shared_at = contact.shared_at
    original_is_hidden = contact.is_hidden

    if request.method == 'POST':
        form = ContactForm(request.POST, instance=contact)
        if form.is_valid():
            updated_contact = form.save(commit=False)
            # Garantir preservação da banda e integridade de autoria/ocultação
            updated_contact.band = original_band
            updated_contact.shared_by = original_shared_by
            updated_contact.shared_at = original_shared_at
            updated_contact.is_hidden = original_is_hidden
            updated_contact.save()
            messages.success(request, "Contato atualizado com sucesso!")
            return redirect('admin_painel:database_list')
    else:
        form = ContactForm(instance=contact)

    return render(request, 'core/admin/database/database_edit.html', {
        'form': form,
        'contact': contact
    })

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_database_hide(request, pk):
    if request.method == 'POST':
        contact = get_object_or_404(Contact, pk=pk)
        contact.is_hidden = True
        contact.save(update_fields=['is_hidden'])
        messages.success(request, f"Contato '{contact.name}' ocultado com sucesso.")
        return redirect(request.META.get('HTTP_REFERER', 'admin_painel:database_list'))
    return HttpResponseForbidden("Método não permitido.")

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_database_unhide(request, pk):
    if request.method == 'POST':
        contact = get_object_or_404(Contact, pk=pk)
        contact.is_hidden = False
        contact.save(update_fields=['is_hidden'])
        messages.success(request, f"Contato '{contact.name}' desocultado com sucesso.")
        return redirect(request.META.get('HTTP_REFERER', 'admin_painel:database_list'))
    return HttpResponseForbidden("Método não permitido.")

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_database_delete(request, pk):
    if request.method == 'POST':
        contact = get_object_or_404(Contact, pk=pk)
        try:
            contact.delete()
            messages.success(request, "Contato excluído definitivamente com sucesso!")
        except ProtectedError:
            messages.error(request, "Este contato não pode ser excluído pois possui vínculos no sistema.")
        return redirect(request.META.get('HTTP_REFERER', 'admin_painel:database_list'))
    return HttpResponseForbidden("Método não permitido.")
