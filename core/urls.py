from django.urls import path
from . import views, pwa_views, file_views, notification_views, push_views, views_support
urlpatterns = [
    path('manifest.webmanifest', pwa_views.band_manifest, name='manifest'),
    path('sw.js', pwa_views.band_service_worker, name='band_sw'),
    path('pwa/<str:filename>', pwa_views.band_icon_view, name='band_icon'),

    # Web Push Endpoints (Etapa 7B.1)
    path('push/chave-publica/', push_views.push_public_key, name='push_public_key'),
    path('push/status/', push_views.push_subscription_status, name='push_subscription_status'),
    path('push/inscrever/', push_views.push_subscribe, name='push_subscribe'),
    path('push/desinscrever/', push_views.push_unsubscribe, name='push_unsubscribe'),
    path('', views.band_root_redirect_view, name='band_root'),
    path('instalar-aplicativo/', views.instalar_aplicativo_view, name='instalar_aplicativo'),
    path('calendario/', views.calendario, name='calendario'),
    path('painel/', views.dashboard_view, name='dashboard'),
    path('pendencias/', views.pending_list_view, name='pendencias'),
    path('dashboard/pendencias/adicionar/', views.add_dashboard_pending_item, name='add_dashboard_pending_item'),
    path('dashboard/pendencias/<int:pending_id>/editar/', views.edit_dashboard_pending_item, name='edit_dashboard_pending_item'),
    path('dashboard/pendencias/<int:pending_id>/excluir/', views.delete_dashboard_pending_item, name='delete_dashboard_pending_item'),
    path('shows/', views.shows_list_view, name='shows_list'),
    path('shows/add/', views.show_create_view, name='shows_add'),
    path('shows/<int:pk>/change/', views.show_edit_view, name='shows_edit'),
    path('shows/<int:pk>/delete/', views.show_delete_view, name='shows_delete'),
    path('usuarios/', views.usuarios_list_view, name='usuarios_list'),
    path('usuarios/add/', views.usuario_create_view, name='usuarios_add'),
    path('usuarios/<int:pk>/change/', views.usuario_edit_view, name='usuarios_edit'),
    path('usuarios/<int:pk>/delete/', views.usuario_delete_view, name='usuarios_delete'),
    path('usuarios/<int:pk>/reset-password/', views.usuario_reset_password_view, name='usuarios_reset_password'),
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
    path('parceiros/', views.partners_list_view, name='parceiros'),
    path('relatorios/assinatura/', views.minha_assinatura_view, name='minha_assinatura'),
    path('relatorios/relatorio-financeiro/', views.relatorios_view, name='relatorio_financeiro'),
    
    # Fale Conosco - Produtor
    path('relatorios/fale-conosco/', views_support.support_list_view, name='support_list'),
    path('relatorios/fale-conosco/novo/', views_support.support_create_view, name='support_create'),
    path('relatorios/fale-conosco/<int:pk>/', views_support.support_detail_view, name='support_detail'),
    path('relatorios/fale-conosco/<int:pk>/reabrir/', views_support.support_reopen_view, name='support_reopen'),

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

    # Notificações
    path('notificacoes/', notification_views.notifications_list, name='notifications_list'),
    path('notificacoes/<int:pk>/abrir/', notification_views.notification_open, name='notification_open'),
    path('notificacoes/<int:pk>/marcar-lida/', notification_views.notification_mark_read, name='notification_mark_read'),
    path('notificacoes/marcar-todas-lidas/', notification_views.notifications_mark_all_read, name='notifications_mark_all_read'),

    # Arquivos Seguros
    path('assets/logo/', file_views.public_band_logo, name='public_band_logo'),
    path('admin/assets/logo/', file_views.admin_band_logo, name='admin_band_logo'),
    path('documentos/contratos/<int:pk>/download/', file_views.download_contract, name='download_contract'),
    path('documentos/contratos/<int:pk>/preview/', file_views.preview_contract, name='preview_contract'),
    path('financeiro/recebimentos/<int:pk>/download/', file_views.download_receipt, name='download_receipt'),
    path('financeiro/recebimentos/<int:pk>/preview/', file_views.preview_receipt, name='preview_receipt'),
    path('financeiro/pagamentos/<int:pk>/download/', file_views.download_payment, name='download_payment'),
    path('financeiro/pagamentos/<int:pk>/preview/', file_views.preview_payment, name='preview_payment'),
    path('faturas/<int:pk>/download/', file_views.download_billing, name='download_billing'),
    path('faturas/<int:pk>/preview/', file_views.preview_billing, name='preview_billing'),
    
    # Anexos do Fale Conosco
    path('fale-conosco/anexos/<int:pk>/download/', file_views.download_support_attachment, name='download_support_attachment'),
    path('fale-conosco/anexos/<int:pk>/preview/', file_views.preview_support_attachment, name='preview_support_attachment'),
    
    # Visualizador HTML Dedicado PWA
    path('arquivos/visualizar/<str:file_type>/<int:pk>/', file_views.internal_file_viewer, name='file_viewer'),
]
