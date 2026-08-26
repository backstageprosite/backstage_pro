with open('core/templates/core/integrantes_list.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()
for i, line in enumerate(lines):
    if 'id="selectAll"' in line:
        print(''.join(lines[i-2:i+3]))
