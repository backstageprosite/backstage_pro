import re

with open('core/models.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace(
    "class TemplateRoom(models.Model):\n    template = models.ForeignKey(LodgingTemplate, on_delete=models.CASCADE, related_name='rooms')\n    type = models.CharField(",
    "class TemplateRoom(models.Model):\n    template = models.ForeignKey(LodgingTemplate, on_delete=models.CASCADE, related_name='rooms')\n    name = models.CharField(max_length=50, blank=True, null=True, verbose_name='Número ou Nome')\n    type = models.CharField("
)

with open('core/models.py', 'w', encoding='utf-8') as f:
    f.write(c)

print("Added name to TemplateRoom")
