with open('core/templates/core/show_finance_detail.html', 'r', encoding='utf-8') as f:
    content = f.read()

old_button = """<a href="{% url 'relatorio_financeiro' band.slug %}" class="btn btn-outline-secondary rounded-pill px-4 fw-bold shadow-sm">
<i class="fa-solid fa-arrow-left me-1"></i> Voltar aos Relatórios
</a>"""
new_button = """<a href="{% url 'relatorio_financeiro' band.slug %}" class="btn btn-secondary btn-sm">
<i class="fas fa-arrow-left"></i> Voltar
</a>"""

content = content.replace(old_button, new_button)
with open('core/templates/core/show_finance_detail.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Item 7 patched")
