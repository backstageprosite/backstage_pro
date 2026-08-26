import re

with open('core/views.py', 'r', encoding='utf-8') as f:
    c = f.read()

old_loop = r"""for _ in range\(quantity\):
                room_list_services\.create_room\(
                    room_list_id=room_list\.id,
                    room_type=room_type,
                    capacity=int\(capacity\),
                    number_or_name=room_number,
                    user=request\.user,
                    beds_config=beds_config,
                    has_ac=has_ac
                \)"""

new_loop = """from core.models import Room
            for i in range(1, quantity + 1):
                final_name = room_number
                if quantity > 1:
                    final_name = f"{room_number}_{i:02d}"
                
                # Ensure uniqueness to avoid DuplicateRoomNumberError
                counter = i if quantity > 1 else 1
                while Room.objects.filter(room_list=room_list, number_or_name=final_name).exists():
                    final_name = f"{room_number}_{counter:02d}"
                    counter += 1
                
                room_list_services.create_room(
                    room_list_id=room_list.id,
                    room_type=room_type,
                    capacity=int(capacity),
                    number_or_name=final_name,
                    user=request.user,
                    beds_config=beds_config,
                    has_ac=has_ac
                )"""

c = re.sub(old_loop, new_loop, c, flags=re.DOTALL)

with open('core/views.py', 'w', encoding='utf-8') as f:
    f.write(c)
print("Item 2 patched")
