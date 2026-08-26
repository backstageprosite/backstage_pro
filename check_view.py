with open('core/views.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if 'def room_list_room_create' in line:
        print(''.join(lines[i:i+30]))
