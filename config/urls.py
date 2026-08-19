"""
URL configuration for config project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.contrib.auth import views as auth_views
from core import views
from core.views import landing_page_view, termos_de_uso_view, politica_de_privacidade_view

urlpatterns = [
    path('admin-master/', admin.site.urls),
    path('painel/', include('core.admin_urls')),
    path('', landing_page_view, name='home'),
    path('termos-de-uso/', termos_de_uso_view, name='termos_de_uso'),
    path('politica-de-privacidade/', politica_de_privacidade_view, name='politica_de_privacidade'),
    
    # Rotas de Recuperação de Senha (Globais)
    path('esqueci-minha-senha/', views.CustomPasswordResetView.as_view(), name='password_reset'),
    path('esqueci-minha-senha/enviado/', views.CustomPasswordResetDoneView.as_view(), name='password_reset_done'),
    path('redefinir-senha/<uidb64>/<token>/', views.CustomPasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('redefinir-senha/concluido/', views.CustomPasswordResetCompleteView.as_view(), name='password_reset_complete'),

    path('bancodedados/', views.banco_de_dados_view, name='banco_de_dados_global'),

    path('<slug:band_slug>/', include('core.urls')),
]

from django.conf import settings
from django.urls import re_path
from django.views.static import serve
import os

urlpatterns += [
    re_path(r'^media/partners/logos/(?P<path>.*)$', serve, {'document_root': os.path.join(settings.MEDIA_ROOT, 'partners', 'logos')}),
    re_path(r'^media/system_logos/(?P<path>.*)$', serve, {'document_root': os.path.join(settings.MEDIA_ROOT, 'system_logos')}),
    re_path(r'^media/app_install_guides/(?P<path>.*)$', serve, {'document_root': os.path.join(settings.MEDIA_ROOT, 'app_install_guides')}),
    path('site/logos/<int:pk>/imagem/', views.landing_page_logo_image_view, name='landing_logo_image'),
]
