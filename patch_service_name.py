import re

with open('core/services/room_list_services.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace(
    'number_or_name = f"Quarto {idx}"',
    'number_or_name = t_room.name if t_room.name else f"Quarto {idx}"'
)

with open('core/services/room_list_services.py', 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated room list services name transfer")
