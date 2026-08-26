import re

with open('core/views.py', 'r', encoding='utf-8') as f:
    c = f.read()

# Replace room_list_room_create entirely.
match = re.search(r'def room_list_room_create.*?return render\(request, \'core/room_list/room_form\.html\', \{.*?\}\)', c, re.DOTALL)
if match:
    new_func = """def room_list_room_create(request, band_slug, pk):
    try:
        room_list = room_list_services.get_room_list_for_band(pk, request.band)
    except RoomListNotFoundError:
        raise Http404("Room List não encontrada.")

    if request.method == 'POST':
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

    # In case they GET this view directly, redirect them to manage.
    return redirect('room_list_manage', band_slug=band_slug, pk=room_list.id)"""
    c = c.replace(match.group(0), new_func)

with open('core/views.py', 'w', encoding='utf-8') as f:
    f.write(c)
print("View replaced")
