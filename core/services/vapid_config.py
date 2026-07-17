import base64
import binascii
import hmac
import logging
import urllib.parse
from dataclasses import dataclass
from django.conf import settings
from django.core.validators import EmailValidator
from django.core.exceptions import ValidationError

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)

class VapidConfigurationError(Exception):
    pass

@dataclass(frozen=True)
class VapidConfiguration:
    public_key: str
    private_key: str
    subject: str

    def __repr__(self):
        return f"VapidConfiguration(public_key='***', private_key='***', subject='***')"

    def __str__(self):
        return self.__repr__()

def _contains_controls_or_spaces(val: str) -> bool:
    for c in val:
        if c.isspace() or ord(c) < 32 or ord(c) == 127:
            return True
    return False

def validate_vapid_public_key(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise VapidConfigurationError("vapid_public_key_missing")
    if _contains_controls_or_spaces(value):
        raise VapidConfigurationError("vapid_public_key_invalid_chars")
    if '=' in value:
        raise VapidConfigurationError("vapid_public_key_invalid_chars")
    
    # Internal padding
    pad = len(value) % 4
    padded_val = value + '=' * (4 - pad) if pad else value
    
    try:
        decoded = base64.b64decode(
            padded_val,
            altchars=b"-_",
            validate=True
        )
    except (binascii.Error, ValueError):
        raise VapidConfigurationError("vapid_public_key_not_base64")
        
    if len(decoded) != 65:
        raise VapidConfigurationError("vapid_public_key_invalid_length")
    if decoded[0] != 0x04:
        raise VapidConfigurationError("vapid_public_key_invalid_prefix")
        
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decoded)
    except Exception:
        raise VapidConfigurationError("vapid_public_key_invalid_point")
        
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if not hmac.compare_digest(canonical, value):
        raise VapidConfigurationError("vapid_public_key_not_canonical")
        
    return value

def validate_vapid_private_key(value: str) -> ec.EllipticCurvePrivateKey:
    if not isinstance(value, str) or not value:
        raise VapidConfigurationError("vapid_private_key_missing")
    if _contains_controls_or_spaces(value):
        raise VapidConfigurationError("vapid_private_key_invalid_chars")
        
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise VapidConfigurationError("vapid_private_key_not_base64")
        
    try:
        private_key = serialization.load_der_private_key(
            decoded,
            password=None,
            backend=default_backend()
        )
    except Exception:
        raise VapidConfigurationError("vapid_private_key_invalid_der")
        
    if not isinstance(private_key, ec.EllipticCurvePrivateKey):
        raise VapidConfigurationError("vapid_private_key_not_ec")
        
    if not isinstance(private_key.curve, ec.SECP256R1):
        raise VapidConfigurationError("vapid_private_key_invalid_curve")
        
    return private_key

def validate_vapid_subject(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise VapidConfigurationError("vapid_subject_missing")
        
    if len(value) > 500:
        raise VapidConfigurationError("vapid_subject_too_long")
        
    if _contains_controls_or_spaces(value):
        raise VapidConfigurationError("vapid_subject_invalid_chars")
        
    if '\\' in value:
        raise VapidConfigurationError("vapid_subject_invalid_chars")
        
    parsed = urllib.parse.urlsplit(value)
    
    if parsed.scheme == 'https':
        if not parsed.hostname:
            raise VapidConfigurationError("vapid_subject_no_hostname")
        if parsed.username or parsed.password:
            raise VapidConfigurationError("vapid_subject_credentials_not_allowed")
        if parsed.fragment:
            raise VapidConfigurationError("vapid_subject_fragment_not_allowed")
                
    elif parsed.scheme == 'mailto':
        if not parsed.path:
            raise VapidConfigurationError("vapid_subject_no_email")
        if parsed.query:
            raise VapidConfigurationError("vapid_subject_query_not_allowed")
        if parsed.fragment:
            raise VapidConfigurationError("vapid_subject_fragment_not_allowed")
        if ',' in parsed.path or ';' in parsed.path:
            raise VapidConfigurationError("vapid_subject_multiple_emails")
            
        validator = EmailValidator()
        try:
            validator(parsed.path)
        except ValidationError:
            raise VapidConfigurationError("vapid_subject_invalid_email")
    else:
        raise VapidConfigurationError("vapid_subject_invalid_scheme")
        
    return value

_has_logged_missing = False

def load_vapid_configuration() -> VapidConfiguration:
    global _has_logged_missing
    
    pub_key_raw = getattr(settings, 'VAPID_PUBLIC_KEY', '')
    priv_key_raw = getattr(settings, 'VAPID_PRIVATE_KEY', '')
    sub_raw = getattr(settings, 'VAPID_SUBJECT', '')
    
    if not pub_key_raw or not priv_key_raw or not sub_raw:
        if not _has_logged_missing:
            logger.warning("VAPID configuration is missing. Push notifications will not work.")
            _has_logged_missing = True
        raise VapidConfigurationError("vapid_configuration_missing")
        
    try:
        validate_vapid_public_key(pub_key_raw)
        priv_key_obj = validate_vapid_private_key(priv_key_raw)
        validate_vapid_subject(sub_raw)
        
        # Verify pair
        pub_derived = priv_key_obj.public_key()
        pub_bytes = pub_derived.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )
        
        # Base64 URL-safe, NO PADDING
        pub_b64 = base64.urlsafe_b64encode(pub_bytes).decode('ascii').rstrip('=')
        
        if not hmac.compare_digest(pub_b64, pub_key_raw.rstrip('=')):
            raise VapidConfigurationError("vapid_key_pair_mismatch")
            
        return VapidConfiguration(
            public_key=pub_key_raw,
            private_key=priv_key_raw,
            subject=sub_raw
        )
    except VapidConfigurationError as e:
        logger.error(f"VAPID configuration error: {str(e)}")
        raise

def is_vapid_configuration_ready() -> bool:
    try:
        load_vapid_configuration()
        return True
    except VapidConfigurationError:
        return False
