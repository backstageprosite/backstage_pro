import os
import sys
import subprocess
import unittest

class SettingsSecurityTests(unittest.TestCase):
    """
    Testes isolados de segurança e parsing para o config/settings.py.
    """
    
    @classmethod
    def setUpClass(cls):
        cls.env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
        cls.env_bak_path = cls.env_path + '.bak'
        if os.path.exists(cls.env_path):
            os.rename(cls.env_path, cls.env_bak_path)

    @classmethod
    def tearDownClass(cls):
        if os.path.exists(cls.env_bak_path):
            os.rename(cls.env_bak_path, cls.env_path)

    def run_settings_check(self, env_vars):
        # 1. Whitelist mínima
        whitelist = ['PATH', 'SYSTEMROOT', 'SYSTEMDRIVE', 'USERPROFILE', 'COMSPEC', 'TEMP', 'TMP', 'WINDIR']
        env = {k: v for k, v in os.environ.items() if k.upper() in whitelist}
        
        # 2. Injeta o cenário
        env.update(env_vars)
        
        script = (
            "import os, sys, django; "
            "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings'); "
            "django.setup(); "
            "from django.conf import settings; "
            "print(f'DEBUG={settings.DEBUG}'); "
            "print(f'SECRET_KEY={settings.SECRET_KEY}'); "
            "print(f'ALLOWED_HOSTS={settings.ALLOWED_HOSTS}'); "
            "print(f'CSRF_TRUSTED_ORIGINS={settings.CSRF_TRUSTED_ORIGINS}'); "
            "print(f'DATABASES={\"sqlite3\" in settings.DATABASES[\"default\"][\"ENGINE\"]}'); "
            "print(f'SECURE_SSL_REDIRECT={settings.SECURE_SSL_REDIRECT}'); "
            "print(f'SESSION_COOKIE_SECURE={settings.SESSION_COOKIE_SECURE}'); "
            "print(f'CSRF_COOKIE_SECURE={settings.CSRF_COOKIE_SECURE}'); "
            "print(f'SECURE_HSTS_SECONDS={settings.SECURE_HSTS_SECONDS}'); "
            "print(f'SECURE_HSTS_INCLUDE_SUBDOMAINS={settings.SECURE_HSTS_INCLUDE_SUBDOMAINS}'); "
            "print(f'SECURE_HSTS_PRELOAD={settings.SECURE_HSTS_PRELOAD}'); "
        )
        
        # 6. Definir cwd explicitamente, 8. Timeout
        cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        try:
            return subprocess.run(
                [sys.executable, "-c", script], 
                env=env, 
                cwd=cwd,
                capture_output=True, 
                text=True,
                timeout=10
            )
        except subprocess.TimeoutExpired:
            self.fail("O subprocesso excedeu o tempo limite de execução (timeout).")

    # 1. Local development sem Railway inicia
    def test_local_dev_starts(self):
        res = self.run_settings_check({})
        self.assertEqual(res.returncode, 0, res.stderr)
        
    # 2. Local usa SQLite
    def test_local_uses_sqlite(self):
        res = self.run_settings_check({})
        self.assertIn("DATABASES=True", res.stdout)
        
    # 3. Local usa fallback de SECRET_KEY
    def test_local_fallback_secret_key(self):
        res = self.run_settings_check({"IGNORE_DOTENV": "1"}) # By-pass the local .env if it exists in the user's directory for tests simulating pure absence
        self.assertIn("SECRET_KEY=chave-local-insegura-para-desenvolvimento", res.stdout)

    # 4. Local DEBUG ausente resulta True
    def test_local_debug_missing_is_true(self):
        res = self.run_settings_check({"IGNORE_DOTENV": "1"})
        self.assertIn("DEBUG=True", res.stdout)

    # 5. Local DEBUG=False resulta False
    def test_local_debug_false_is_false(self):
        res = self.run_settings_check({"DEBUG": "false", "IGNORE_DOTENV": "1"})
        self.assertIn("DEBUG=False", res.stdout)

    # 6. Railway DEBUG ausente resulta False
    def test_railway_debug_missing_is_false(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("DEBUG=False", res.stdout)

    # 7. Railway DEBUG=True falha
    def test_railway_debug_true_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "DEBUG": "True",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("DEBUG=True não é permitido em ambiente seguro.", res.stderr)

    # 8. DJANGO_ENV=production sem Railway usa segurança
    def test_production_env_uses_security(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("DEBUG=False", res.stdout)
        self.assertIn("DATABASES=False", res.stdout)

    # 9. DJANGO_ENV inválido falha
    def test_invalid_django_env_fails(self):
        res = self.run_settings_check({"DJANGO_ENV": "invalid"})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("DJANGO_ENV inválido", res.stderr)

    # 10. Railway sem SECRET_KEY falha
    def test_railway_without_secret_key_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("A secure SECRET_KEY must be provided in production.", res.stderr)

    # 11. Railway com SECRET_KEY vazia falha
    def test_railway_with_empty_secret_key_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("A secure SECRET_KEY must be provided in production.", res.stderr)

    # 12. Railway com chave curta falha
    def test_railway_short_secret_key_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abc",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("SECRET_KEY does not meet production security requirements.", res.stderr)

    # 13. Railway com django-insecure falha
    def test_railway_django_insecure_key_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "django-insecure-" + "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("SECRET_KEY does not meet production security requirements.", res.stderr)

    # 14. Railway com baixa diversidade falha
    def test_railway_low_diversity_key_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "a" * 60,
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("SECRET_KEY does not meet production security requirements.", res.stderr)

    # 15. Railway sem DATABASE_URL falha
    def test_railway_without_database_url_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("DATABASE_URL is required in production.", res.stderr)

    # 16. Railway com URL não PostgreSQL falha
    def test_railway_non_postgres_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "mysql://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Only PostgreSQL is supported in production.", res.stderr)

    # 17. Railway sem ALLOWED_HOSTS e sem domínio automático falha
    def test_railway_no_hosts_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("ALLOWED_HOSTS is required in production.", res.stderr)

    # 18. Railway com ALLOWED_HOSTS=* falha
    def test_railway_wildcard_hosts_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "*",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Wildcard '*' in ALLOWED_HOSTS is forbidden in production.", res.stderr)

    # 19. Host com protocolo falha
    def test_host_with_protocol_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "https://test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Invalid characters in ALLOWED_HOSTS entry: https://test.com", res.stderr)

    # 20. Railway domain é adicionado ao ALLOWED_HOSTS (sem sujar)
    def test_railway_domain_added_to_hosts(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "CSRF_TRUSTED_ORIGINS": "https://auto.up.railway.app",
            "RAILWAY_PUBLIC_DOMAIN": "auto.up.railway.app"
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("['auto.up.railway.app']", res.stdout)

    # 21. Railway CSRF origin é adicionada
    def test_railway_domain_added_to_csrf(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "ALLOWED_HOSTS": "test.com",
            "RAILWAY_PUBLIC_DOMAIN": "auto.up.railway.app"
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("['https://auto.up.railway.app']", res.stdout)

    # 22. Origem HTTP em produção falha
    def test_csrf_http_fails_in_prod(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "CSRF_TRUSTED_ORIGINS": "http://test.com"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("CSRF_TRUSTED_ORIGINS must use https in production", res.stderr)

    # 23. Origem com caminho falha
    def test_csrf_with_path_fails_in_prod(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "CSRF_TRUSTED_ORIGINS": "https://test.com/path"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("CSRF_TRUSTED_ORIGINS format is invalid", res.stderr)

    # 24. SECURE_SSL_REDIRECT fica True
    def test_ssl_redirect_true(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("SECURE_SSL_REDIRECT=True", res.stdout)

    # 25. SECURE_SSL_REDIRECT=False em produção falha
    def test_ssl_redirect_false_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "SECURE_SSL_REDIRECT": "0"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("SECURE_SSL_REDIRECT deve estar ativo em produção.", res.stderr)

    # 26. SESSION_COOKIE_SECURE fica True
    def test_session_cookie_secure_true(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("SESSION_COOKIE_SECURE=True", res.stdout)

    # 27. CSRF_COOKIE_SECURE fica True
    def test_csrf_cookie_secure_true(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("CSRF_COOKIE_SECURE=True", res.stdout)

    # 28. HSTS padrão fica 3600
    def test_hsts_default_3600(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("SECURE_HSTS_SECONDS=3600", res.stdout)

    # 29. HSTS zero em produção falha
    def test_hsts_zero_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "SECURE_HSTS_SECONDS": "0"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("SECURE_HSTS_SECONDS deve ser maior que zero em produção.", res.stderr)

    # 30. HSTS negativo falha
    def test_hsts_negative_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "SECURE_HSTS_SECONDS": "-10"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Invalid positive integer", res.stderr)

    # 31. HSTS inválido falha
    def test_hsts_invalid_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "SECURE_HSTS_SECONDS": "abc"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Invalid positive integer", res.stderr)

    # 32. IncludeSubDomains padrão False
    def test_include_subdomains_default_false(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("SECURE_HSTS_INCLUDE_SUBDOMAINS=False", res.stdout)

    # 33. Preload padrão False
    def test_preload_default_false(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
        })
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("SECURE_HSTS_PRELOAD=False", res.stdout)

    # 34. Booleano inválido falha
    def test_invalid_boolean_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "SECURE_SSL_REDIRECT": "yesorno"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Invalid boolean", res.stderr)

    # 35. Configuração mínima válida importa settings
    def test_minimal_config_imports(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "DATABASE_URL": "postgres://user:pass@host/db",
            "CSRF_TRUSTED_ORIGINS": "https://test.com"
        })
        self.assertEqual(res.returncode, 0, res.stderr)

    # 36. Mensagem de SECRET_KEY não expõe valor
    def test_secret_key_message_does_not_leak(self):
        weak_key = "abcde-this-is-a-weak-key-that-will-be-leaked"
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": weak_key,
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn(weak_key, res.stderr)

    # 37. Mensagem de DATABASE_URL não expõe valor
    def test_db_url_message_does_not_leak(self):
        bad_db = "mysql://supersecret:superpass@localhost:3306/db"
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": bad_db
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertNotIn(bad_db, res.stderr)

    # 38. Desenvolvimento local continua aceitando testserver
    def test_local_dev_accepts_testserver(self):
        res = self.run_settings_check({"IGNORE_DOTENV": "1"})
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("testserver", res.stdout)
        
    # 39. DJANGO_ENV=production sem Railway não carrega .env
    def test_production_no_railway_doesnt_load_dotenv(self):
        # Aqui injetamos propriedades malformadas que passariam se o .env fosse carregado e sobrescrevesse, ou verificamos se ele reclama de SECRET_KEY
        # O proprio isolamento ja faz isso, mas validamos:
        res = self.run_settings_check({
            "DJANGO_ENV": "production"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("A secure SECRET_KEY must be provided in production.", res.stderr)
        
    # 40. DJANGO_ENV=staging sem Railway não carrega .env
    def test_staging_no_railway_doesnt_load_dotenv(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "staging"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("A secure SECRET_KEY must be provided in production.", res.stderr)
        
    # 41. Host com protocolo falha
    # Ja verificado no 19, re-implementando para ficar claro
    def test_host_protocol_fails_explicit(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "http://test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Invalid characters in ALLOWED_HOSTS", res.stderr)
        
    # 42. Host com caminho falha
    def test_host_path_fails(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com/api",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Invalid characters in ALLOWED_HOSTS", res.stderr)
        
    # 43. Host com query falha
    def test_host_query_fails(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com?q=1",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Invalid characters in ALLOWED_HOSTS", res.stderr)
        
    # 44. Host com fragmento falha
    def test_host_fragment_fails(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com#test",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Invalid characters in ALLOWED_HOSTS", res.stderr)
        
    # 45. RAILWAY_PUBLIC_DOMAIN malformado falha
    def test_railway_domain_malformed_fails(self):
        res = self.run_settings_check({
            "RAILWAY_ENVIRONMENT_ID": "test",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "RAILWAY_PUBLIC_DOMAIN": "http://test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Invalid characters in ALLOWED_HOSTS", res.stderr)
        
    # 46. CSRF com wildcard falha
    def test_csrf_wildcard_fails(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://*.test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Wildcard '*' in CSRF_TRUSTED_ORIGINS is forbidden", res.stderr)
        
    # 47. CSRF com credenciais falha
    def test_csrf_credentials_fails(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://user:pass@test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("CSRF_TRUSTED_ORIGINS format is invalid", res.stderr)
        
    # 48. CSRF com query falha
    def test_csrf_query_fails(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com/?q=1",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("CSRF_TRUSTED_ORIGINS format is invalid", res.stderr)
        
    # 49. CSRF com fragmento falha
    def test_csrf_fragment_fails(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com/#foo",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("CSRF_TRUSTED_ORIGINS format is invalid", res.stderr)
        
    # 50. Subprocesso não herda DATABASE_URL externa
    def test_no_db_url_leak(self):
        # Ja testado pelo clean do dict env, se der ruim ele cai no 15.
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("DATABASE_URL is required in production.", res.stderr)
        
    # 51. Subprocesso não herda SECRET_KEY externa
    def test_no_secret_key_leak(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("A secure SECRET_KEY must be provided in production.", res.stderr)
        
    # 52. Subprocesso não herda DEBUG externo
    def test_no_debug_leak(self):
        res = self.run_settings_check({
            "DJANGO_ENV": "production",
            "SECRET_KEY": "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
            "ALLOWED_HOSTS": "test.com",
            "CSRF_TRUSTED_ORIGINS": "https://test.com",
            "DATABASE_URL": "postgres://user:pass@host/db"
        })
        self.assertEqual(res.returncode, 0)
        self.assertIn("DEBUG=False", res.stdout)

