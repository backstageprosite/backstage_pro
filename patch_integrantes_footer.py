import re

with open('core/templates/core/integrantes_pdf.html', 'r', encoding='utf-8') as f:
    int_html = f.read()

# Replace the entire footer div
new_footer_int = """<div class="footer" style="border-top: 1px solid #ddd; padding-top: 5px; font-size: 11px; display: flex; justify-content: space-between; align-items: center; width: 100%;">
<div style="flex: 1; text-align: left;"><strong>Publicado:</strong> {% now "d/m/Y H:i" %}</div>
<div style="flex: 1; text-align: center;">Desenvolvido por Backstage Pro<br>@backstagepro.site</div>
<div style="flex: 1; text-align: right;"></div>
</div>"""

int_html = re.sub(r'<div class="footer">.*?</div>\s*</div>', new_footer_int, int_html, flags=re.DOTALL)

with open('core/templates/core/integrantes_pdf.html', 'w', encoding='utf-8') as f:
    f.write(int_html)
