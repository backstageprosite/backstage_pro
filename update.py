import os

files_to_update = [
    'core/templates/core/landing.html',
    'core/templates/core/politica_de_privacidade.html',
    'core/templates/core/termos_de_uso.html'
]

for filepath in files_to_update:
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        content = content.replace('5571982729156', '5571983474004')
        content = content.replace('98272-9156', '98347-4004')
        
        if 'landing.html' in filepath:
            old_contact = '<p class="text-muted mb-1"><i class="fa-brands fa-whatsapp me-2"></i> +55 71 98347-4004</p>'
            new_contact = old_contact + '\n                    <p class="text-muted mb-1"><a href="https://instagram.com/backstagepro.site" target="_blank" class="text-decoration-none text-muted"><i class="fa-brands fa-instagram me-2"></i>@backstagepro.site</a></p>'
            content = content.replace(old_contact, new_contact)
            
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated {filepath}")
