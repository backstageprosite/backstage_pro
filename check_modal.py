import re
with open('core/templates/core/room_list/room_list_manage.html', 'r', encoding='utf-8') as f:
    c = f.read()

m = re.search(r'<div class="modal fade" id="modalAdicionarQuarto".*?</div>\s*</div>\s*</div>\s*</div>', c, re.DOTALL)
if m:
    print(m.group(0))
