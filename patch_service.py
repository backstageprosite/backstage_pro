import re
with open('core/services/room_list_services.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = re.sub(
    r'if Room\.objects\.filter\(room_list=locked_rl, number_or_name=number_or_name\)\.exists\(\):\s*raise DuplicateRoomNumberError\(.*?\)',
    '',
    c,
    flags=re.DOTALL
)

with open('core/services/room_list_services.py', 'w', encoding='utf-8') as f:
    f.write(c)
print("Removed duplicate check")
