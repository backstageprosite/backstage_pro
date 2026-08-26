import re
with open('core/templates/core/contatos.html', 'r', encoding='utf-8') as f:
    c = f.read()

for m in re.finditer(r'<button[^>]+data-bs-target="#modalContato[^>]+>.*?</button>', c, re.DOTALL):
    print("Found:", m.group(0))

# Try replacing the actual content
c_new = re.sub(
    r'(<button type="button" class="btn btn-sm btn-link text-decoration-none p-0" data-bs-toggle="modal" data-bs-target="#modalContato-[0-9]+">).*?(</button>)',
    r'\1<i class="fa-solid fa-eye text-secondary border rounded-circle p-2 bg-light shadow-sm" style="font-size: 1.1rem; width: 35px; height: 35px; display: inline-flex; justify-content: center; align-items: center;"></i>\2',
    c,
    flags=re.DOTALL
)

with open('core/templates/core/contatos.html', 'w', encoding='utf-8') as f:
    f.write(c_new)
print("Done")
