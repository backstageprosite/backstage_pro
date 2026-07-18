from django.urls import path
from . import admin_views, pwa_views

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
    
    path('usuarios/', admin_views.AdminUserListView.as_view(), name='usuarios'),
    path('usuarios/novo/', admin_views.admin_user_create, name='usuarios_novo'),
    path('usuarios/<int:pk>/editar/', admin_views.admin_user_edit, name='usuarios_editar'),
    path('usuarios/<int:pk>/desativar/', admin_views.admin_user_toggle_active, name='usuarios_desativar'),
    path('usuarios/<int:pk>/resetar-senha/', admin_views.admin_user_reset_password, name='usuarios_resetar_senha'),
    
    path('shows/', admin_views.AdminShowListView.as_view(), name='shows'),
    
    path('assinaturas/', admin_views.AdminAssinaturasView.as_view(), name='assinaturas'),
    path('assinaturas/nova/', admin_views.admin_assinatura_create, name='assinaturas_nova'),
    path('assinaturas/<int:pk>/editar/', admin_views.admin_assinatura_edit, name='assinaturas_editar'),
    path('assinaturas/<int:pk>/cancelar/', admin_views.admin_assinatura_cancel, name='assinaturas_cancelar'),
    
    path('cobrancas/', admin_views.AdminCobrancasView.as_view(), name='cobrancas'),
    path('cobrancas/nova/', admin_views.admin_cobranca_create, name='cobrancas_nova'),
    path('cobrancas/<int:pk>/editar/', admin_views.admin_cobranca_edit, name='cobrancas_editar'),
    path('cobrancas/<int:pk>/status/<str:status>/', admin_views.admin_cobranca_change_status, name='cobrancas_status'),
    
    path('relatorios/', admin_views.AdminRelatoriosView.as_view(), name='relatorios'),
    path('relatorios/financeiro/', admin_views.AdminRelatorioFinanceiroView.as_view(), name='relatorio_financeiro'),
    
    path('web-push/', admin_views.AdminWebPushDashboardView.as_view(), name='admin_web_push_dashboard'),
    
    path('configuracoes/', admin_views.AdminConfiguracoesView.as_view(), name='configuracoes'),
]
