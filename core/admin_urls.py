from django.urls import path
from . import admin_views, pwa_views, admin_views_support, admin_views_expenses, admin_views_database

app_name = 'admin_painel'

urlpatterns = [
    path('manifest.webmanifest', pwa_views.admin_manifest, name='manifest'),
    path('sw.js', pwa_views.admin_service_worker, name='admin_sw'),
    path('', admin_views.AdminDashboardView.as_view(), name='dashboard'),
    path('login/', admin_views.AdminLoginView.as_view(), name='login'),
    path('logout/', admin_views.admin_logout, name='logout'),
    
    path('bandas/', admin_views.AdminBandListView.as_view(), name='bandas'),
    path('bandas/nova/', admin_views.admin_band_create, name='bandas_nova'),
    path('bandas/<int:pk>/editar/', admin_views.admin_band_edit, name='bandas_editar'),
    path('bandas/<int:pk>/desativar/', admin_views.admin_band_toggle_active, name='bandas_desativar'),
    path('bandas/<int:pk>/criar-cobranca/', admin_views.admin_band_create_charge, name='bandas_criar_cobranca'),
    
    path('usuarios/', admin_views.AdminUserListView.as_view(), name='usuarios'),
    path('usuarios/novo/', admin_views.admin_user_create, name='usuarios_novo'),
    path('usuarios/<int:pk>/editar/', admin_views.admin_user_edit, name='usuarios_editar'),
    path('usuarios/<int:pk>/desativar/', admin_views.admin_user_toggle_active, name='usuarios_desativar'),
    path('usuarios/<int:pk>/resetar-senha/', admin_views.admin_user_reset_password, name='usuarios_resetar_senha'),
    
    path('avisos/', admin_views.AdminAvisosView.as_view(), name='avisos'),
    path('avisos/novo/', admin_views.admin_aviso_create, name='avisos_novo'),
    path('avisos/<int:pk>/editar/', admin_views.admin_aviso_edit, name='avisos_editar'),
    path('avisos/<int:pk>/excluir/', admin_views.admin_aviso_delete, name='avisos_excluir'),
    
    path('shows/', admin_views.AdminShowListView.as_view(), name='shows'),
    
    path('assinaturas/', admin_views.AdminAssinaturasView.as_view(), name='assinaturas'),
    path('assinaturas/gerar-cobranca/', admin_views.admin_band_create_charge, name='assinaturas_gerar_cobranca'),
    path('assinaturas/nova/', admin_views.admin_assinatura_create, name='assinaturas_nova'),
    path('assinaturas/<int:pk>/editar/', admin_views.admin_assinatura_edit, name='assinaturas_editar'),
    path('assinaturas/<int:pk>/cancelar/', admin_views.admin_assinatura_cancel, name='assinaturas_cancelar'),
    path('assinaturas/<int:pk>/status/', admin_views.admin_assinatura_status, name='assinaturas_status'),
    
    path('cobrancas/', admin_views.AdminCobrancasView.as_view(), name='cobrancas'),
    path('cobrancas/nova/', admin_views.admin_cobranca_create, name='cobrancas_nova'),
    path('cobrancas/<int:pk>/editar/', admin_views.admin_cobranca_edit, name='cobrancas_editar'),
    path('cobrancas/<int:pk>/excluir/', admin_views.admin_cobranca_delete, name='cobrancas_excluir'),
    path('cobrancas/<int:pk>/pagar/', admin_views.admin_cobranca_pagar, name='cobrancas_pagar'),
    path('cobrancas/<int:pk>/status/<str:status>/', admin_views.admin_cobranca_change_status, name='cobrancas_status'),
    
    path('relatorios/', admin_views.AdminRelatoriosView.as_view(), name='relatorios'),
    path('relatorios/financeiro/', admin_views.AdminRelatorioFinanceiroView.as_view(), name='relatorio_financeiro'),
    path('relatorios/financeiro/despesas/nova/', admin_views_expenses.admin_expense_create, name='expense_create'),
    path('relatorios/financeiro/despesas/<int:pk>/editar/', admin_views_expenses.admin_expense_edit, name='expense_edit'),
    path('relatorios/financeiro/despesas/<int:pk>/paga/', admin_views_expenses.admin_expense_mark_paid, name='expense_mark_paid'),
    path('relatorios/financeiro/despesas/<int:pk>/excluir/', admin_views_expenses.admin_expense_delete, name='expense_delete'),
    
    path('relatorios/parceiros/', admin_views.AdminPartnerListView.as_view(), name='parceiros'),
    path('relatorios/parceiros/novo/', admin_views.admin_partner_create, name='parceiros_novo'),
    path('relatorios/parceiros/<int:pk>/editar/', admin_views.admin_partner_edit, name='parceiros_editar'),
    path('relatorios/parceiros/<int:pk>/desativar/', admin_views.admin_partner_toggle_active, name='parceiros_desativar'),
    path('relatorios/parceiros/<int:pk>/excluir/', admin_views.admin_partner_delete, name='parceiros_excluir'),
    
    # Fale Conosco Administrativo
    path('relatorios/fale-conosco/', admin_views_support.AdminSupportListView.as_view(), name='support_list'),
    path('relatorios/fale-conosco/<int:pk>/', admin_views_support.AdminSupportDetailView.as_view(), name='support_detail'),
    path('relatorios/fale-conosco/<int:pk>/excluir/', admin_views_support.admin_support_delete, name='support_delete'),

    # Gestão do Site
    path('relatorios/site/', admin_views.SiteLogosView.as_view(), name='site_logos'),
    path('relatorios/site/planos/', admin_views.SitePlansPriceUpdateView.as_view(), name='site_plans_update'),
    path('relatorios/site/reordenar/', admin_views.SiteLogoReorderView.as_view(), name='site_logos_reorder'),
    path('relatorios/site/<int:pk>/editar/', admin_views.SiteLogoEditView.as_view(), name='site_logos_edit'),
    path('relatorios/site/<int:pk>/excluir/', admin_views.SiteLogoDeleteView.as_view(), name='site_logos_delete'),
    path('relatorios/site/<int:pk>/desativar/', admin_views.SiteLogoToggleActiveView.as_view(), name='site_logos_toggle_active'),

    path('web-push/', admin_views.AdminWebPushDashboardView.as_view(), name='admin_web_push_dashboard'),
    

    path('banco-de-dados/', admin_views_database.AdminDatabaseListView.as_view(), name='database_list'),
    path('banco-de-dados/<int:pk>/editar/', admin_views_database.admin_database_edit, name='database_edit'),
    path('banco-de-dados/<int:pk>/ocultar/', admin_views_database.admin_database_hide, name='database_hide'),
    path('banco-de-dados/<int:pk>/desocultar/', admin_views_database.admin_database_unhide, name='database_unhide'),
    path('banco-de-dados/<int:pk>/excluir/', admin_views_database.admin_database_delete, name='database_delete'),

    path('configuracoes/', admin_views.AdminConfiguracoesView.as_view(), name='configuracoes'),
]
