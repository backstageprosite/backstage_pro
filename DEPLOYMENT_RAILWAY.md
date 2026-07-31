# Guia de Deploy e Segurança para a Railway

A arquitetura do `config/settings.py` adota um padrão de segurança **fail-closed**.
Se uma variável obrigatória estiver ausente ou insegura no ambiente de produção, o Django irá abortar a inicialização proativamente com a exceção `ImproperlyConfigured`.

## 1. Identificação Automática de Ambiente
Se a variável `RAILWAY_ENVIRONMENT_ID` estiver presente, o sistema considerará que está em produção. Você também pode simular a produção setando `DJANGO_ENV=production`. Nesses ambientes, o carregamento de arquivos locais `.env` é terminantemente bloqueado para impedir vazamento de configurações.

## 2. Variáveis de Ambiente Obrigatórias (Dashboard da Railway)

| Variável | Valor Esperado | Motivo / Restrição |
| :--- | :--- | :--- |
| `DATABASE_URL` | `postgres://user:pass@host...` | Obrigatório. Não fará fallback silencioso para SQLite. |
| `SECRET_KEY` | String aleatória (`>=50` caracteres) | Obrigatório. Aborta se estiver vazia, for curta, tiver prefixo inseguro do django, ou tiver pouca entropia. |
| `SECURE_SSL_REDIRECT` | `1` ou `True` | Obrigatório. Garante que todo tráfego seja HTTPS. |
| `DJANGO_ENV` | `production` | Informa que estamos no modo final de produção. |

## 3. Comportamento Automático de Hosts
Na Railway, o sistema recebe a variável `RAILWAY_PUBLIC_DOMAIN`.
Ela será automaticamente:
1. Inserida no topo da lista `ALLOWED_HOSTS`.
2. Convertida para `https://<dominio>` e inserida no topo de `CSRF_TRUSTED_ORIGINS`.

**Atenção:** Em produção, o uso do wildcard `*` no `ALLOWED_HOSTS` ou `CSRF_TRUSTED_ORIGINS` é **proibido** e resultará em crash da aplicação. Da mesma forma, origens que possuam paths extras, fragmentos ou scheme `http://` também farão o sistema abortar em ambiente seguro.
