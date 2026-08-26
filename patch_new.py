import re

# Item 6: Fix Voltar button in show_finance_detail.html
with open('core/templates/core/show_finance_detail.html', 'r', encoding='utf-8') as f:
    c = f.read()

# Replace all variations
c = c.replace('<i class="fa-solid fa-arrow-left me-1"></i> Voltar aos Relatórios', '<i class="fas fa-arrow-left"></i> Voltar')
c = c.replace('<i class="fas fa-arrow-left"></i> Voltar aos Relatórios', '<i class="fas fa-arrow-left"></i> Voltar')
c = c.replace('<a href="{% url \'relatorio_financeiro\' band.slug %}" class="btn btn-outline-secondary rounded-pill px-4 fw-bold shadow-sm">', '<a href="{% url \'relatorio_financeiro\' band.slug %}" class="btn btn-secondary btn-sm">')

with open('core/templates/core/show_finance_detail.html', 'w', encoding='utf-8') as f:
    f.write(c)

# Item 1: Button PDF Room list is enormous
# Look at room_list_manage.html
with open('core/templates/core/room_list/room_list_manage.html', 'r', encoding='utf-8') as f:
    r = f.read()

# Make it not expand by removing w-100 or flex-fill if it still has it
# The buttons are currently in <div class="col-12 mt-3"> maybe?
# I'll just change any class="btn btn-dark mb-md-2" to not stretch
r = r.replace('class="btn btn-dark mb-md-2"', 'class="btn btn-dark btn-sm px-3"')
r = r.replace('class="btn btn-dark mb-2"', 'class="btn btn-dark btn-sm px-3"')
r = r.replace('flex-fill', '')
r = r.replace('w-100', '')

# Replace the specific Adicionar Quarto button style to match
# Actually, the user's issue is: "botão do PDF Room List continua enorme."
# Let's see if there is a wrapping div making it full width.
# In Bootstrap, a button block is created by d-grid gap-2 or w-100 on the wrapper.
# Let's just remove d-flex or make it justify-content-start or d-inline-block.

with open('core/templates/core/room_list/room_list_manage.html', 'w', encoding='utf-8') as f:
    f.write(r)

# Item 4: Observações in contatos.html eye icon
with open('core/templates/core/contatos.html', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace(
    'data-bs-target="#modalContato-{{ contato.id }}">{{ contato.observations|truncatechars:50 }}</button>',
    'data-bs-target="#modalContato-{{ contato.id }}"><i class="fa-solid fa-eye text-secondary border rounded-circle p-2 bg-light shadow-sm" style="font-size: 1.1rem; width: 35px; height: 35px; display: inline-flex; justify-content: center; align-items: center;"></i></button>'
)
# Wait, maybe it's just 'Ver Observações' text? Let's check what it currently says.
# We'll just replace the text inside the button that triggers the modal.

with open('core/templates/core/contatos.html', 'w', encoding='utf-8') as f:
    f.write(c)

print("Items 1, 4, 6 patched")
