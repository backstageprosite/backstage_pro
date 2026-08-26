import re

with open('core/templates/core/show_pdf.html', 'r', encoding='utf-8') as f:
    content = f.read()

old_block = """                    {% if show.wardrobe or show.attractions %}
                    <div class="col-12 mb-2">
                        <div class="d-flex gap-4">
                            {% if show.wardrobe %}
                            <div class="flex-fill">
                                <h6 class="text-muted"><i class="fa-solid fa-shirt me-1"></i> Figurino</h6>
                                <p>{{ show.wardrobe|linebreaksbr }}</p>
                            </div>
                            {% endif %}
                            {% if show.wardrobe and show.attractions %}
                            <div style="border-left: 1px solid #dee2e6;"></div>
                            {% endif %}
                            {% if show.attractions %}
                            <div class="flex-fill">
                                <h6 class="text-muted"><i class="fa-solid fa-users me-1"></i> Outras Atrações no Evento</h6>
                                <p class="mb-1">{{ show.attractions|linebreaksbr }}</p>
                            </div>
                            {% endif %}
                        </div>
                    </div>
                    {% endif %}"""

new_block = """                    {% if show.wardrobe %}
                    <div class="col-6 mb-3">
                        <h6 class="text-muted"><i class="fa-solid fa-shirt me-1"></i> Figurino</h6>
                        <p>{{ show.wardrobe|linebreaksbr }}</p>
                    </div>
                    {% endif %}
                    {% if show.attractions %}
                    <div class="col-6 mb-3">
                        <h6 class="text-muted"><i class="fa-solid fa-users me-1"></i> Outras Atrações no Evento</h6>
                        <p class="mb-1">{{ show.attractions|linebreaksbr }}</p>
                    </div>
                    {% endif %}"""

content = content.replace(old_block, new_block)
with open('core/templates/core/show_pdf.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Item 8 patched")
