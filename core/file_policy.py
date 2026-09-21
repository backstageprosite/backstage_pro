import os
import mimetypes
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
import uuid

MAX_SHOW_FILES = 7
MAX_FILE_SIZE_MB = 10
MAX_SHOW_STORAGE_MB = 35

ALLOWED_EXTENSIONS = [
    '.pdf', '.jpg', '.jpeg', '.png', '.webp', '.docx', '.xlsx'
]

ALLOWED_MIMETYPES = [
    'application/pdf',
    'image/jpeg',
    'image/png',
    'image/webp',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
]

def validate_file_size_and_type(file):
    if not file:
        return
    
    if file.size > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValidationError(_(f"O arquivo {file.name} excede o limite de {MAX_FILE_SIZE_MB}MB."))
    
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError(_(f"A extensão {ext} não é permitida. Formatos aceitos: {', '.join(ALLOWED_EXTENSIONS)}"))
    
    mime_type, _encoding = mimetypes.guess_type(file.name)
    if mime_type and mime_type not in ALLOWED_MIMETYPES:
        raise ValidationError(_(f"O formato do arquivo {file.name} parece inválido ({mime_type})."))
    
    if hasattr(file, 'read'):
        header = file.read(10)
        file.seek(0)
        if ext == '.pdf' and not header.startswith(b'%PDF'):
            raise ValidationError(_("O arquivo parece ser um falso PDF."))
        if ext in ['.jpg', '.jpeg'] and not header.startswith(b'\xff\xd8'):
            raise ValidationError(_("O arquivo parece ser uma falsa imagem JPEG."))
        if ext == '.png' and not header.startswith(b'\x89PNG'):
            raise ValidationError(_("O arquivo parece ser uma falsa imagem PNG."))
        if ext in ['.docx', '.xlsx'] and not header.startswith(b'PK\x03\x04'):
            raise ValidationError(_("O arquivo não parece ser um documento Office válido."))

def get_upload_path_for(prefix):
    def _upload_path(instance, filename):
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            ext = '.bin'
        return f"{prefix}/{uuid.uuid4().hex}{ext}"
    return _upload_path

def get_show_files_info(show):
    """
    BP-PEND-69: Retorna (total_count, total_size_bytes) exclusivamente para
    os Documentos Operacionais do Show (ContractDocument).
    Comprovantes financeiros (FinancialReceipt e ShowPayment) são desacoplados desta cota.
    """
    count = 0
    size = 0
    for doc in show.documents.all():
        if doc.file:
            count += 1
            try:
                size += doc.file.size
            except Exception:
                pass
    return count, size

def check_show_limits(show, new_files_sizes):
    """
    BP-PEND-69: Valida se a adição de novos documentos operacionais (lista de tamanhos em bytes)
    excederá os limites de documentos do show (MAX_SHOW_FILES=7 e MAX_SHOW_STORAGE_MB=35MB).
    """
    count, size = get_show_files_info(show)
    
    if count + len(new_files_sizes) > MAX_SHOW_FILES:
        raise ValidationError(_(f"Não foi possível enviar os arquivos. Este show já possui {count} de {MAX_SHOW_FILES} documentos e permite apenas mais {MAX_SHOW_FILES - count} documento(s)."))
        
    total_new_size = sum(new_files_sizes)
    if (size + total_new_size) > MAX_SHOW_STORAGE_MB * 1024 * 1024:
        raise ValidationError(_(f"Os documentos deste show podem ocupar no máximo {MAX_SHOW_STORAGE_MB} MB. (Usado: {size / 1024 / 1024:.2f} MB)"))


