from django.urls import set_script_prefix
from django.utils.deprecation import MiddlewareMixin
from core.models import Band

class BandAdminMiddleware(MiddlewareMixin):
    """
    Middleware que permite acessar o Django Admin sob URLs dinâmicas como /painel/<slug_da_banda>/.
    Ele intercepta a requisição, define o SCRIPT_NAME para a URL base da banda,
    e delega o restante da URL para as rotas normais do AdminSite (via admin_urls.py).
    Dessa forma, o Django Admin gera internamente todas as URLs com o prefixo correto
    sem quebrar nenhum botão (Salvar, Excluir, Adicionar).
    """

    def process_request(self, request):
        path = request.path_info
        # Verifica se o formato é /<band_slug>/painel/...
        parts = path.split('/')
        if len(parts) >= 3 and parts[2] == 'painel' and parts[1] != 'painel':
            band_slug = parts[1]
            
            # Ignora nomes reservados
            if band_slug in ['admin', 'painel', 'static', 'media']:
                return None
            
            # Verifica se a banda existe
            if Band.objects.filter(slug=band_slug).exists():
                # O SCRIPT_NAME será /dannielvieira/painel
                script_name = f"/{band_slug}/painel"
                
                # Calcula o restante da URL (ex: /core/show/)
                new_path = '/' + '/'.join(parts[3:])
                
                request.META['SCRIPT_NAME'] = script_name
                request.path_info = new_path
                set_script_prefix(script_name + '/')
                request.urlconf = 'config.admin_urls'
        
        return None
