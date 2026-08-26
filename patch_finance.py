import re
with open('core/templates/core/show_finance_detail.html', 'r', encoding='utf-8') as f:
    c = f.read()

old_button = r'<a href="\{% url \'relatorio_financeiro\' band.slug %\}" class="btn btn-secondary btn-sm">\s*<i class="fas fa-arrow-left"></i> Voltar\s*</a>'
new_button = """<a href="{% url 'relatorio_financeiro' band.slug %}" class="btn btn-light rounded-pill px-3 shadow-sm border">
            <i class="fa-solid fa-arrow-left me-1"></i> Voltar
        </a>"""

c = re.sub(old_button, new_button, c, flags=re.DOTALL)

with open('core/templates/core/show_finance_detail.html', 'w', encoding='utf-8') as f:
    f.write(c)
print("Item 3 patched")
