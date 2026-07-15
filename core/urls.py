from django.urls import path
from . import views, pwa_views, file_views

urlpatterns = [
    path('manifest.webmanifest', pwa_views.band_manifest, name='manifest'),
    path('sw.js', pwa_views.band_service_worker, name='band_sw'),
    path('pwa/<str:filename>', pwa_views.band_icon_view, name='band_icon'),
    path('calendario/', views.calendario, name='calendario'),
    path('painel/', views.dashboard_view, name='dashboard'),
    path('shows/', views.shows_list_view, name='shows_list'),
    path('shows/add/', views.show_create_view, name='shows_add'),
    path('shows/<int:pk>/change/', views.show_edit_view, name='shows_edit'),
    path('shows/<int:pk>/delete/', views.show_delete_view, name='shows_delete'),
    path('usuarios/', views.usuarios_list_view, name='usuarios_list'),
    path('usuarios/add/', views.usuario_create_view, name='usuarios_add'),
    path('usuarios/<int:pk>/change/', views.usuario_edit_view, name='usuarios_edit'),
    path('usuarios/<int:pk>/delete/', views.usuario_delete_view, name='usuarios_delete'),
    path('contatos/', views.contatos_list_view, name='contatos_list'),
    path('contatos/add/', views.contato_create_view, name='contatos_add'),
    path('contatos/<int:pk>/change/', views.contato_edit_view, name='contatos_edit'),
    path('contatos/<int:pk>/delete/', views.contato_delete_view, name='contatos_delete'),
    
    path('login/', views.BandLoginView.as_view(), name='login'),
    path('logout/', views.band_logout, name='logout'),
    path('show/<int:pk>/', views.show_detail, name='show_detail'),
    path('show/<int:pk>/financeiro/', views.show_finance_detail_view, name='show_finance_detail'),
    path('show/<int:pk>/pdf/', views.show_pdf_view, name='show_pdf'),
    path('agenda/pdf/', views.agenda_pdf_view, name='agenda_pdf'),

    path('relatorios/', views.relatorios_index_view, name='relatorios_index'),
    path('relatorios/assinatura/', views.minha_assinatura_view, name='minha_assinatura'),
    path('relatorios/relatorio-financeiro/', views.relatorios_view, name='relatorio_financeiro'),
    path('arquivos/', views.arquivos_view, name='arquivos'),
    path('configuracoes/', views.configuracoes_view, name='configuracoes'),
    
    path('shows/<int:show_id>/pagamentos/novo/', views.payment_create_view, name='payment_create'),
    path('pagamentos/<int:pk>/editar/', views.payment_edit_view, name='payment_edit'),
    path('pagamentos/<int:pk>/excluir/', views.payment_delete_view, name='payment_delete'),
    
    path('comprovantes/<int:pk>/editar/', views.receipt_edit_view, name='receipt_edit'),
    path('comprovantes/<int:pk>/excluir/', views.receipt_delete_view, name='receipt_delete'),
    path('documentos/<int:pk>/editar/', views.document_edit_view, name='document_edit'),
    path('documentos/<int:pk>/excluir/', views.document_delete_view, name='document_delete'),
    
    path('shows/<int:show_id>/equipe/gerenciar/', views.manage_team_costs_view, name='manage_team_costs'),
    path('equipe/custo/<int:pk>/excluir/', views.teamcost_delete_view, name='teamcost_delete'),
    path('equipe/custo/<int:pk>/editar/', views.teamcost_edit_view, name='teamcost_edit'),

    # Arquivos Seguros
    path('assets/logo/', file_views.public_band_logo, name='public_band_logo'),
    path('admin/assets/logo/', file_views.admin_band_logo, name='admin_band_logo'),
    path('documentos/contratos/<int:pk>/download/', file_views.download_contract, name='download_contract'),
    path('financeiro/recebimentos/<int:pk>/download/', file_views.download_receipt, name='download_receipt'),
    path('financeiro/pagamentos/<int:pk>/download/', file_views.download_payment, name='download_payment'),
    path('faturas/<int:pk>/download/', file_views.download_billing, name='download_billing'),
]
