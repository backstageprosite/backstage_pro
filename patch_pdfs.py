import re

# Fix integrantes_pdf.html footer
with open('core/templates/core/integrantes_pdf.html', 'r', encoding='utf-8') as f:
    int_html = f.read()

old_footer_int = """<div class="footer">
<div>Publicado em: {% now "d/m/Y H:i" %}</div>
<div style="margin-top: 5px;">Desenvolvido por Backstage Pro<br>@backstagepro.site</div>
</div>"""

new_footer_int = """<div class="footer" style="border-top: 1px solid #ddd; padding-top: 5px; font-size: 11px; display: flex; justify-content: space-between; align-items: center; width: 100%;">
<div style="flex: 1; text-align: left;"><strong>Publicado:</strong> {% now "d/m/Y H:i" %}</div>
<div style="flex: 1; text-align: center;">Desenvolvido por Backstage Pro<br>@backstagepro.site</div>
<div style="flex: 1; text-align: right;"></div>
</div>"""

int_html = int_html.replace(old_footer_int, new_footer_int)

with open('core/templates/core/integrantes_pdf.html', 'w', encoding='utf-8') as f:
    f.write(int_html)

# Fix room_list_pdf.html footer
with open('core/templates/core/room_list/room_list_pdf.html', 'r', encoding='utf-8') as f:
    room_html = f.read()

# Remove the extra footer at the end of the table if it exists
extra_footer_match = re.search(r'<table class="main-table" style="margin-top: 8px; border-top: 1px solid #ccc;">\s*<tr>\s*<td style="font-size: 10px; text-align: center; padding-top: 5px; color: #555;">\s*Desenvolvido por Backstage Pro<br>@backstagepro.site\s*</td>\s*</tr>\s*</table>', room_html)
if extra_footer_match:
    room_html = room_html.replace(extra_footer_match.group(0), "")

# Replace the actual footer_content div
old_footer_content = re.search(r'<div id="footer_content">.*?</div>', room_html, re.DOTALL)
if old_footer_content:
    # We want Documento: [data] Title, Desenvolvido por Backstage Pro @..., Gerado em: Date
    # Room List doesn't have show title natively in context always, it has room_list.title or band
    new_footer = """<div id="footer_content">
    <table style="width: 100%; font-size: 8px;">
        <tr>
            <td style="width: 33%; text-align: left;"><strong>Documento:</strong> [{{ show_date|date:"d-m-Y"|default:room_list.title }}] Room List</td>
            <td style="width: 34%; text-align: center;">Desenvolvido por Backstage Pro<br>@backstagepro.site</td>
            <td style="width: 33%; text-align: right;"><strong>Gerado em:</strong> {% now "d/m/Y H:i" %}</td>
        </tr>
    </table>
</div>"""
    room_html = room_html.replace(old_footer_content.group(0), new_footer)

with open('core/templates/core/room_list/room_list_pdf.html', 'w', encoding='utf-8') as f:
    f.write(room_html)

print("PDF footers updated")
