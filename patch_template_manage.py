import re

with open('core/templates/core/room_list/lodging_template_manage.html', 'r', encoding='utf-8') as f:
    c = f.read()

# 1. Update Title and Header
c = c.replace('{% block title %}Gerenciar Hospedagem - {{ request.band.name }}', '{% block title %}Modelo Padrão de Hospedagem - {{ request.band.name }}{% endblock %}')
c = re.sub(r'<h4 class="fw-bold m-0 text-truncate".*?</h4>', '<h4 class="fw-bold m-0 text-truncate" style="max-width: 100%;">Modelo Padrão de Hospedagem</h4>', c)

# 2. Update Voltar link
c = re.sub(r'\{% url \'room_list_index\' request\.band\.slug %\}', '{% url \'configuracoes\' request.band.slug %}', c)

# 3. Remove PDF Room List button
c = re.sub(r'<a href="\{% url \'room_list_pdf\'.*?<i class="fa-solid fa-file-pdf me-2 fs-5"></i> PDF Room List\s*</a>', '', c, flags=re.DOTALL)

# 4. Remove Card Header with Show, Hotel, Status etc.
# The block is <div class="card shadow-sm p-4 mb-4">...</div>
card_block = re.search(r'<div class="card shadow-sm p-4 mb-4">.*?</div>\s*</div>\s*</div>', c, flags=re.DOTALL)
if card_block:
    new_card = """<div class="card shadow-sm p-4 mb-4">
    <div class="row">
        <div class="col-md-6">
            <p class="text-muted mb-0">Configure os quartos padrão que serão aplicados automaticamente ao criar uma nova hospedagem.</p>
        </div>
        <div class="col-12 col-md-6 text-md-end mt-3 mt-md-0">
            <button type="button" class="btn btn-primary" data-bs-toggle="modal" data-bs-target="#modalAdicionarQuarto">Adicionar Quarto</button>
        </div>
    </div>
</div>"""
    c = c.replace(card_block.group(0), new_card)

# 5. Remove "Não Alocados" column
c = re.sub(r'<div class="col-lg-5 col-xl-4">\s*<div class="sticky-top".*?<!-- FIM COLUNA NO ALOCADOS -->', '', c, flags=re.DOTALL)

# 6. Change col-lg-7 col-xl-8 to col-12 for the Quartos column
c = c.replace('class="col-lg-7 col-xl-8"', 'class="col-12"')

# 7. Update loop variables from room_list.rooms.all to template.rooms.all
c = c.replace('for room in room_list.rooms.all', 'for room in template.rooms.all')

# 8. Update room form submit URLs
c = c.replace("{% url 'room_list_room_create' request.band.slug room_list.id %}", "{% url 'lodging_template_room_create' request.band.slug template.id %}")
c = c.replace("{% url 'room_list_room_update' request.band.slug room_list.id room.id %}", "{% url 'lodging_template_room_update' request.band.slug template.id room.id %}")
c = c.replace("{% url 'room_list_room_delete' request.band.slug room_list.id room.id %}", "{% url 'lodging_template_room_delete' request.band.slug template.id room.id %}")

# 9. Remove room participant looping (since there are no participants)
participant_block = re.search(r'<div class="d-flex flex-wrap gap-2 mt-2" id="room-.*?</div>', c, flags=re.DOTALL)
if participant_block:
    c = re.sub(r'<div class="d-flex flex-wrap gap-2 mt-2" id="room-.*?</div>\s*</div>\s*</div>', '</div></div>', c, flags=re.DOTALL)

# Let's just remove the participants loop more robustly
c = re.sub(r'<div class="d-flex flex-wrap gap-2 mt-2" id="room-\{\{ room\.id \}\}">.*?</div>', '<div class="d-flex flex-wrap gap-2 mt-2"></div>', c, flags=re.DOTALL)

# 10. Fix modal IDs and clean up unused modals (like Sincronizar, Exportar PDF, Excluir Room List)
c = re.sub(r'<!-- Modal Sincronizar -->.*?</div>\s*</div>\s*</div>\s*</div>', '', c, flags=re.DOTALL)
c = re.sub(r'<!-- Modal de Excluso -->.*?</div>\s*</div>\s*</div>\s*</div>', '', c, flags=re.DOTALL)

# Ensure "Deixe em branco para 'Sem número'" is present
# It already is since we copied from room_list_manage.html

with open('core/templates/core/room_list/lodging_template_manage.html', 'w', encoding='utf-8') as f:
    f.write(c)
print("Template lodging_template_manage.html updated")
