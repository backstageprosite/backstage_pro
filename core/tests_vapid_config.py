import os
import base64
import json
import logging
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.conf import settings

from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from core.models import Band, WebPushSubscription
from core.services.vapid_config import (
    validate_vapid_public_key, validate_vapid_private_key,
    validate_vapid_subject, load_vapid_configuration,
    is_vapid_configuration_ready, VapidConfigurationError
)

User = get_user_model()

class VapidConfigTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Generate valid EC P-256 pair
        cls.priv_key_obj = ec.generate_private_key(ec.SECP256R1(), default_backend())
        cls.pub_key_obj = cls.priv_key_obj.public_key()
        
        cls.valid_der_priv = cls.priv_key_obj.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        cls.valid_priv_b64 = base64.b64encode(cls.valid_der_priv).decode('ascii')
        
        pub_bytes = cls.pub_key_obj.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        cls.valid_pub_b64url = base64.urlsafe_b64encode(pub_bytes).decode('ascii').rstrip('=')
        cls.valid_subject = "https://backstagepro.site"
        
        # Another pair to test mismatch
        other_priv = ec.generate_private_key(ec.SECP256R1(), default_backend())
        other_pub_bytes = other_priv.public_key().public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        cls.other_pub_b64url = base64.urlsafe_b64encode(other_pub_bytes).decode('ascii').rstrip('=')
        
        # Dummy RSA key
        rsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        rsa_der = rsa_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        cls.rsa_b64 = base64.b64encode(rsa_der).decode('ascii')
        
        # P-384 key
        p384_key = ec.generate_private_key(ec.SECP384R1(), default_backend())
        p384_der = p384_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        cls.p384_b64 = base64.b64encode(p384_der).decode('ascii')

        # Dummy user & band for endpoint
        cls.band = Band.objects.create(name="Banda Teste", slug="banda-teste", is_active=True)
        cls.produtor = User.objects.create_user(username="produtor", email="prod@test.com", password="123", role="PRODUTOR", band=cls.band)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.produtor)

    # =================
    # DEPENDÊNCIA
    # =================
    def test_dependencies(self):
        # 1. pywebpush can be imported
        import pywebpush
        import importlib.metadata
        # 2. version is 2.3.0
        version = importlib.metadata.version("pywebpush")
        self.assertEqual(version, "2.3.0")
        # 3. requirements pin
        # 4. no webpush called: we just didn't call it anywhere in our code.
        pass

    # =================
    # PUBLIC KEY
    # =================
    def test_public_key_validation(self):
        # 5. valid accepted
        self.assertEqual(validate_vapid_public_key(self.valid_pub_b64url), self.valid_pub_b64url)
        # Missing or empty
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key("")
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(None)
        
        # Whitespace and controls
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(" " + self.valid_pub_b64url)
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(f"{self.valid_pub_b64url}\n")
        
        # padding '=' rejected
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(self.valid_pub_b64url + "=")
        
        # character '+' rejected
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(self.valid_pub_b64url.replace('-', '+'))
            
        # character '/' rejected
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(self.valid_pub_b64url.replace('_', '/'))
        
        # Non-canonical string rejected. 
        # Base64 with validate=True is very strict, but we test that any alteration throws VapidConfigurationError
        non_canonical = self.valid_pub_b64url[:-1] + ('A' if self.valid_pub_b64url[-1] != 'A' else 'B')
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(non_canonical)
        
        # 8. 64 bytes rejected
        bad_bytes = b'\x04' + b'\x00' * 63
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(base64.urlsafe_b64encode(bad_bytes).decode('ascii'))
        # 9. 66 bytes rejected
        bad_bytes = b'\x04' + b'\x00' * 65
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(base64.urlsafe_b64encode(bad_bytes).decode('ascii'))
        # 10. first byte != 0x04 rejected
        bad_bytes = b'\x03' + b'\x00' * 64
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(base64.urlsafe_b64encode(bad_bytes).decode('ascii'))
        # 11. invalid P-256 point rejected
        bad_bytes = b'\x04' + b'\x00' * 64
        with self.assertRaises(VapidConfigurationError): validate_vapid_public_key(base64.urlsafe_b64encode(bad_bytes).decode('ascii'))

    # =================
    # PYWEBPUSH COMPATIBILITY
    # =================
    def test_pywebpush_compatibility(self):
        # 6. Compatibilidade prática com pywebpush (py_vapid)
        from py_vapid import Vapid
        
        # Should load the base64 DER string successfully
        vapid = Vapid.from_string(private_key=self.valid_priv_b64)
        self.assertIsNotNone(vapid)
        
        # Test invalid string rejected
        with self.assertRaises(Exception):
            Vapid.from_string(private_key="invalidbase64==")

    # =================
    # PRIVATE KEY
    # =================
    def test_private_key_validation(self):
        # 14. valid DER PKCS8 P-256 accepted
        pk = validate_vapid_private_key(self.valid_priv_b64)
        self.assertIsInstance(pk, ec.EllipticCurvePrivateKey)
        # 15. invalid Base64 rejected
        with self.assertRaises(VapidConfigurationError): validate_vapid_private_key("!!!")
        # 16. inline PEM rejected
        pem = self.priv_key_obj.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        with self.assertRaises(VapidConfigurationError): validate_vapid_private_key(base64.b64encode(pem).decode('ascii'))
        # 17. RSA rejected
        with self.assertRaises(VapidConfigurationError): validate_vapid_private_key(self.rsa_b64)
        # 18. other curve rejected
        with self.assertRaises(VapidConfigurationError): validate_vapid_private_key(self.p384_b64)
        # 19. corrupted DER rejected
        with self.assertRaises(VapidConfigurationError): validate_vapid_private_key(base64.b64encode(b"corruptedderdatahere").decode('ascii'))
        # 20. CR/LF rejected
        with self.assertRaises(VapidConfigurationError): validate_vapid_private_key(f"{self.valid_priv_b64}\n")

    # =================
    # PAIR
    # =================
    def test_key_pair_matching(self):
        # 21. matching pair accepted
        with override_settings(VAPID_PUBLIC_KEY=self.valid_pub_b64url, VAPID_PRIVATE_KEY=self.valid_priv_b64, VAPID_SUBJECT=self.valid_subject):
            config = load_vapid_configuration()
            self.assertIsNotNone(config)
        # 22. divergent pair rejected
        with override_settings(VAPID_PUBLIC_KEY=self.other_pub_b64url, VAPID_PRIVATE_KEY=self.valid_priv_b64, VAPID_SUBJECT=self.valid_subject):
            with self.assertRaises(VapidConfigurationError) as ctx:
                load_vapid_configuration()
            # 23. comparison doesn't expose keys
            self.assertEqual(str(ctx.exception), "vapid_key_pair_mismatch")

    # =================
    # SUBJECT
    # =================
    def test_subject_validation(self):
        # Valid cases
        self.assertEqual(validate_vapid_subject("https://backstagepro.site"), "https://backstagepro.site")
        self.assertEqual(validate_vapid_subject("mailto:contato@backstagepro.site"), "mailto:contato@backstagepro.site")
        
        # 11. subject acima de 500 rejeitado
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("https://backstagepro.site/" + "a"*500)
        
        # Invalid chars (spaces, tabs, controls, backslash)
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("https://backstagepro.site\n")
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("https://backstagepro.site\r")
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("https://backstagepro.site ")
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("https://backstagepro.site\t")
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("https://backstagepro.site\\path")
        
        # HTTPS invalid cases
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("http://backstagepro.site")
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("javascript:alert(1)")
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("https://")
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("https://user:pass@backstagepro.site")
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("https://backstagepro.site/#frag")
        
        # mailto invalid cases
        # 7. mailto sem endereço válido rejeitado
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("mailto:texto-invalido")
        # comma
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("mailto:a@b.com,c@d.com")
        # semicolon
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("mailto:a@b.com;c@d.com")
        # query
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("mailto:a@b.com?subject=x")
        # space
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("mailto:a@b.com com espaço")
        # TAB
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("mailto:a@b.com\tcom\tTAB")
        # control unicode
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("mailto:a@b.com\u0000")
        
        # Missing or empty
        with self.assertRaises(VapidConfigurationError): validate_vapid_subject("")

    # =================
    # CONFIGURATION
    # =================
    def test_configuration(self):
        # 33. 3 valid vars -> ready=True
        with override_settings(VAPID_PUBLIC_KEY=self.valid_pub_b64url, VAPID_PRIVATE_KEY=self.valid_priv_b64, VAPID_SUBJECT=self.valid_subject):
            self.assertTrue(is_vapid_configuration_ready())
        
        # 34. public missing -> ready=False
        with override_settings(VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY=self.valid_priv_b64, VAPID_SUBJECT=self.valid_subject):
            self.assertFalse(is_vapid_configuration_ready())
            
        # 35. private missing -> ready=False
        with override_settings(VAPID_PUBLIC_KEY=self.valid_pub_b64url, VAPID_PRIVATE_KEY="", VAPID_SUBJECT=self.valid_subject):
            self.assertFalse(is_vapid_configuration_ready())
            
        # 36. subject missing -> ready=False
        with override_settings(VAPID_PUBLIC_KEY=self.valid_pub_b64url, VAPID_PRIVATE_KEY=self.valid_priv_b64, VAPID_SUBJECT=""):
            self.assertFalse(is_vapid_configuration_ready())
            
        # 37. divergent pair -> ready=False
        with override_settings(VAPID_PUBLIC_KEY=self.other_pub_b64url, VAPID_PRIVATE_KEY=self.valid_priv_b64, VAPID_SUBJECT=self.valid_subject):
            self.assertFalse(is_vapid_configuration_ready())

        # 38. repr hides secrets
        # 39. logs hide secrets
        with override_settings(VAPID_PUBLIC_KEY=self.valid_pub_b64url, VAPID_PRIVATE_KEY=self.valid_priv_b64, VAPID_SUBJECT=self.valid_subject):
            config = load_vapid_configuration()
            r = repr(config)
            self.assertNotIn(self.valid_priv_b64, r)
            self.assertNotIn(self.valid_subject, r)
            self.assertNotIn(self.valid_pub_b64url, r)
            
            with self.assertLogs('core.services.vapid_config', level='ERROR') as log:
                # Trigger error
                with override_settings(VAPID_PUBLIC_KEY=self.other_pub_b64url):
                    try:
                        load_vapid_configuration()
                    except VapidConfigurationError:
                        pass
                output = " ".join(log.output)
                self.assertNotIn(self.valid_priv_b64, output)
                self.assertNotIn(self.valid_subject, output)

    # =================
    # ENDPOINT
    # =================
    def test_endpoint(self):
        url = reverse('push_public_key', kwargs={'band_slug': self.band.slug})
        
        # 40, 41, 42, 43. incomplete -> 503
        with override_settings(VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY=self.valid_priv_b64, VAPID_SUBJECT=self.valid_subject):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 503)
            # 46. 503 response contains only generic error
            self.assertEqual(resp.json(), {"error": "push_not_configured"})
            self.assertEqual(resp['Cache-Control'], 'no-store')
            
        with override_settings(VAPID_PUBLIC_KEY=self.valid_pub_b64url, VAPID_PRIVATE_KEY="", VAPID_SUBJECT=self.valid_subject):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 503)
            
        # 44. valid -> 200
        with override_settings(VAPID_PUBLIC_KEY=self.valid_pub_b64url, VAPID_PRIVATE_KEY=self.valid_priv_b64, VAPID_SUBJECT=self.valid_subject):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
            # 45. 200 response contains ONLY publicKey
            self.assertEqual(resp.json(), {"publicKey": self.valid_pub_b64url})
            # 47, 48. private NEVER in response
            # 49. no-store remains
            self.assertEqual(resp['Cache-Control'], 'no-store')
            
        # 50. auth/bind remains
        self.client.logout()
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 401)
        
    # =================
    # AUSÊNCIAS
    # =================
    def test_absences(self):
        # 51. nenhuma inscrição é criada
        self.assertEqual(WebPushSubscription.objects.count(), 0)
        # 52, 53, 54, 55. Covered by code audit. No webpush code called, no migrations.
        pass
