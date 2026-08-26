import re

with open('core/templates/core/room_list/room_list_manage.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace flex-fill with a regular button class for the main PDF
content = content.replace('btn btn-dark flex-fill mb-md-2', 'btn btn-dark mb-md-2')
content = content.replace('btn btn-dark mb-md-2 flex-fill px-1', 'btn btn-dark mb-md-2')
content = content.replace('btn btn-dark mb-2 flex-fill px-1', 'btn btn-dark mb-2')
content = content.replace('class="btn btn-dark mb-md-2 btn-sm flex-fill px-1"', 'class="btn btn-dark mb-md-2 btn-sm px-3"')
content = content.replace('class="btn btn-dark mb-2 btn-sm flex-fill px-1"', 'class="btn btn-dark mb-2 btn-sm px-3"')

with open('core/templates/core/room_list/room_list_manage.html', 'w', encoding='utf-8') as f:
    f.write(content)
print("Item 2 applied")
