import re
with open('core/templates/core/integrantes_list.html', 'r', encoding='utf-8') as f:
    c = f.read()

# Make the above-table select-all visible on both mobile and desktop
# Currently: <div class="d-md-none mb-3 px-2 mt-2">
c = c.replace('<div class="d-md-none mb-3 px-2 mt-2">', '<div class="mb-3 px-2 mt-2">')
# Also remove "Mobile" from ID just in case
c = c.replace('id="selectAllMobile"', 'id="selectAllAbove"')
c = c.replace('for="selectAllMobile"', 'for="selectAllAbove"')

# Remove the one inside the table header
c = re.sub(r'<th class="ps-4 fw-bold border-bottom-0 py-3"[^>]*>.*?</th>', '<th class="ps-4 fw-bold border-bottom-0 py-3" style="width: 50px;"></th>', c, flags=re.DOTALL)

with open('core/templates/core/integrantes_list.html', 'w', encoding='utf-8') as f:
    f.write(c)
print("Item 2 patched")
