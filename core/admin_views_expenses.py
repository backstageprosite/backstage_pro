from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from .models import Expense
from django import forms
import datetime
from django.contrib.auth.decorators import user_passes_test
from .admin_views import is_admin_geral

class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = [
            'description', 'provider', 'category', 'amount', 'competence_date',
            'due_date', 'status', 'paid_date', 'payment_method', 'internal_notes',
            'proof_file', 'is_recurring', 'recurrence_cycle', 'recurrence_end_date'
        ]
        widgets = {
            'competence_date': forms.DateInput(attrs={'type': 'date'}),
            'due_date': forms.DateInput(attrs={'type': 'date'}),
            'paid_date': forms.DateInput(attrs={'type': 'date'}),
            'recurrence_end_date': forms.DateInput(attrs={'type': 'date'}),
        }

def _get_redirect_url(request):
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return next_url
    query = request.GET.urlencode()
    if query:
        return f"/painel/relatorios/financeiro/?{query}"
    return 'admin_painel:relatorio_financeiro'

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_expense_create(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            expense = form.save(commit=False)
            if request.user.is_authenticated:
                expense.created_by = request.user
                expense.updated_by = request.user

            # Verificação de possível duplicidade (mesma data de vencimento, descrição e valor)
            description = form.cleaned_data.get('description', '').strip()
            due_date = form.cleaned_data.get('due_date')
            amount = form.cleaned_data.get('amount')
            ignore_duplicate = request.POST.get('ignore_duplicate') == '1'

            duplicate_qs = Expense.objects.filter(
                description__iexact=description,
                due_date=due_date,
                amount=amount
            )
            if duplicate_qs.exists() and not ignore_duplicate:
                dup_item = duplicate_qs.first()
                messages.warning(
                    request,
                    f"Atenção: Já existe um lançamento com a mesma descrição ('{dup_item.description}'), "
                    f"vencimento ({dup_item.due_date.strftime('%d/%m/%Y')}) e valor (R$ {dup_item.amount}). "
                    f"O lançamento foi registrado com sucesso. Verifique se não se trata de uma duplicata."
                )

            expense.save()
            messages.success(request, "Despesa adicionada com sucesso!")
        else:
            messages.error(request, "Erro ao adicionar despesa.")
    return redirect(_get_redirect_url(request))

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_expense_edit(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=expense)
        if form.is_valid():
            exp = form.save(commit=False)
            if request.user.is_authenticated:
                exp.updated_by = request.user
            exp.save()
            messages.success(request, "Despesa atualizada com sucesso!")
        else:
            messages.error(request, "Erro ao atualizar despesa.")
    return redirect(_get_redirect_url(request))

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_expense_mark_paid(request, pk):
    if request.method == 'POST':
        expense = get_object_or_404(Expense, pk=pk)
        expense.status = 'PAGO'
        expense.paid_date = timezone.localdate()
        if request.user.is_authenticated:
            expense.updated_by = request.user
        expense.save()
        messages.success(request, "Despesa marcada como paga!")
    return redirect(_get_redirect_url(request))

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_expense_delete(request, pk):
    if request.method == 'POST':
        expense = get_object_or_404(Expense, pk=pk)
        delete_future = request.POST.get('delete_future') == 'yes'
        
        if delete_future and expense.is_recurring:
            Expense.objects.filter(
                description=expense.description,
                provider=expense.provider,
                category=expense.category,
                due_date__gte=expense.due_date
            ).delete()
        else:
            expense.delete()
            
        messages.success(request, "Despesa excluída com sucesso!")
    return redirect(_get_redirect_url(request))

