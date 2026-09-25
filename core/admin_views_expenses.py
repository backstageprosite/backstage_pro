from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.utils import timezone
from .models import Expense
from django import forms
import datetime
from django.contrib.auth.decorators import user_passes_test
from .admin_views import is_admin_geral

import re
from decimal import Decimal, InvalidOperation

def parse_brazilian_currency(val):
    """
    Normaliza e valida valores monetários aceitando formatos:
    - 49,90 ou 49.90 -> Decimal('49.90')
    - 1.234,56 ou 1,234.56 -> Decimal('1234.56')
    - 100 -> Decimal('100.00')
    Rejeita valores ambíguos, com mais de 2 casas decimais, ou inválidos.
    """
    if val is None:
        raise forms.ValidationError("Informe um valor válido.")
    
    val_str = str(val).strip()
    # Remove símbolo de moeda R$ ou $ e espaços
    val_str = re.sub(r'^(R\$\s*|\$\s*)', '', val_str, flags=re.IGNORECASE).strip()
    
    if not val_str:
        raise forms.ValidationError("Informe um valor válido.")
        
    has_comma = ',' in val_str
    has_dot = '.' in val_str

    if has_comma and has_dot:
        last_comma = val_str.rfind(',')
        last_dot = val_str.rfind('.')

        if last_comma > last_dot:
            # Formato brasileiro: 1.234.567,89
            # O separador decimal é a vírgula
            thousands = val_str[:last_comma].split('.')
            decimals = val_str[last_comma + 1:]
            
            # Validar blocos de milhar
            if not thousands[0].isdigit() or not (1 <= len(thousands[0]) <= 3):
                raise forms.ValidationError("Formato de milhar inválido para o valor.")
            for group in thousands[1:]:
                if not (group.isdigit() and len(group) == 3):
                    raise forms.ValidationError("Formato de milhar inválido para o valor.")
                    
            if not decimals.isdigit() or len(decimals) > 2:
                raise forms.ValidationError("O valor deve conter no máximo duas casas decimais.")
                
            clean_str = "".join(thousands) + "." + decimals
        else:
            # Formato americano: 1,234,567.89
            # O separador decimal é o ponto
            thousands = val_str[:last_dot].split(',')
            decimals = val_str[last_dot + 1:]
            
            if not thousands[0].isdigit() or not (1 <= len(thousands[0]) <= 3):
                raise forms.ValidationError("Formato de milhar inválido para o valor.")
            for group in thousands[1:]:
                if not (group.isdigit() and len(group) == 3):
                    raise forms.ValidationError("Formato de milhar inválido para o valor.")
                    
            if not decimals.isdigit() or len(decimals) > 2:
                raise forms.ValidationError("O valor deve conter no máximo duas casas decimais.")
                
            clean_str = "".join(thousands) + "." + decimals
    elif has_comma:
        # Apenas vírgula: 49,90 ou 1000,50 ou múltiplos blocos inválidos como 1,234,56
        parts = val_str.split(',')
        if len(parts) > 2:
            raise forms.ValidationError("Formato de número inválido ou ambíguo com múltiplas vírgulas.")
        
        integer_part, decimal_part = parts[0], parts[1]
        if not integer_part.isdigit() or not decimal_part.isdigit():
            raise forms.ValidationError("Valor numérico inválido.")
        if len(decimal_part) > 2:
            raise forms.ValidationError("O valor deve conter no máximo duas casas decimais.")
            
        clean_str = f"{integer_part}.{decimal_part}"
    elif has_dot:
        # Apenas ponto: 49.90 ou 1000.50 ou 1.234
        parts = val_str.split('.')
        if len(parts) > 2:
            raise forms.ValidationError("Formato de número inválido ou ambíguo com múltiplos pontos.")
            
        integer_part, decimal_part = parts[0], parts[1]
        if not integer_part.isdigit() or not decimal_part.isdigit():
            raise forms.ValidationError("Valor numérico inválido.")
            
        # Atenção: se alguém digitar 1.234 com exatamente 3 dígitos após o ponto sem vírgula,
        # isso é ambíguo entre milhar (1.234) e três decimais (1.234).
        # Como o requisito exige: "Aceitar no máximo duas casas decimais" e "Não converter silenciosamente entradas ambíguas ou inválidas; mostrar uma mensagem clara",
        # se len(decimal_part) > 2 rejeitamos com mensagem clara.
        if len(decimal_part) > 2:
            raise forms.ValidationError("O valor deve conter no máximo duas casas decimais. Se for milhar, use formato completo como 1.234,00.")
            
        clean_str = f"{integer_part}.{decimal_part}"
    else:
        # Sem separador decimal: número inteiro (ex: 100)
        if not val_str.isdigit():
            raise forms.ValidationError("Valor numérico inválido.")
        clean_str = val_str

    try:
        dec = Decimal(clean_str).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        raise forms.ValidationError("Valor monetário inválido.")

    if dec <= Decimal('0.00'):
        raise forms.ValidationError("O valor deve ser maior que zero.")

    return dec


class ExpenseForm(forms.ModelForm):
    amount = forms.CharField(label="Valor", required=True)
    proof_file = forms.FileField(label="Comprovante", required=False)

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

    def clean_amount(self):
        amount_raw = self.cleaned_data.get('amount')
        return parse_brazilian_currency(amount_raw)


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

            # Verificação de possível duplicidade (mesma data de vencimento, descrição e valor normalizado)
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
                formatted_amount = f"{dup_item.amount:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
                messages.warning(
                    request,
                    f"Atenção: Já existe um lançamento com a mesma descrição ('{dup_item.description}'), "
                    f"vencimento ({dup_item.due_date.strftime('%d/%m/%Y')}) e valor (R$ {formatted_amount}). "
                    f"O lançamento foi registrado com sucesso. Verifique se não se trata de uma duplicata."
                )

            expense.save()
            messages.success(request, "Despesa adicionada com sucesso!")
        else:
            for field, errors in form.errors.items():
                label = form.fields[field].label if field in form.fields and form.fields[field].label else field
                for error in errors:
                    messages.error(request, f"{label}: {error}")
    return redirect(_get_redirect_url(request))

@user_passes_test(is_admin_geral, login_url='/painel/login/')
def admin_expense_edit(request, pk):
    expense = get_object_or_404(Expense, pk=pk)
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=expense)
        if form.is_valid():
            exp = form.save(commit=False)
            # Garantir que comprovante existente fique intacto se nenhum novo arquivo for enviado
            if not request.FILES.get('proof_file'):
                exp.proof_file = expense.proof_file
            if request.user.is_authenticated:
                exp.updated_by = request.user
            exp.save()
            messages.success(request, "Despesa atualizada com sucesso!")
        else:
            for field, errors in form.errors.items():
                label = form.fields[field].label if field in form.fields and form.fields[field].label else field
                for error in errors:
                    messages.error(request, f"{label}: {error}")
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

