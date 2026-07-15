# Guia de Deploy - Backstage Pro (Railway + GitHub)

Este guia prático ensina como publicar o Backstage Pro em produção através da nuvem do Railway, armazenando o código no GitHub, sem precisar lidar com painéis e comandos complexos de infraestrutura.

## 1. Preparação Local (Primeiro Commit no GitHub)
1. Crie uma conta no [GitHub](https://github.com/) (caso não tenha).
2. No canto superior direito, clique no símbolo **+** e selecione **New repository**.
3. Escolha um nome (ex: `backstage_pro`), marque como **Private** (Privado) e clique em **Create repository**.
4. Na sua máquina, através de uma ferramenta de interface gráfica do Git (como *GitHub Desktop* ou via VS Code), ou via terminal (`git init`), conecte a pasta do seu projeto.
5. **Atenção:** Arquivos como `db.sqlite3` e a pasta `media/` já estão no `.gitignore` por segurança e não devem ser enviados.
6. Faça seu primeiro commit (ex: "Initial commit with PWA setup") e publique a branch principal (geralmente `main` ou `master`).

---

## 2. Configurando o Railway
1. Crie uma conta ou faça login no [Railway.app](https://railway.app/).
2. Na tela inicial, clique em **New Project** -> **Deploy from GitHub repo**.
3. Autorize a conexão com seu GitHub e selecione o repositório `backstage_pro` que você criou.
4. O Railway iniciará automaticamente o primeiro deploy. Pode ser que ele falhe num primeiro momento, pois faltam variáveis de ambiente e o banco de dados.

### 2.1 Adicionando o PostgreSQL
1. Dentro do projeto do Railway, clique no botão superior direito **+ New** (ou Add Plugin).
2. Selecione **Database** -> **Add PostgreSQL**.
3. O Railway instanciará um banco de dados poderoso e privado.

### 2.2 Vinculando o Banco de Dados ao seu App
1. Clique no card da aplicação Django (onde fica o código).
2. Vá para a aba **Variables**.
3. Adicione uma variável chamada `DATABASE_URL` e, como valor, clique no campo de texto para o Railway sugerir a URL (ela aparece como `${{Postgres.DATABASE_URL}}`).

### 2.3 Variáveis Obrigatórias
Ainda na aba **Variables** do seu app, cadastre as seguintes chaves (sem aspas):
- `SECRET_KEY` = (gere uma senha longa, segura e aleatória)
- `DEBUG` = `False`
- `ALLOWED_HOSTS` = `backstagepro.site,www.backstagepro.site,localhost`
- `CSRF_TRUSTED_ORIGINS` = `https://backstagepro.site,https://www.backstagepro.site`
- `LOG_LEVEL` = `INFO`

---

## 3. Configurando Mídias Persistentes (CRÍTICO)
No Railway, o espaço de disco principal do app se apaga a cada atualização de versão ("disco efêmero"). Para não perder as logos e uploads, é obrigatório criar um **Volume**.

1. Selecione o card do App Django.
2. Acesse a aba **Volumes**.
3. Clique em **Create Volume** (Dê o nome de `media_volume` ou similar).
4. No campo **Mount Path** (Caminho de Montagem), escreva: `/app/media`
5. Volte na aba **Variables** e crie uma última variável:
   - `MEDIA_ROOT` = `/app/media`
6. Agora todos os uploads viverão em um disco inabalável.

---

## 4. Comandos de Inicialização (Start, Build e Pre-deploy)
O Railway permite configurar três fases distintas (aba **Settings**):

- **Build Command:** 
  `python manage.py collectstatic --noinput`
  *(O Railway costuma fazer isso nativamente se as variáveis estiverem corretas, mas é recomendado forçar a coleta explícita).*
- **Start Command (Comando de Inicialização):** 
  `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`
- **Pre-deploy (Migrations):** 
  Para segurança na homologação, coloque o comando:
  `python manage.py migrate`
  Isso rodará as migrações no banco Postgres antes do container entrar no ar.

---

## 5. Vinculando o Domínio Definitivo (Hostinger)
1. Antes do domínio oficial, o Railway te dará um domínio provisório (ex: `xxx.up.railway.app`). Faça a homologação nele primeiro!
2. No Railway, acesse o painel do seu app Django e clique na aba **Settings**.
3. Desça até a área de **Networking / Public Networking**.
4. Clique em **Custom Domain** e digite `backstagepro.site`.
5. O Railway informará registros DNS que precisam ser apontados (geralmente um CNAME).
6. Vá até o painel da Hostinger, na gestão do seu domínio `backstagepro.site`, abra a zona DNS.
7. Adicione o CNAME conforme orientado.

---

## 6. Procedimento de Rollback
Se você lançar uma versão defeituosa:
1. Volte ao Railway (aba **Deployments**).
2. Localize o deploy anterior que estava operante.
3. Clique nos três pontinhos e escolha **Redeploy**. Não execute reset destrutivo nem apague o banco!

---

## 7. Aviso sobre Arquivos Privados
O Volume preserva os arquivos físicos, mas atualmente o Django serve qualquer arquivo da pasta `/media/` de forma pública para quem tem o link direto. Para uma **operação comercial**, documentos sensíveis (Contratos, Comprovantes) precisarão de views autenticadas. Por enquanto, utilize dados fictícios na homologação.
