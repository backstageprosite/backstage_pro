import re

# Fix view core/views.py
with open('core/views.py', 'r', encoding='utf-8') as f:
    views_py = f.read()

view_old = """    if request.method == 'POST':
        form = RoomForm(request.POST)
        if form.is_valid():
            try:
                data = form.cleaned_data.copy()
                quantity = int(request.POST.get('quantity', 1))
                room_number = data.pop('number_or_name')
                if not room_number:
                    room_number = 'Sem número'
                
                for _ in range(quantity):
                    room_list_services.create_room(
                        room_list_id=room_list.id,
                        room_type=data.get('type'),
                        capacity=data.get('capacity'),
                        number_or_name=room_number,
                        user=request.user,
                        beds_config=data.get('beds_config'),
                        has_ac=data.get('has_ac', False)
                    )
                msg = f"1 quarto adicionado com sucesso." if quantity == 1 else f"{quantity} quartos adicionados com sucesso."
                messages.success(request, msg)
                return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)
            except Exception as e:
                messages.error(request, str(e))
        else:
            form = RoomForm()

    return render(request, 'core/room_list/room_form.html', {"""

view_new = """    if request.method == 'POST':
        try:
            quantity = int(request.POST.get('quantity', 1))
            room_number = request.POST.get('number_or_name', '').strip()
            if not room_number:
                room_number = 'Sem número'
                
            room_type = request.POST.get('type')
            capacity = request.POST.get('capacity', 1)
            beds_config = request.POST.get('beds_config', '')
            has_ac = request.POST.get('has_ac') == 'on'
            
            for _ in range(quantity):
                room_list_services.create_room(
                    room_list_id=room_list.id,
                    room_type=room_type,
                    capacity=int(capacity),
                    number_or_name=room_number,
                    user=request.user,
                    beds_config=beds_config,
                    has_ac=has_ac
                )
            msg = f"1 quarto adicionado com sucesso." if quantity == 1 else f"{quantity} quartos adicionados com sucesso."
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, str(e))
        return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)

    return render(request, 'core/room_list/room_form.html', {"""

views_py = views_py.replace(view_old, view_new)
with open('core/views.py', 'w', encoding='utf-8') as f:
    f.write(views_py)

# Fix HTML choices in room_list_manage.html
with open('core/templates/core/room_list/room_list_manage.html', 'r', encoding='utf-8') as f:
    manage_html = f.read()

html_old = """                        <select name="type" class="form-select" required>
                            <option value="SGL">Single (SGL) - 1 pessoa</option>
                            <option value="DBL">Double (DBL) - 2 pessoas</option>
                            <option value="TPL">Triple (TPL) - 3 pessoas</option>
                            <option value="QPL">Quadruple (QPL) - 4 pessoas</option>
                            <option value="EXC">Executive/Suite (EXC)</option>
                        </select>"""

html_new = """                        <select name="type" class="form-select" required>
                            <option value="INDIVIDUAL">Individual (1 pessoa)</option>
                            <option value="CASAL">Casal (2 pessoas)</option>
                            <option value="DUPLO">Duplo (2 pessoas)</option>
                            <option value="TRIPLO">Triplo (3 pessoas)</option>
                            <option value="QUADRUPLO">Quádruplo (4 pessoas)</option>
                            <option value="PERSONALIZADO">Personalizado</option>
                        </select>"""

manage_html = manage_html.replace(html_old, html_new)
with open('core/templates/core/room_list/room_list_manage.html', 'w', encoding='utf-8') as f:
    f.write(manage_html)

print("Item 6 patched")
