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
    path('relatorios/avisos/', views.band_notices_index, name='band_notices_index'),
    path('relatorios/avisos/novo/', views.band_notices_create, name='band_notices_create'),
    path('relatorios/avisos/<int:pk>/editar/', views.band_notices_edit, name='band_notices_edit'),
    path('relatorios/avisos/<int:pk>/excluir/', views.band_notices_delete, name='band_notices_delete'),
    path('parceiros/', views.partners_list_view, name='parceiros'),
    path('relatorios/assinatura/', views.minha_assinatura_view, name='minha_assinatura'),
    path('relatorios/relatorio-financeiro/', views.relatorios_view, name='relatorio_financeiro'),
    
    # Rider
    path('relatorios/rider/', views.rider_list_view, name='rider_list'),
    path('relatorios/rider/<int:pk>/download/', file_views.download_rider, name='download_rider'),
    path('relatorios/rider/<int:pk>/preview/', file_views.preview_rider, name='preview_rider'),
    path('rider/publico/<uuid:uuid>/', file_views.public_rider_download, name='public_rider_download'),
    
    # Integrantes
    path('relatorios/integrantes/', views.integrantes_list_view, name='integrantes_list'),
    path('relatorios/integrantes/pdf/', views.integrantes_pdf_view, name='integrantes_pdf'),
    path('relatorios/integrantes/<int:pk>/excluir/', views.integrante_delete_view, name='integrante_delete'),
    path('relatorios/integrantes/reorder/', views.integrantes_reorder_view, name='integrantes_reorder'),
    
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

urlpatterns += [
    # Room List - WEB-02A
    path('relatorios/hospedagem/', views.room_list_index, name='room_list_index'),
    path('relatorios/hospedagem/nova/', views.room_list_select_show, name='room_list_select_show'),
    path('shows/<int:show_id>/hospedagem/criar/', views.room_list_create, name='room_list_create'),
    path('hospedagem/<int:pk>/editar/', views.room_list_edit, name='room_list_edit'),


    path('hospedagem/<int:pk>/', views.room_list_manage, name='room_list_manage'),
    path('hospedagem/<int:pk>/excluir/', views.room_list_delete, name='room_list_delete'),
    
    # Quartos
    path('hospedagem/<int:pk>/quartos/criar/', views.room_list_room_create, name='room_list_room_create'),
    path('hospedagem/<int:pk>/quartos/<int:room_id>/editar/', views.room_list_room_edit, name='room_list_room_edit'),
    path('hospedagem/<int:pk>/quartos/<int:room_id>/excluir/', views.room_list_room_delete, name='room_list_room_delete'),
    # Sincronização e Operações
    path('hospedagem/<int:pk>/sincronizar/', views.room_list_sync, name='room_list_sync'),
    path('hospedagem/<int:pk>/participantes/<int:participant_id>/alocar/', views.room_list_allocate, name='room_list_allocate'),
    path('hospedagem/<int:pk>/participantes/<int:participant_id>/desalocar/', views.room_list_unassign, name='room_list_unassign'),
    path('hospedagem/<int:pk>/participantes/<int:participant_id>/excluir/', views.room_list_participant_delete, name='room_list_participant_delete'),
    path('hospedagem/<int:pk>/acoes/publicar/', views.room_list_publish, name='room_list_publish'),
    path('hospedagem/<int:pk>/acoes/reabrir/', views.room_list_reopen, name='room_list_reopen'),
    path('hospedagem/<int:pk>/acoes/arquivar/', views.room_list_archive, name='room_list_archive'),
    path('hospedagem/<int:pk>/acoes/reativar/', views.room_list_reactivate, name='room_list_reactivate'),
    path('hospedagem/<int:pk>/acoes/marcar-enviada/', views.room_list_mark_sent, name='room_list_mark_sent'),
    path('hospedagem/<int:pk>/acoes/aplicar-modelo/', views.room_list_apply_template, name='room_list_apply_template'),

    # Modelo Padrão
    path('configuracoes/hospedagem/modelo/', views.lodging_template_manage, name='lodging_template_manage'),
    path('configuracoes/hospedagem/modelo/<int:pk>/quarto/criar/', views.lodging_template_room_create, name='lodging_template_room_create'),
    path('configuracoes/hospedagem/modelo/<int:pk>/quarto/<int:room_id>/editar/', views.lodging_template_room_update, name='lodging_template_room_update'),
    path('configuracoes/hospedagem/modelo/<int:pk>/quarto/<int:room_id>/excluir/', views.lodging_template_room_delete, name='lodging_template_room_delete'),
    
    # Room List
    path('hospedagem/<int:pk>/pdf/', views.room_list_pdf_view, name='room_list_pdf'),
    path('hospedagem/<int:pk>/pdf/hotel/', views.room_list_hotel_pdf_view, name='room_list_hotel_pdf'),
    path('hospedagem/quarto/<int:room_pk>/delete/', views.delete_room_view, name='delete_room'),
]