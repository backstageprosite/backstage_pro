import re

with open('core/templates/core/room_list/room_list_manage.html', 'r', encoding='utf-8') as f:
    c = f.read()

# Replace the top header
old_header = """<div class="d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-3 mb-4">
    <h4 class="fw-bold m-0 text-truncate" style="max-width: 100%;">Gerenciar Hospedagem: <span class="text-primary">{{ room_list.show.city }}</span></h4>
    <a href="{% url 'room_list_index' request.band.slug %}" class="btn btn-outline-dark rounded-pill fw-bold px-3"><i class="fa-solid fa-arrow-left me-1"></i> Voltar</a>
</div>"""

new_header = """<div class="d-flex flex-column flex-md-row justify-content-between align-items-md-center gap-3 mb-4">
    <h4 class="fw-bold m-0 text-truncate" style="max-width: 100%;">Gerenciar Hospedagem: <span class="text-primary">{{ room_list.show.city }}</span></h4>
    <div class="d-flex flex-wrap gap-2 justify-content-md-end">
        <a href="{% url 'room_list_index' request.band.slug %}" class="btn btn-outline-dark rounded-pill fw-bold px-3 d-flex align-items-center"><i class="fa-solid fa-arrow-left me-1"></i> Voltar</a>
        <a href="{% url 'room_list_pdf' request.band.slug room_list.id %}" target="_blank" class="btn btn-dark rounded-pill shadow-sm px-4 fw-bold d-flex align-items-center transition-hover">
            <i class="fa-solid fa-file-pdf me-2 fs-5"></i> PDF Room List
        </a>
    </div>
</div>"""

c = c.replace(old_header, new_header)

# Remove the old PDF Room List buttons
# We can just match the block where they are defined and remove them.
# The user wants "o botão PDF Room List". The old ones look like:
# <a href="{% url 'room_list_pdf' request.band.slug room_list.id %}" target="_blank" class="btn btn-dark btn-sm px-3 "><i class="fa-solid fa-file-pdf"></i> PDF Room List</a>
c = re.sub(r'<a href="{% url \'room_list_pdf\'[^>]*><i class="fa-solid fa-file-pdf"></i> PDF Room List</a>', '', c)

with open('core/templates/core/room_list/room_list_manage.html', 'w', encoding='utf-8') as f:
    f.write(c)
print("Item 1 patched")
