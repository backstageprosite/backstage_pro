import re

with open('core/templates/core/contatos.html', 'r', encoding='utf-8') as f:
    c = f.read()

# Replace the notes column
old_td = '<td class="fw-medium text-dark">{{ contato.notes|default:"-" }}</td>'
new_td = """<td class="text-center">
    {% if contato.notes %}
    <button class="btn btn-sm btn-outline-primary" data-bs-toggle="modal" data-bs-target="#modalObsContato{{ contato.id }}" title="Ver Observações">
        <i class="fa-solid fa-eye"></i>
    </button>
    {% else %}
    <span class="text-muted">-</span>
    {% endif %}
</td>"""

c = c.replace(old_td, new_td)

# Add the modal after the delete modal
modal = """<!-- Delete Modal -->
                            <div class="modal fade" id="deleteModal{{ contato.id }}" tabindex="-1" aria-hidden="true">"""

obs_modal = """<!-- Obs Modal -->
                            <div class="modal fade" id="modalObsContato{{ contato.id }}" tabindex="-1" aria-hidden="true">
                                <div class="modal-dialog modal-dialog-centered">
                                    <div class="modal-content border-0 shadow-lg text-start" style="border-radius: 12px;">
                                        <div class="modal-header border-bottom-0 pb-0">
                                            <h5 class="modal-title fw-bold text-dark"><i class="fa-solid fa-file-lines me-2 text-primary"></i> Observações</h5>
                                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                                        </div>
                                        <div class="modal-body py-4">
                                            <p class="mb-0" style="white-space: pre-wrap;">{{ contato.notes }}</p>
                                        </div>
                                        <div class="modal-footer border-top-0 pt-0">
                                            <button type="button" class="btn btn-light rounded-pill px-4 fw-bold" data-bs-dismiss="modal">Fechar</button>
                                        </div>
                                    </div>
                                </div>
                            </div>
                            
                            <!-- Delete Modal -->
                            <div class="modal fade" id="deleteModal{{ contato.id }}" tabindex="-1" aria-hidden="true">"""

c = c.replace(modal, obs_modal)

# Also fix the table header center alignment for Observacoes if needed, but it's probably fine.
c = c.replace('<th class="py-3">Observações</th>', '<th class="py-3 text-center">Observações</th>')

with open('core/templates/core/contatos.html', 'w', encoding='utf-8') as f:
    f.write(c)
print("Item 4 patched")
