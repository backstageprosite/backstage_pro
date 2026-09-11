import io
import os
import logging
import warnings
from PIL import Image, UnidentifiedImageError, ImageOps
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

MAX_PROFILE_IMAGE_BYTES = 5 * 1024 * 1024  # 5MB

def process_profile_picture(uploaded_file, max_size=(400, 400), quality=85):
    """
    Processa a foto de perfil:
    - Valida tamanho em bytes (máximo 5MB).
    - Valida integridade e formato de imagem com Pillow (proteção contra decompression bombs).
    - Aplica orientação EXIF correta.
    - Redimensiona proporcionalmente mantendo proporção dentro de max_size.
    - Converte para JPEG otimizado (ou PNG se canal alfa).
    - Retorna um novo InMemoryUploadedFile compacto para salvar no ImageField.
    """
    if not uploaded_file:
        return None

    if uploaded_file.size > MAX_PROFILE_IMAGE_BYTES:
        raise ValidationError("O tamanho máximo permitido para a foto de perfil é 5MB.")

    try:
        uploaded_file.seek(0)
        img_data = uploaded_file.read()
        uploaded_file.seek(0)

        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(img_data))
            img.verify()

        # Reabrir após verify()
        img = Image.open(io.BytesIO(img_data))

        # Corrige rotação conforme EXIF
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        has_alpha = (img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info))
        
        # Redimensiona mantendo proporção
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        output_io = io.BytesIO()
        output_format = 'PNG' if has_alpha else 'JPEG'
        content_type = 'image/png' if has_alpha else 'image/jpeg'
        ext = '.png' if has_alpha else '.jpg'

        if output_format == 'JPEG':
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(output_io, format='JPEG', quality=quality, optimize=True)
        else:
            img.save(output_io, format='PNG', optimize=True)

        output_io.seek(0)
        processed_size = output_io.getbuffer().nbytes

        base_name = os.path.splitext(uploaded_file.name)[0]
        new_filename = f"{base_name}{ext}"

        new_file = InMemoryUploadedFile(
            file=output_io,
            field_name=uploaded_file.field_name if hasattr(uploaded_file, 'field_name') else 'profile_picture',
            name=new_filename,
            content_type=content_type,
            size=processed_size,
            charset=None
        )
        return new_file

    except ValidationError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        logger.warning(f"Erro ao validar ou processar foto de perfil: {e}")
        raise ValidationError("O arquivo enviado não é uma imagem válida ou está corrompido.")
    except Exception as e:
        logger.warning(f"Erro inesperado no processamento da imagem de perfil: {e}")
        raise ValidationError("Não foi possível processar a imagem enviada.")
