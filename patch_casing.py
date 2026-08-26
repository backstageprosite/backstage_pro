import os
import re

for root, _, files in os.walk('core/templates'):
    for file in files:
        if file.endswith('.html'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if 'Instalar aplicativo' in content:
                new_content = content.replace('Instalar aplicativo', 'Instalar Aplicativo')
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Patched {filepath}")
