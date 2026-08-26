import re

with open('core/services/room_list_services.py', 'r', encoding='utf-8') as f:
    c = f.read()

pattern = r'number_or_name = number_or_name\.strip\(\) if number_or_name else number_or_name\s+allowed_kwargs = \{k: v for k, v in kwargs\.items\(\) if k in \{\'beds_config\', \'has_ac\', \'order\'\}\}'

replacement = """number_or_name = number_or_name.strip() if number_or_name else number_or_name

    if Room.objects.filter(room_list=locked_rl, number_or_name=number_or_name).exists():
        raise DuplicateRoomNumberError(f"Já existe um quarto '{number_or_name}' nesta Room List.")

    allowed_kwargs = {k: v for k, v in kwargs.items() if k in {'beds_config', 'has_ac', 'order'}}"""

c = re.sub(pattern, replacement, c)

with open('core/services/room_list_services.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Restored duplicate check in service.")
