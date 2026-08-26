import re
with open('core/urls.py', 'r', encoding='utf-8') as f:
    c = f.read()

new_urls = """path('configuracoes/hospedagem/modelo/', views.lodging_template_manage, name='lodging_template_manage'),
    path('configuracoes/hospedagem/modelo/<int:pk>/quarto/criar/', views.lodging_template_room_create, name='lodging_template_room_create'),
    path('configuracoes/hospedagem/modelo/<int:pk>/quarto/<int:room_id>/editar/', views.lodging_template_room_update, name='lodging_template_room_update'),
    path('configuracoes/hospedagem/modelo/<int:pk>/quarto/<int:room_id>/excluir/', views.lodging_template_room_delete, name='lodging_template_room_delete'),"""

c = re.sub(r'path\(\'configuracoes/hospedagem/modelo/\', views\.lodging_template_manage, name=\'lodging_template_manage\'\),', new_urls, c)

with open('core/urls.py', 'w', encoding='utf-8') as f:
    f.write(c)
print("Updated urls.py")
