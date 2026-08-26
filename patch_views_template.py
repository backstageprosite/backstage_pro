import re

with open('core/views.py', 'r', encoding='utf-8') as f:
    c = f.read()

old_func = r'def lodging_template_manage\(request, band_slug\):.*?return render\(request, \'core/room_list/lodging_template_manage\.html\', \{.*?\}\)'

new_func = """def lodging_template_manage(request, band_slug):
    from core.models import LodgingTemplate
    band = request.band
    template, created = LodgingTemplate.objects.get_or_create(band=band)
    
    return render(request, 'core/room_list/lodging_template_manage.html', {
        'band': band,
        'template': template,
    })

def lodging_template_room_create(request, band_slug, pk):
    from core.models import LodgingTemplate, TemplateRoom
    template = get_object_or_404(LodgingTemplate, pk=pk, band=request.band)
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
            
            for i in range(1, quantity + 1):
                final_name = room_number
                if quantity > 1:
                    final_name = f"{room_number}_{i:02d}"
                
                counter = i if quantity > 1 else 1
                while TemplateRoom.objects.filter(template=template, name=final_name).exists():
                    final_name = f"{room_number}_{counter:02d}"
                    counter += 1
                
                TemplateRoom.objects.create(
                    template=template,
                    name=final_name,
                    type=room_type,
                    capacity=int(capacity),
                    beds_config=beds_config,
                    has_ac=has_ac
                )
            
            msg = f"1 quarto adicionado com sucesso." if quantity == 1 else f"{quantity} quartos adicionados com sucesso."
            messages.success(request, msg)
        except Exception as e:
            messages.error(request, f"Erro ao criar quartos: {str(e)}")
    return redirect('lodging_template_manage', band_slug=band_slug)

def lodging_template_room_update(request, band_slug, pk, room_id):
    from core.models import LodgingTemplate, TemplateRoom
    template = get_object_or_404(LodgingTemplate, pk=pk, band=request.band)
    room = get_object_or_404(TemplateRoom, pk=room_id, template=template)
    
    if request.method == 'POST':
        try:
            room_number = request.POST.get('number_or_name', '').strip()
            if not room_number:
                room_number = 'Sem número'
                
            # Allow same name if it's the current room
            if TemplateRoom.objects.filter(template=template, name=room_number).exclude(pk=room.pk).exists():
                messages.error(request, f"Já existe um quarto '{room_number}' neste modelo.")
            else:
                room.name = room_number
                room.type = request.POST.get('type')
                room.capacity = int(request.POST.get('capacity', 1))
                room.beds_config = request.POST.get('beds_config', '')
                room.has_ac = request.POST.get('has_ac') == 'on'
                room.save()
                messages.success(request, "Quarto atualizado com sucesso.")
        except Exception as e:
            messages.error(request, f"Erro ao atualizar quarto: {str(e)}")
            
    return redirect('lodging_template_manage', band_slug=band_slug)

def lodging_template_room_delete(request, band_slug, pk, room_id):
    from core.models import LodgingTemplate, TemplateRoom
    template = get_object_or_404(LodgingTemplate, pk=pk, band=request.band)
    room = get_object_or_404(TemplateRoom, pk=room_id, template=template)
    
    if request.method == 'POST':
        room.delete()
        messages.success(request, "Quarto excluído com sucesso.")
        
    return redirect('lodging_template_manage', band_slug=band_slug)
"""

c = re.sub(old_func, new_func, c, flags=re.DOTALL)

with open('core/views.py', 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated views.py")
