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

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_expense_create(request):
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "Despesa adicionada com sucesso!")
        else:
            messages.error(request, "Erro ao adicionar despesa."); print(form.errors)
    return redirect('admin_painel:relatorio_financeiro')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_expense_edit(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=expense)
        if form.is_valid():
            form.save()
            messages.success(request, "Despesa atualizada com sucesso!")
        else:
            messages.error(request, "Erro ao atualizar despesa.")
    return redirect('admin_painel:relatorio_financeiro')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
def admin_expense_mark_paid(request, pk):
    if request.method == 'POST':
        expense = get_object_or_404(Expense, pk=pk)
        expense.status = 'PAGO'
        expense.paid_date = timezone.localdate()
        expense.save()
        messages.success(request, "Despesa marcada como paga!")
    return redirect('admin_painel:relatorio_financeiro')

@user_passes_test(is_admin_geral, login_url='/admin-master/login/')
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
    return redirect('admin_painel:relatorio_financeiro')

