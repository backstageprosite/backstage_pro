import re

# Item 4: Add label to desktop selectAll in integrantes_list.html
with open('core/templates/core/integrantes_list.html', 'r', encoding='utf-8') as f:
    int_html = f.read()

# Make the checkbox column wider and add a label
int_html = int_html.replace('style="width: 50px;"', 'style="width: 100px; cursor: pointer;"')
int_html = int_html.replace(
    '<input type="checkbox" class="form-check-input" id="selectAll" onclick="toggleAll(this)">',
    '<div class="form-check m-0"><input type="checkbox" class="form-check-input" id="selectAll" onclick="toggleAll(this)"><label class="form-check-label ms-1" for="selectAll" style="cursor: pointer;">Todos</label></div>'
)
with open('core/templates/core/integrantes_list.html', 'w', encoding='utf-8') as f:
    f.write(int_html)

# Item 5: Filters on mobile should be col-6 instead of 1 per line (col-12 by default if not specified or via form).
# Let's adjust all filter fields to use col-6 on small screens (col-6 col-md-2 col-lg-2).
import os
filter_pages = [
    'core/templates/core/shows.html',
    'core/templates/core/relatorios.html',
    'core/templates/core/admin/usuarios.html',
    'core/templates/core/admin/cobrancas.html',
    'core/templates/core/admin/assinaturas.html',
    'core/templates/core/banco_de_dados.html',
    'core/templates/core/contatos.html',
    'core/templates/core/admin/bandas.html'
]
for p in filter_pages:
    if os.path.exists(p):
        with open(p, 'r', encoding='utf-8') as f:
            c = f.read()
        # Add col-6 to existing responsive columns
        c = c.replace('class="col-md-2 col-lg-2"', 'class="col-6 col-md-2 col-lg-2"')
        c = c.replace('class="col-md-3"', 'class="col-6 col-md-3"')
        # Handle Contatos specially to match Banco de Dados
        if 'contatos.html' in p:
            c = c.replace('class="col-md-4"', 'class="col-6 col-md-2 col-lg-2"')
            c = c.replace('class="col-md-5"', 'class="col-6 col-md-3 col-lg-3"')
            c = c.replace('g-3 align-items-end', 'g-2 align-items-end')
        
        with open(p, 'w', encoding='utf-8') as f:
            f.write(c)

print("Items 4 and 5 patched")
