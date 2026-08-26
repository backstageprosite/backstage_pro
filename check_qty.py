import re
with open('core/templates/core/room_list/room_list_manage.html', 'r', encoding='utf-8') as f:
    c = f.read()
if 'name="quantity"' in c:
    print("Found name='quantity'")
else:
    print("Not found name='quantity'")
