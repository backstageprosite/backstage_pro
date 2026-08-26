import re
c = open('core/templates/core/room_list/room_list_manage.html', 'r', encoding='utf-8').read()
m = re.search(r'<div class="modal fade" id="modalAdicionarQuarto".*?</form>', c, re.DOTALL)
if m:
    print(m.group(0))
else:
    print("Not found")
