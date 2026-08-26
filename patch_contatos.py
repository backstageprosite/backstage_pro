import re

with open('core/templates/core/contatos.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace <span class="badge ..."> with <span class="badge ..." style="min-width: 130px; display: inline-block; text-align: center;">
content = re.sub(
    r'(<span class="badge [^"]+")',
    r'\1 style="min-width: 130px; display: inline-block; text-align: center;"',
    content
)

# Fix possible duplication
content = content.replace('style="min-width: 130px; display: inline-block; text-align: center;" style="min-width: 130px; display: inline-block; text-align: center;"', 'style="min-width: 130px; display: inline-block; text-align: center;"')

with open('core/templates/core/contatos.html', 'w', encoding='utf-8') as f:
    f.write(content)

