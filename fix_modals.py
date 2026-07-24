import re

def fix_modals(filepath, item_name, items_name):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    modals = []
    
    # We will search for all modals inside the table. The table ends around </table
    table_end_idx = content.find('</table>')
    if table_end_idx == -1: return
    
    table_content = content[:table_end_idx]
    rest_content = content[table_end_idx:]
    
    while True:
        # Find any <div class="modal...
        match = re.search(r'(\s*<!--.*?-->\s*)?<div class="modal fade[^"]*"', table_content)
        if not match:
            break
            
        start_idx = match.start()
        
        div_count = 0
        end_idx = -1
        i = table_content.find('<div class="modal fade', start_idx)
        
        while i < len(table_content):
            if table_content.startswith('<div', i):
                div_count += 1
                i += 4
            elif table_content.startswith('</div', i):
                div_count -= 1
                i += 5
                if div_count == 0:
                    end_idx = i + 1
                    break
            else:
                i += 1
                
        if end_idx == -1:
            break
            
        modal_content = table_content[start_idx:end_idx]
        modals.append(modal_content)
        
        table_content = table_content[:start_idx] + table_content[end_idx:]

    if not modals:
        print(f"No modals found inside table in {filepath}")
        return

    content = table_content + rest_content
    modals_str = f"\n{{% for {item_name} in {items_name} %}}\n" + "\n".join(modals) + f"\n{{% endfor %}}\n"
    
    if '<script>' in content:
        content = content.replace('<script>', modals_str + '\n<script>')
    else:
        content = content.replace('{% endblock %}', modals_str + '\n{% endblock %}')
        
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Successfully moved {len(modals)} modals in {filepath}")

fix_modals('core/templates/core/usuarios.html', 'usuario', 'usuarios')
fix_modals('core/templates/core/admin/usuarios.html', 'usuario', 'usuarios')
fix_modals('core/templates/core/contatos.html', 'contato', 'contatos')
