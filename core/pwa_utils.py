import io
import logging
import warnings
from PIL import Image, UnidentifiedImageError
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)

MAX_PWA_LOGO_BYTES = 10 * 1024 * 1024  # 10 MB limit

def generate_band_icon(band_logo, size, maskable=False, apple=False):
    """
    Gera um ícone PWA dinâmico para a banda a partir da logo cadastrada.
    Retorna os bytes do arquivo PNG ou None em caso de falha/ausência.
    """
    if not band_logo or not band_logo.name:
        return None

    try:
        if band_logo.size > MAX_PWA_LOGO_BYTES:
            logger.warning(f"Logo excede o tamanho máximo de {MAX_PWA_LOGO_BYTES} bytes. Processamento cancelado.")
            return None
    except Exception as e:
        logger.warning(f"Não foi possível consultar tamanho da logo: {e}")
        # Se não conseguimos checar o tamanho, abortamos por segurança
        return None

    try:
        with band_logo.open('rb') as f:
            # Lê os bytes inteiros para a memória
            img_data = f.read()
            
        with warnings.catch_warnings():
            # Converte DecompressionBombWarning em erro
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            
            img = Image.open(io.BytesIO(img_data))
            # Executa a validação real que dispara possíveis avisos
            img.verify()
            
        # Reabre para manipulação (verify invalida a imagem no Pillow)
        img = Image.open(io.BytesIO(img_data))
        
        # Corrige possível orientação EXIF antes de processar
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass # Ignora se não houver dados EXIF

        img = img.convert("RGBA")
        
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
        logger.warning(f"Falha ao processar logo da banda para geração PWA: {e}")
        return None
    except Exception as e:
        # Para DecompressionBombError e outros não previstos
        logger.warning(f"Erro inesperado no Pillow ao gerar ícone: {e}")
        return None

    bg_color = '#FFFFFF'
    bg = Image.new('RGBA', (size, size), bg_color)
    
    # Normal/Apple: 75% da área; Maskable: 65% (para respeitar a safe zone circular)
    max_ratio = 0.65 if maskable else 0.75
    
    max_w = int(size * max_ratio)
    max_h = int(size * max_ratio)
    
    img_w, img_h = img.size
    
    # Previne divisão por zero se a imagem for corrompida (0x0)
    if img_w == 0 or img_h == 0:
        return None
        
    ratio = min(max_w / img_w, max_h / img_h)
    new_w, new_h = int(img_w * ratio), int(img_h * ratio)
    
    # Redimensiona preservando proporção, usando filtro de alta qualidade
    try:
        resized_img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    except Exception as e:
        logger.warning(f"Erro ao redimensionar logo da banda: {e}")
        return None
    
    # Calcula coordenadas para centralizar
    x = (size - new_w) // 2
    y = (size - new_h) // 2
    
    # Cola a imagem sobre o fundo branco (transparências originais viram branco)
    bg.alpha_composite(resized_img, (x, y))
    
    # Converte para RGB para garantir que não haja transparência final nas bordas
    final_img = bg.convert("RGB")
    
    # Salva em memória
    output = io.BytesIO()
    try:
        final_img.save(output, format='PNG')
        return output.getvalue()
    except Exception as e:
        logger.warning(f"Erro ao salvar ícone PWA final em memória: {e}")
        return None
