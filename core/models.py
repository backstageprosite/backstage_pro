from django.db import models
from decimal import Decimal
from core.file_policy import validate_file_size_and_type
from django.contrib.auth.models import AbstractUser
from django.conf import settings
import hashlib
import uuid
from django.core.validators import FileExtensionValidator
from django.core.exceptions import ValidationError

def validate_image_size(value):
    filesize = value.size
    if filesize > 5242880:  # 5 MB
        raise ValidationError("O tamanho máximo permitido para a imagem é 5MB.")

class Band(models.Model):
    class PlanType(models.TextChoices):
        BASICO = 'BASICO', 'Básico'
        AVANCADO = 'AVANCADO', 'Avançado'

    name = models.CharField(max_length=100, verbose_name="Nome da Banda")
    slug = models.SlugField(max_length=100, unique=True, verbose_name="Slug (URL)")
    plan_type = models.CharField(max_length=15, choices=PlanType.choices, default=PlanType.AVANCADO, verbose_name='Plano da banda')
    logo = models.ImageField(validators=[validate_file_size_and_type], upload_to='bands/logos/', blank=True, null=True, verbose_name="Logo da Banda")

    # Controle de Assinatura (SaaS)
    SUBSCRIPTION_PLAN_CHOICES = (
        ('MENSAL', 'Mensal'),
        ('SEMESTRAL', 'Semestral'),
        ('ANUAL', 'Anual'),
    )
    SUBSCRIPTION_STATUS_CHOICES = (
        ('PENDENTE', 'Pendente'),
        ('CONFIRMADO', 'Confirmado'),
        ('CANCELADO', 'Cancelado'),
    )
    subscription_plan = models.CharField(max_length=20, choices=SUBSCRIPTION_PLAN_CHOICES, default='MENSAL', verbose_name='Plano de Assinatura')
    subscription_status = models.CharField(max_length=20, choices=SUBSCRIPTION_STATUS_CHOICES, default='PENDENTE', verbose_name='Status do Pagamento')
    subscription_due_date = models.DateField(blank=True, null=True, verbose_name='Data de Vencimento')
    is_active = models.BooleanField(default=True, verbose_name='Acesso Liberado (Ativo)', help_text="Desmarque para suspender totalmente o acesso desta banda ao sistema.")

    class Meta:
        verbose_name = "Banda"
        verbose_name_plural = "Bandas"


    @property
    def is_advanced(self):
        return self.plan_type == self.PlanType.AVANCADO

    @property
    def is_basic(self):
        return self.plan_type == self.PlanType.BASICO

    @property
    def has_active_subscription(self):
        """
        Retorna se a banda possui assinatura ativa.
        Executa verificação e sincronização de encerramento automático caso aplicável.
        Retorna False se estiver desativada ou suspensa financeiramente por inadimplência (>= 5 dias).
        """
        sub = self.subscriptions.filter(is_deleted=False).order_by('-created_at').first()
        if not sub:
            return self.is_active
        sub.check_and_sync_auto_expiration()
        if sub.status != 'ATIVO':
            return False
        if sub.is_financially_suspended:
            return False
        return True

    @property
    def dynamic_status(self):
        if self.status == 'PAGO':
            return 'PAGO'
        elif self.status == 'CANCELADO':
            return 'CANCELADO'
            
        from django.utils import timezone
        today = timezone.localdate()
        
        if today > self.due_date:
            return 'VENCIDO'
        elif 0 <= (self.due_date - today).days <= 7:
            return 'PROX_VENCIMENTO'
        else:
            return 'PENDENTE'
            
    def get_dynamic_status_display(self):
        st = self.dynamic_status
        if st == 'VENCIDO': return 'Vencido'
        if st == 'PROX_VENCIMENTO': return 'Próx. Vencimento'
        if st == 'PENDENTE': return 'Pendente'
        if st == 'PAGO': return 'Pago'
        if st == 'CANCELADO': return 'Cancelado'
        return st

    def __str__(self):
        return self.name

class User(AbstractUser):
    """
    Modelo customizado de usuário para diferenciar Produtores e Integrantes.
    """
    ROLE_CHOICES = (
        ('PRODUTOR', 'Produtor'),
        ('EMPRESARIO', 'Empresário'),
        ('INTEGRANTE', 'Integrante'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='INTEGRANTE', verbose_name='Perfil')
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='users', null=True, blank=True, verbose_name="Banda")
    email = models.EmailField(unique=False, blank=True, null=True, verbose_name='E-mail')
    phone = models.CharField(max_length=30, blank=True, null=True, verbose_name='Telefone')
    profile_picture = models.ImageField(upload_to='profiles/', blank=True, null=True, verbose_name='Foto de Perfil')
    must_change_password = models.BooleanField(default=False, verbose_name='Exige troca de senha no próximo acesso')

    @property
    def profile_picture_url(self):
        if self.profile_picture and hasattr(self.profile_picture, 'url'):
            return self.profile_picture.url
        return None

    def is_produtor(self):
        return self.role in ['PRODUTOR', 'EMPRESARIO'] or self.is_superuser

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

class Show(models.Model):
    STATUS_PRE_RESERVADO = 'PRE_RESERVADO'
    STATUS_CONFIRMADO = 'CONFIRMADO'
    STATUS_CANCELADO = 'CANCELADO'

    STATUS_CHOICES = (
        (STATUS_PRE_RESERVADO, 'Reserva'),
        (STATUS_CONFIRMADO, 'Confirmado'),
        (STATUS_CANCELADO, 'Cancelado'),
    )

    STATUS_FINANCIALLY_ELIGIBLE = (STATUS_CONFIRMADO,)

    PAYMENT_CHOICES = (
        ('PENDENTE', 'Pendente'),
        ('PARCIAL', 'Pago Parcialmente'),
        ('PAGO', 'Pago Totalmente'),
    )

    # Informações Principais
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='shows', null=True, blank=True, verbose_name="Banda")
    title = models.CharField(max_length=200, blank=True, null=True, verbose_name='Nome do Show')
    event_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='Nome do Evento')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PRE_RESERVADO', verbose_name='Status do Show')
    date = models.DateField(blank=True, null=True, verbose_name='Data')

    # Localização
    city = models.CharField(max_length=100, blank=True, null=True, verbose_name='Cidade')
    venue = models.CharField(max_length=200, blank=True, null=True, verbose_name='Local do Show')
    address = models.CharField(max_length=300, blank=True, null=True, verbose_name='Endereço Completo')
    address_link = models.URLField(max_length=500, blank=True, null=True, verbose_name='Link de Localização')
    attractions = models.TextField(blank=True, null=True, verbose_name='Outras Atrações')

    # Cronograma
    departure_location = models.CharField(max_length=200, blank=True, null=True, verbose_name='Local de Saída')
    departure_location_link = models.URLField(max_length=500, blank=True, null=True, verbose_name='Link de Localização')
    departure_time = models.DateTimeField(blank=True, null=True, verbose_name='Data e Horário Saída')
    arrival_time = models.DateTimeField(blank=True, null=True, verbose_name="Data e Previsão Chegada")
    travel_time = models.CharField(max_length=100, blank=True, null=True, verbose_name="Tempo de Deslocamento")
    distance_km = models.CharField(max_length=100, blank=True, null=True, verbose_name="Distância")
    soundcheck_time = models.TimeField(blank=True, null=True, verbose_name="Passagem de Som")
    soundcheck_end_time = models.TimeField(blank=True, null=True, verbose_name="Final da passagem de som")
    show_time = models.TimeField(blank=True, null=True, verbose_name='Início do Show')
    show_end_time = models.TimeField(blank=True, null=True, verbose_name='Final do Show')
    duration = models.CharField(max_length=50, blank=True, null=True, help_text='Ex: 2 horas', verbose_name='Duração do Show')

    # Financeiro & Contrato (Restrito)
    contractor_name = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contratante')
    contractor_phone = models.CharField(max_length=20, blank=True, null=True, verbose_name='Telefone do Contratante')
    contract_type = models.CharField(max_length=100, blank=True, null=True, verbose_name='Tipo de Contratação', help_text='Ex: Prefeitura, Empresário, Bilheteria, etc.')
    fee = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, verbose_name='Valor do Cachê')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_CHOICES, default='PENDENTE', verbose_name='Status do Pagamento')

    # Logística
    transport = models.TextField(blank=True, null=True, verbose_name='Transporte')
    flight_number = models.CharField(max_length=50, blank=True, null=True, verbose_name='Número do Voo (Aéreo)')
    airline = models.CharField(max_length=50, blank=True, null=True, verbose_name='Empresa Aérea (Aéreo)')
    transport_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Transporte)')
    boarding_time = models.TimeField(blank=True, null=True, verbose_name='Horário de Embarque')
    location_link = models.URLField(max_length=500, blank=True, null=True, verbose_name='Link de Localização')
    accommodation_responsible = models.CharField(max_length=255, blank=True, null=True, verbose_name="Responsável")
    accommodation_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Responsável)')
    accommodation = models.TextField(blank=True, null=True, verbose_name='Nome do Hotel')
    accommodation_city = models.CharField(max_length=255, blank=True, null=True, verbose_name='Cidade da Hospedagem')
    accommodation_address = models.CharField(max_length=255, blank=True, null=True, verbose_name='Endereço da Hospedagem')
    accommodation_link = models.URLField(max_length=500, blank=True, null=True, verbose_name='Link de Localização')
    checkout_time = models.TimeField(blank=True, null=True, verbose_name='Saída p/ Show')
    dressing_room = models.TextField(blank=True, null=True, verbose_name='Camarim')
    dressing_room_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Camarim)')
    catering = models.TextField(blank=True, null=True, verbose_name='Alimentação')
    wardrobe = models.TextField(blank=True, null=True, verbose_name='Figurino')
    transfer = models.TextField(blank=True, null=True, verbose_name='Palco/Baldeação')
    transfer_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Palco/Baldeação)')

    # Informações Técnicas
    sound_system = models.CharField(max_length=255, blank=True, null=True, verbose_name='Sistema de Sonorização')
    sound_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Som)')

    lighting_system = models.CharField(max_length=255, blank=True, null=True, verbose_name='Sistema de Iluminação')
    lighting_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Luz)')

    led_system = models.CharField(max_length=255, blank=True, null=True, verbose_name='Sistema de LED')
    led_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (LED)')

    backline = models.CharField(max_length=255, blank=True, null=True, verbose_name='Backline')
    backline_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Backline)')

    pyrotechnics = models.CharField(max_length=255, blank=True, null=True, verbose_name='Efeitos Pirotecnia')
    pyrotechnics_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Pirotecnia)')

    generator_system = models.CharField(max_length=255, blank=True, null=True, verbose_name='Gerador')
    generator_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Gerador)')
    loaders_system = models.CharField(max_length=255, blank=True, null=True, verbose_name='Carregadores')
    loaders_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Carregadores)')
    local_production = models.CharField(max_length=255, blank=True, null=True, verbose_name='Produção Local')
    local_production_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Produção Local)')

    # Observações
    internal_notes = models.TextField(blank=True, null=True, help_text='Visível apenas para a produção.', verbose_name='Observações Internas')
    band_notes = models.TextField(blank=True, null=True, help_text='Visível para todos os integrantes.', verbose_name='Observações para a Banda')

    # Revisão de Notificações
    notification_revision = models.PositiveBigIntegerField(default=0, editable=False)

    # Auditoria de Datas (BP-PEND-57)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True, verbose_name="Data de Criação")
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True, verbose_name="Última Atualização")

    class Meta:
        verbose_name = 'Show'
        verbose_name_plural = 'Shows'
        ordering = ['date', 'show_time']

    def __str__(self):
        if self.date:
            return f"{self.date.strftime('%d/%m/%Y')} - {self.title} ({self.city})"
        return f"Sem data - {self.title} ({self.city})"

    def get_display_label(self):
        date_str = self.date.strftime('%d/%m/%Y') if self.date else 'Data não informada'
        name = (self.title or self.event_name or 'SHOW SEM NOME').upper()
        return f'{date_str} - {name}'

    @property
    def is_past(self):
        from datetime import date
        if self.date:
            return self.date < date.today()
        return False

    def save(self, *args, **kwargs):
        # BP-PEND-57: Garantir que updated_at reflita alterações reais.
        # Se update_fields for especificado explicitamente pelo chamador, respeitar kwargs.
        if self.pk and 'update_fields' not in kwargs:
            orig = Show.objects.filter(pk=self.pk).values().first()
            if orig:
                fields_to_check = [f.attname for f in self._meta.concrete_fields if f.name not in ('updated_at', 'created_at')]
                
                def _normalize(val):
                    if val is None or val == '':
                        return ''
                    return val

                has_change = any(_normalize(getattr(self, f)) != _normalize(orig.get(f)) for f in fields_to_check)
                if not has_change:
                    # Nenhuma alteração de dados no Show: salvar preservando o updated_at atual
                    kwargs['update_fields'] = [
                        f.name for f in self._meta.concrete_fields
                        if f.name != 'updated_at' and not f.primary_key
                    ]
        super().save(*args, **kwargs)

def contract_upload_path(instance, filename):
    return f'shows/{instance.id}/documentos/{filename}'

def receipt_upload_path(instance, filename):
    # Salva o arquivo na pasta media/shows/ID_DO_SHOW/comprovantes/nome_do_arquivo
    return f'shows/{instance.show.id}/comprovantes/{filename}'

class ContractDocument(models.Model):
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name='documents')
    description = models.CharField(max_length=200, verbose_name='Descrição do Documento')
    file = models.FileField(validators=[validate_file_size_and_type], upload_to=contract_upload_path, verbose_name='Arquivo / Documento')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Documento Anexado'
        verbose_name_plural = 'Documentos Anexados (Apenas Produção)'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.description} ({self.show.title})"

class FinancialReceipt(models.Model):
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name='receipts')
    description = models.CharField(max_length=200, verbose_name='Do que se trata?')
    date = models.DateField(blank=True, null=True, verbose_name='Data')
    category = models.CharField(max_length=100, blank=True, null=True, verbose_name='Categoria')
    value = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor (R$)')
    file = models.FileField(validators=[validate_file_size_and_type], upload_to=receipt_upload_path, verbose_name='Arquivo / Comprovante')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Comprovante Financeiro'
        verbose_name_plural = 'Comprovantes Financeiros (Apenas Produção)'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.description} - R$ {self.value}"

def payment_upload_path(instance, filename):
    return f'shows/{instance.show.id}/recebimentos/{filename}'

class ShowPayment(models.Model):
    PAYMENT_METHOD_CHOICES = (
        ('PIX', 'Pix'),
        ('TRANSFERENCIA', 'Transferência'),
        ('DINHEIRO', 'Dinheiro'),
        ('CARTAO', 'Cartão'),
        ('BOLETO', 'Boleto'),
        ('CHEQUE', 'Cheque'),
        ('OUTRO', 'Outro'),
    )

    STATUS_CHOICES = (
        ('PENDENTE', 'Pendente'),
        ('RECEBIDO', 'Recebido'),
        ('ATRASADO', 'Atrasado'),
        ('CANCELADO', 'Cancelado'),
    )

    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name='payments')
    description = models.CharField(max_length=200, verbose_name='Descrição (Ex: Sinal, Parcela 2)')
    value = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor (R$)')
    expected_date = models.DateField(blank=True, null=True, verbose_name='Data Prevista')
    receipt_date = models.DateField(blank=True, null=True, verbose_name='Data de Recebimento')
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, default='PIX', verbose_name='Forma de Pagamento')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='RECEBIDO', verbose_name='Status')
    file = models.FileField(validators=[validate_file_size_and_type], upload_to=payment_upload_path, blank=True, null=True, verbose_name='Arquivo / Comprovante')
    observations = models.TextField(blank=True, null=True, verbose_name='Observações')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_payments', verbose_name='Criado por')

    class Meta:
        verbose_name = 'Recebimento'
        verbose_name_plural = 'Recebimentos do Show (Apenas Produção)'
        ordering = ['expected_date', '-created_at']

    def __str__(self):
        return f"{self.description} - R$ {self.value} ({self.get_status_display()})"

class ShowTeamCost(models.Model):
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name='team_costs')
    name = models.CharField(max_length=200, verbose_name='Nome do Integrante')
    date = models.DateField(blank=True, null=True, verbose_name='Data')
    role = models.CharField(max_length=100, blank=True, null=True, verbose_name='Função')
    value = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor (R$)')

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_team_costs', verbose_name='Criado por')

    class Meta:
        verbose_name = 'Custo com Equipe'
        verbose_name_plural = 'Custos com Equipe (Apenas Produção)'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - R$ {self.value}"

class Contact(models.Model):
    CONTACT_TYPE_CHOICES = (
        ('HOSPEDAGEM', 'Hotel'),
        ('RESTAURANTE', 'Restaurante'),
        ('ESTABELECIMENTO', 'Empresa'),
        ('FORNECEDOR', 'Fornecedor'),
        ('PRODUTOR', 'Produtor(a)'),
        ('CONTRATANTE', 'Contratante'),
    )

    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='contacts', verbose_name='Banda')
    name = models.CharField(max_length=200, verbose_name='Nome')
    contact_type = models.CharField(max_length=50, choices=CONTACT_TYPE_CHOICES, default='FORNECEDOR', verbose_name='Tipo')
    phone = models.CharField(max_length=200, blank=True, null=True, verbose_name='Contato (Telefone)')
    email = models.EmailField(max_length=254, blank=True, null=True, verbose_name='E-mail')
    location = models.CharField(max_length=255, blank=True, null=True, verbose_name='Local')
    link = models.URLField(max_length=500, blank=True, null=True, verbose_name='Link')
    notes = models.TextField(blank=True, null=True, verbose_name='Observações')

    public_information = models.TextField(blank=True, null=True, verbose_name='Informações públicas')
    is_shared_globally = models.BooleanField(default=False, verbose_name='Compartilhado globalmente')
    shared_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='shared_contacts', verbose_name='Compartilhado por')
    shared_at = models.DateTimeField(null=True, blank=True, verbose_name='Compartilhado em')

    normalized_phone = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    normalized_email = models.EmailField(max_length=254, blank=True, null=True, db_index=True)

    is_hidden = models.BooleanField(default=False, db_index=True, verbose_name='Oculto pelo Administrador')
    copied_from = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='copied_contacts', verbose_name='Copiado de')

    class Meta:
        verbose_name = 'Contato (Banco de Dados)'
        verbose_name_plural = 'Banco de Dados'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=['normalized_phone'],
                condition=models.Q(is_shared_globally=True, normalized_phone__isnull=False) & ~models.Q(normalized_phone=''),
                name='unique_global_phone'
            ),
            models.UniqueConstraint(
                fields=['normalized_email'],
                condition=models.Q(is_shared_globally=True, normalized_email__isnull=False) & ~models.Q(normalized_email=''),
                name='unique_global_email'
            ),
            models.UniqueConstraint(
                fields=['band', 'copied_from'],
                condition=models.Q(copied_from__isnull=False),
                name='unique_contact_copy_per_band'
            )
        ]

    @property
    def is_advanced(self):
        return self.plan_type == self.PlanType.AVANCADO

    @property
    def is_basic(self):
        return self.plan_type == self.PlanType.BASICO

    @property
    def dynamic_status(self):
        if self.status == 'PAGO':
            return 'PAGO'
        elif self.status == 'CANCELADO':
            return 'CANCELADO'
        elif self.status == 'ISENTO':
            return 'ISENTO'
        
        from django.utils import timezone
        today = timezone.localdate()
        
        if today > self.due_date:
            return 'VENCIDO'
        elif 0 <= (self.due_date - today).days <= 7:
            return 'PROX_VENCIMENTO'
        else:
            return 'PENDENTE'
            
    def get_dynamic_status_display(self):
        st = self.dynamic_status
        if st == 'VENCIDO': return 'Vencido'
        if st == 'PROX_VENCIMENTO': return 'Próx. Vencimento'
        if st == 'PENDENTE': return 'Pendente'
        if st == 'PAGO': return 'Pago'
        if st == 'CANCELADO': return 'Cancelado'
        if st == 'ISENTO': return 'Isento'
        return st

    def save(self, *args, **kwargs):
        if self.phone:
            import re
            digits = re.sub(r'\D', '', self.phone)
            if digits.startswith('55') and len(digits) > 11:
                digits = digits[2:]
            self.normalized_phone = digits
        else:
            self.normalized_phone = ""

        if self.email:
            self.normalized_email = self.email.strip().lower()
        else:
            self.normalized_email = ""

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - {self.get_contact_type_display()}"

class ContactLike(models.Model):
    contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name='likes', verbose_name='Contato')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='contact_likes', verbose_name='Produtor')
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='contact_likes', verbose_name='Banda do Produtor')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Data da Curtida')

    class Meta:
        verbose_name = 'Curtida de Contato'
        verbose_name_plural = 'Curtidas de Contatos'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['contact', 'user'],
                name='unique_contact_like_per_user'
            )
        ]

    def __str__(self):
        return f"Curtida de {self.user.username} em {self.contact.name}"

def commercial_proposal_document_upload_path(instance, filename):
    import uuid
    import os
    ext = os.path.splitext(filename)[1].lower()
    return f'commercial/{instance.proposal.band.id}/{instance.proposal.id}/{uuid.uuid4().hex}{ext}'

class CommercialProposal(models.Model):
    class Phase(models.TextChoices):
        RESERVA = 'RESERVA', 'Reserva'
        FECHADO = 'FECHADO', 'Fechado'
        DESISTENCIA = 'DESISTENCIA', 'Desistência'

    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='commercial_proposals', verbose_name='Banda')
    show = models.OneToOneField(
        Show,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='commercial_proposal',
        verbose_name='Show Vinculado'
    )
    name = models.CharField(max_length=200, verbose_name='Nome da Solicitação')
    date = models.DateField(verbose_name='Data do Show')
    time = models.TimeField(blank=True, null=True, verbose_name='Horário do Show')
    contact_name = models.CharField(max_length=255, blank=True, null=True, verbose_name='Nome do Contato')
    contact = models.CharField(max_length=200, blank=True, null=True, verbose_name='Contato')
    normalized_contact = models.CharField(max_length=50, blank=True, null=True, verbose_name='Contato Normalizado')
    location = models.CharField(max_length=255, blank=True, null=True, verbose_name='Local')
    origin = models.CharField(max_length=200, blank=True, null=True, verbose_name='Origem')
    fee = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, verbose_name='Valor do Cachê (R$)')
    phase = models.CharField(
        max_length=20,
        choices=Phase.choices,
        default=Phase.RESERVA,
        db_index=True,
        verbose_name='Fase do Orçamento'
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_commercial_proposals',
        verbose_name='Criado por'
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    class Meta:
        verbose_name = 'Solicitação Comercial'
        verbose_name_plural = 'Solicitações Comerciais'
        ordering = ['date', 'time', 'id']
        indexes = [
            models.Index(fields=['band', 'phase', 'date'], name='idx_commercial_band_phase_date'),
        ]

    def save(self, *args, **kwargs):
        if self.contact:
            import re
            digits = re.sub(r'\D', '', self.contact)
            if digits.startswith('55') and len(digits) > 11:
                digits = digits[2:]
            self.normalized_contact = digits
        else:
            self.normalized_contact = ""
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} - {self.get_phase_display()} ({self.date.strftime('%d/%m/%Y') if self.date else 'Sem data'})"

class CommercialProposalDocument(models.Model):
    proposal = models.ForeignKey(
        CommercialProposal,
        on_delete=models.CASCADE,
        related_name='documents',
        verbose_name='Solicitação'
    )
    file = models.FileField(
        validators=[validate_file_size_and_type],
        upload_to=commercial_proposal_document_upload_path,
        verbose_name='Arquivo'
    )
    original_name = models.CharField(max_length=255, verbose_name='Nome Original')
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='uploaded_commercial_documents',
        verbose_name='Enviado por'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='Data de Envio')

    class Meta:
        verbose_name = 'Documento Comercial'
        verbose_name_plural = 'Documentos Comerciais'
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.original_name} ({self.proposal.name})"

class BandSubscription(models.Model):
    CYCLE_CHOICES = (
        ('MENSAL', 'Mensal'),
        ('SEMESTRAL', 'Semestral'),
        ('ANUAL', 'Anual'),
        ('PERSONALIZADO', 'Personalizado'),
    )
    STATUS_CHOICES = (
        ('ATIVO', 'Ativa'),
        ('DESATIVADO', 'Desativada'),
    )
    PAYMENT_METHOD_CHOICES = (
        ('PIX', 'Pix'),
        ('BOLETO', 'Boleto'),
        ('CARTAO', 'Cartão'),
        ('TRANSFERENCIA', 'Transferência'),
        ('DINHEIRO', 'Dinheiro'),
        ('OUTRO', 'Outro'),
    )

    COMMERCIAL_CONDITION_PAID = 'PAGO'
    COMMERCIAL_CONDITION_PARTNERSHIP = 'PARCERIA'
    COMMERCIAL_CONDITION_CHOICES = (
        (COMMERCIAL_CONDITION_PAID, 'Pago'),
        (COMMERCIAL_CONDITION_PARTNERSHIP, 'Parceria'),
    )

    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='subscriptions', verbose_name='Banda')
    commercial_condition = models.CharField(
        max_length=20,
        choices=COMMERCIAL_CONDITION_CHOICES,
        default=COMMERCIAL_CONDITION_PAID,
        db_index=True,
        verbose_name='Condição Comercial'
    )
    plan_name = models.CharField(max_length=100, default='Mensal', verbose_name='Nome do Plano')
    billing_cycle = models.CharField(max_length=20, choices=CYCLE_CHOICES, default='MENSAL', verbose_name='Ciclo de Cobrança')
    contracted_value = models.DecimalField(max_digits=10, decimal_places=2, default=300.00, verbose_name='Valor Contratado')
    start_date = models.DateField(blank=True, null=True, verbose_name='Data de Início')
    next_due_date = models.DateField(blank=True, null=True, verbose_name='Próximo Vencimento')
    auto_renew = models.BooleanField(default=False, verbose_name='Renovar automaticamente')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ATIVO', verbose_name='Status da Assinatura')
    payment_method_preference = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, default='PIX', verbose_name='Preferência de Pagamento')

    financial_responsible_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='Responsável Financeiro')
    billing_phone = models.CharField(max_length=30, blank=True, null=True, verbose_name='Telefone de Cobrança (WhatsApp)')
    billing_email = models.EmailField(blank=True, null=True, verbose_name='E-mail de Cobrança')
    internal_notes = models.TextField(blank=True, null=True, verbose_name='Observações Internas')

    # Gateway fields (Asaas / integração)
    gateway_provider = models.CharField(max_length=30, blank=True, null=True, default=None, verbose_name='Provedor do Gateway')
    gateway_customer_id = models.CharField(max_length=100, blank=True, null=True, default=None, db_index=True, verbose_name='ID do Cliente no Gateway')
    gateway_subscription_id = models.CharField(max_length=100, blank=True, null=True, default=None, db_index=True, verbose_name='ID da Assinatura no Gateway')
    gateway_checkout_id = models.CharField(max_length=100, blank=True, null=True, default=None, db_index=True, verbose_name='ID do Checkout no Gateway')
    gateway_external_reference = models.CharField(max_length=100, blank=True, null=True, default=None, db_index=True, verbose_name='Referência Externa do Gateway')
    cancel_at_period_end = models.BooleanField(default=False, verbose_name='Cancelar ao fim do período')
    canceled_at = models.DateTimeField(null=True, blank=True, verbose_name='Data de Cancelamento')
    grace_period_started_at = models.DateTimeField(null=True, blank=True, verbose_name='Início da Tolerância')

    is_deleted = models.BooleanField(default=False, verbose_name='Excluída')
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name='Data de Exclusão')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Assinatura SaaS'
        verbose_name_plural = 'Assinaturas SaaS'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['gateway_provider', 'gateway_subscription_id'],
                condition=models.Q(gateway_subscription_id__isnull=False) & ~models.Q(gateway_subscription_id=''),
                name='unique_subscription_per_gateway_provider'
            ),
            models.UniqueConstraint(
                fields=['gateway_provider', 'gateway_checkout_id'],
                condition=models.Q(gateway_checkout_id__isnull=False) & ~models.Q(gateway_checkout_id=''),
                name='unique_checkout_per_gateway_provider'
            ),
        ]

    @property
    def is_partnership(self):
        return self.commercial_condition == self.COMMERCIAL_CONDITION_PARTNERSHIP

    @property
    def is_paid_commercial_condition(self):
        return self.commercial_condition == self.COMMERCIAL_CONDITION_PAID

    def days_overdue(self):
        """
        Calcula a quantidade de dias em atraso para assinaturas ativas e em renovação automática.
        Retorna 0 se em dia, se cancelamento já agendado ou se for condição comercial de Parceria.
        """
        if self.is_partnership:
            return 0
        from django.utils import timezone
        if self.status != 'ATIVO' or self.cancel_at_period_end or not self.auto_renew or not self.next_due_date:
            return 0
        today = timezone.localdate()
        diff = (today - self.next_due_date).days
        return max(0, diff)

    @property
    def is_overdue_tolerance(self):
        """
        Tolerância de 1 a 4 dias de atraso.
        Acesso operacional normal mantido, mas sinalização visual na Assinatura.
        """
        return 1 <= self.days_overdue() < 5

    @property
    def is_financially_suspended(self):
        """
        Suspensão financeira a partir do 5º dia de atraso (dias >= 5).
        """
        return self.days_overdue() >= 5

    def apply_payment_success(self, paid_date=None):
        """
        Aplica a quitação de um pagamento na assinatura:
        1. Se for condição comercial de Parceria: ignora quitação/avanço financeiro com segurança.
        2. Se o pagamento ocorreu DENTRO da tolerância (< 5 dias de atraso em relação a next_due_date):
           - Preserva a data-base (billing anchor) original da assinatura.
           - next_due_date avança +1 período a partir da data de vencimento atual (ou original).
        3. Se o pagamento ocorreu APÓS a suspensão financeira (>= 5 dias de atraso em relação a next_due_date ou desativada):
           - REGULARIZAÇÃO COM REATIVAÇÃO: a data do pagamento aprovado passa a ser a NOVA DATA-BASE.
           - next_due_date é recalculado a partir de paid_date (+1 mês ou +1 ano).
        4. Restaura o status para 'ATIVO' e auto_renew=True.
        """
        if self.is_partnership:
            return False
        from django.utils import timezone
        from core.services.payments.base import calculate_next_billing_date
        import datetime

        if not paid_date:
            paid_date = timezone.localdate()
        elif isinstance(paid_date, datetime.datetime):
            paid_date = timezone.localdate(paid_date) if timezone.is_aware(paid_date) else paid_date.date()
        elif isinstance(paid_date, str):
            paid_date = datetime.date.fromisoformat(paid_date)

        # Determina se estava suspenso financeiramente com base na data do pagamento vs next_due_date
        was_suspended = False
        if self.status == 'DESATIVADO':
            was_suspended = True
        elif self.next_due_date:
            diff_days = (paid_date - self.next_due_date).days
            if diff_days >= 5:
                was_suspended = True

        if was_suspended:
            # Regularização após suspensão: nova data-base baseada na data do pagamento
            self.start_date = paid_date
            self.next_due_date = calculate_next_billing_date(paid_date, self.billing_cycle or 'MENSAL', periods_offset=1)
        else:
            # Pagamento em dia ou durante tolerância: preserva a data-base original
            base_anchor = self.next_due_date or paid_date
            self.next_due_date = calculate_next_billing_date(base_anchor, self.billing_cycle or 'MENSAL', periods_offset=1)

        self.status = 'ATIVO'
        self.auto_renew = True
        self.cancel_at_period_end = False
        self.canceled_at = None
        self.save(update_fields=['status', 'auto_renew', 'cancel_at_period_end', 'canceled_at', 'start_date', 'next_due_date', 'updated_at'])
        return was_suspended

    @property
    def is_canceled_period_expired(self):
        """
        Assinatura com cancelamento voluntário agendado (cancel_at_period_end=True) ou
        plano anual sem renovação automática (billing_cycle='ANUAL', auto_renew=False)
        que já atingiu/ultrapassou o fim do período pago.
        O acesso operacional é concedido até o final do dia de next_due_date.
        Após esse dia (today > next_due_date), ou quando desativada por cancelamento, o período está encerrado.
        """
        if self.status == 'DESATIVADO' and self.cancel_at_period_end:
            return True
        from django.utils import timezone
        if self.cancel_at_period_end and not self.auto_renew and self.next_due_date:
            today = timezone.localdate()
            return today > self.next_due_date
        if self.billing_cycle == 'ANUAL' and not self.auto_renew and self.next_due_date:
            today = timezone.localdate()
            return today > self.next_due_date
        return False

    def check_and_sync_auto_expiration(self):
        """
        Regra de encerramento automático do período já pago:
        Quando cancel_at_period_end=True e auto_renew=False, ou plano anual sem renovação automática,
        e today > next_due_date (após o dia final pago), a assinatura passa automaticamente para DESATIVADO.
        Assinaturas sob condição de Parceria nunca expiram automaticamente por lógica financeira.
        """
        if self.is_partnership:
            return False
        from django.utils import timezone
        today = timezone.localdate()
        if self.status == 'ATIVO':
            is_expired_annual = (self.billing_cycle == 'ANUAL' and not self.auto_renew)
            if (self.cancel_at_period_end and not self.auto_renew) or is_expired_annual:
                if self.next_due_date and today > self.next_due_date:
                    self.status = 'DESATIVADO'
                    self.save(update_fields=['status', 'updated_at'])
                    return True
        return False

    def __str__(self):
        return f"Assinatura - {self.band.name}"

def billing_proof_upload_path(instance, filename):
    return f'billing/{instance.band.id}/comprovantes/{filename}'

def rider_upload_path(instance, filename):
    return f'bands/{instance.band.slug}/riders/{filename}'

class RiderDocument(models.Model):
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='riders', verbose_name='Banda')
    name = models.CharField(max_length=200, verbose_name='Nome')
    file = models.FileField(validators=[validate_file_size_and_type], upload_to=rider_upload_path, verbose_name='Arquivo')
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True, verbose_name='ID de Compartilhamento Público')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Criado por')

    class Meta:
        verbose_name = 'Rider'
        verbose_name_plural = 'Riders'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.band.name}"

class BillingRecord(models.Model):
    STATUS_CHOICES = (
        ('PENDENTE', 'Pendente'),
        ('PAGO', 'Pago'),
        ('CANCELADO', 'Cancelado'),
        ('ISENTO', 'Isento'),
    )
    PAYMENT_METHOD_CHOICES = (
        ('PIX', 'Pix'),
        ('BOLETO', 'Boleto'),
        ('CARTAO', 'Cartão'),
        ('TRANSFERENCIA', 'Transferência'),
        ('DINHEIRO', 'Dinheiro'),
        ('OUTRO', 'Outro'),
    )

    subscription = models.ForeignKey(BandSubscription, on_delete=models.CASCADE, related_name='records', verbose_name='Assinatura')
    band = models.ForeignKey('Band', on_delete=models.CASCADE, related_name='billing_records', verbose_name='Banda')
    reference_period = models.CharField(max_length=100, verbose_name='Período de Referência (Ex: Agosto/2026)')
    
    # Snapshot fields
    plan_name = models.CharField(max_length=100, blank=True, null=True, verbose_name='Nome do Plano na Época')
    billing_cycle = models.CharField(max_length=20, blank=True, null=True, verbose_name='Ciclo na Época')
    
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor Cobrado')
    due_date = models.DateField(verbose_name='Vencimento da Fatura')
    paid_date = models.DateField(blank=True, null=True, verbose_name='Data do Pagamento')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE', verbose_name='Status')
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, blank=True, null=True, verbose_name='Forma de Pagamento')
    proof_file = models.FileField(validators=[validate_file_size_and_type], upload_to=billing_proof_upload_path, blank=True, null=True, verbose_name='Comprovante')
    notes = models.TextField(blank=True, null=True, verbose_name='Observações')

    # Gateway fields (Asaas / conciliação)
    gateway_provider = models.CharField(max_length=30, blank=True, null=True, default=None, verbose_name='Provedor do Gateway')
    gateway_payment_id = models.CharField(max_length=100, blank=True, null=True, default=None, db_index=True, verbose_name='ID do Pagamento no Gateway')
    gateway_invoice_url = models.URLField(max_length=500, blank=True, null=True, default=None, verbose_name='URL da Fatura no Gateway')
    gateway_external_reference = models.CharField(max_length=100, blank=True, null=True, default=None, db_index=True, verbose_name='Referência Externa no Gateway')
    gateway_event_status = models.CharField(max_length=50, blank=True, null=True, default=None, verbose_name='Status do Evento no Gateway')

    # Vinculo com compra anual (quando aplicavel)
    annual_purchase = models.ForeignKey(
        'AnnualPlanPurchase',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='billing_records',
        verbose_name='Compra Anual Vinculada'
    )
    installment_number = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='Número da Parcela (ex: 1 a 5)'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_billings', verbose_name='Criado por')

    class Meta:
        verbose_name = 'Fatura SaaS'
        verbose_name_plural = 'Faturas SaaS'
        ordering = ['-due_date', '-created_at']
        unique_together = ('subscription', 'due_date')
        constraints = [
            models.UniqueConstraint(
                fields=['gateway_provider', 'gateway_payment_id'],
                condition=models.Q(gateway_payment_id__isnull=False) & ~models.Q(gateway_payment_id=''),
                name='unique_payment_per_gateway_provider'
            )
        ]

    def __str__(self):
        return f"{self.band.name} - {self.reference_period} ({self.get_status_display()})"

    @property
    def is_vencendo_7d(self):
        import datetime
        if self.status != 'PENDENTE' or not self.due_date: return False
        hoje = datetime.date.today()
        diff = (self.due_date - hoje).days
        return 0 <= diff <= 7
        
    @property
    def is_vencido(self):
        import datetime
        if self.status != 'PENDENTE' or not self.due_date: return False
        return self.due_date < datetime.date.today()


    @property
    def is_advanced(self):
        return self.plan_type == self.PlanType.AVANCADO

    @property
    def is_basic(self):
        return self.plan_type == self.PlanType.BASICO

    @property
    def dynamic_status(self):
        if self.status == 'PAGO':
            return 'PAGO'
        elif self.status == 'CANCELADO':
            return 'CANCELADO'
        elif self.status == 'ISENTO':
            return 'ISENTO'
        
        from django.utils import timezone
        today = timezone.localdate()
        
        if today > self.due_date:
            return 'VENCIDO'
        elif 0 <= (self.due_date - today).days <= 7:
            return 'PROX_VENCIMENTO'
        else:
            return 'PENDENTE'
            
    def get_dynamic_status_display(self):
        st = self.dynamic_status
        if st == 'VENCIDO': return 'Vencido'
        if st == 'PROX_VENCIMENTO': return 'Próx. Vencimento'
        if st == 'PENDENTE': return 'Pendente'
        if st == 'PAGO': return 'Pago'
        if st == 'CANCELADO': return 'Cancelado'
        if st == 'ISENTO': return 'Isento'
        return st

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        old_status = None
        if not is_new:
            old_status = type(self).objects.get(pk=self.pk).status

        super().save(*args, **kwargs)

        


class Notification(models.Model):
    EVENT_CHOICES = (
        ('NEW_SHOW', 'Novo show'),
        ('SHOW_CANCELLED', 'Show cancelado'),
        ('SHOW_DATE_CHANGED', 'Data do show alterada'),
        ('SHOW_START_TIME_CHANGED', 'Horário inicial do show alterado'),
        ('SHOW_CONFIRMED', 'Show confirmado'),
    )

    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='notifications', verbose_name='Banda')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications', verbose_name='Destinatário')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications_as_actor', verbose_name='Ator')

    event_type = models.CharField(max_length=50, choices=EVENT_CHOICES, verbose_name='Tipo de Evento')
    title = models.CharField(max_length=200, verbose_name='Título')
    message = models.TextField(verbose_name='Mensagem')
    target_url = models.CharField(max_length=500, verbose_name='URL de Destino')

    related_show = models.ForeignKey('Show', on_delete=models.SET_NULL, null=True, blank=True, related_name='notifications', verbose_name='Show Relacionado')
    event_key = models.CharField(max_length=255, verbose_name='Chave de Idempotência')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    read_at = models.DateTimeField(null=True, blank=True, verbose_name='Lido em')

    class Meta:
        verbose_name = 'Notificação'
        verbose_name_plural = 'Notificações'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['band', 'recipient', 'event_key'], name='unique_notification_recipient_event')
        ]
        indexes = [
            models.Index(fields=['recipient', 'band', 'read_at', 'created_at']),
            models.Index(fields=['band', 'created_at']),
        ]

    @property
    def is_read(self):
        return self.read_at is not None

    def mark_as_read(self):
        if not self.is_read:
            from django.utils import timezone
            self.read_at = timezone.now()
            self.save(update_fields=['read_at'])

    def __str__(self):
        return f"{self.event_type} para {self.recipient} na banda {self.band}"



class WebPushSubscription(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="web_push_subscriptions", verbose_name="Usuário")
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name="web_push_subscriptions", verbose_name="Banda")
    endpoint = models.TextField(verbose_name="Endpoint")
    endpoint_hash = models.CharField(max_length=64, unique=True, editable=False, verbose_name="Hash do Endpoint")
    p256dh = models.CharField(max_length=255, verbose_name="Chave Pública P256DH")
    auth = models.CharField(max_length=255, verbose_name="Chave de Autenticação")
    service_worker_scope = models.CharField(max_length=500, verbose_name="Scope do Service Worker")
    user_agent = models.CharField(max_length=512, blank=True, default="", verbose_name="User Agent")
    expiration_time = models.DateTimeField(null=True, blank=True, verbose_name="Data de Expiração")
    is_active = models.BooleanField(default=True, verbose_name="Ativo")
    failure_count = models.PositiveSmallIntegerField(default=0, verbose_name="Contagem de Falhas")
    last_success_at = models.DateTimeField(null=True, blank=True, verbose_name="Último Sucesso")
    last_failure_at = models.DateTimeField(null=True, blank=True, verbose_name="Última Falha")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Criado em")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Atualizado em")

    class Meta:
        verbose_name = "Inscrição Web Push"
        verbose_name_plural = "Inscrições Web Push"
        indexes = [
            models.Index(fields=['user', 'band', 'is_active']),
            models.Index(fields=['band', 'is_active']),
        ]

    def _refresh_endpoint_hash(self):
        if not self.endpoint:
            self.endpoint_hash = ""
            return
        import hashlib
        self.endpoint_hash = hashlib.sha256(self.endpoint.encode('utf-8')).hexdigest()

    def full_clean(self, exclude=None, validate_unique=True, validate_constraints=True):
        self._refresh_endpoint_hash()
        return super().full_clean(
            exclude=exclude,
            validate_unique=validate_unique,
            validate_constraints=validate_constraints,
        )

    @property
    def is_advanced(self):
        return self.plan_type == self.PlanType.AVANCADO

    @property
    def is_basic(self):
        return self.plan_type == self.PlanType.BASICO

    @property
    def dynamic_status(self):
        if self.status == 'PAGO':
            return 'PAGO'
        elif self.status == 'CANCELADO':
            return 'CANCELADO'
        elif self.status == 'ISENTO':
            return 'ISENTO'
        
        from django.utils import timezone
        today = timezone.localdate()
        
        if today > self.due_date:
            return 'VENCIDO'
        elif 0 <= (self.due_date - today).days <= 7:
            return 'PROX_VENCIMENTO'
        else:
            return 'PENDENTE'
            
    def get_dynamic_status_display(self):
        st = self.dynamic_status
        if st == 'VENCIDO': return 'Vencido'
        if st == 'PROX_VENCIMENTO': return 'Próx. Vencimento'
        if st == 'PENDENTE': return 'Pendente'
        if st == 'PAGO': return 'Pago'
        if st == 'CANCELADO': return 'Cancelado'
        if st == 'ISENTO': return 'Isento'
        return st

    def save(self, *args, **kwargs):
        self._refresh_endpoint_hash()

        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'endpoint' in update_fields:
            if 'endpoint_hash' not in update_fields:
                kwargs['update_fields'] = list(update_fields) + ['endpoint_hash']

        self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.service_worker_scope:
            from django.core.exceptions import ValidationError
            import urllib.parse
            import unicodedata

            scope = self.service_worker_scope

            # Anti-double encoding
            decoded_once = urllib.parse.unquote(scope)
            decoded_twice = urllib.parse.unquote(decoded_once)

            if decoded_once != decoded_twice:
                raise ValidationError({'service_worker_scope': 'Double encoding detectado'})

            scope = decoded_once

            for char in scope:
                if unicodedata.category(char).startswith('C'):
                    raise ValidationError({'service_worker_scope': 'Não pode conter caracteres de controle'})

            if '\\' in scope:
                raise ValidationError({'service_worker_scope': 'Não pode conter backslash'})

            if not scope.startswith('/'):
                raise ValidationError({'service_worker_scope': 'Deve começar com /'})

            if not scope.endswith('/'):
                raise ValidationError({'service_worker_scope': 'Deve terminar com /'})

            if '//' in scope:
                raise ValidationError({'service_worker_scope': 'Não pode conter //'})

            parsed = urllib.parse.urlsplit(scope)
            if parsed.scheme or parsed.netloc:
                raise ValidationError({'service_worker_scope': 'Não pode conter scheme ou netloc'})

            parts = parsed.path.split('/')
            if '.' in parts or '..' in parts:
                raise ValidationError({'service_worker_scope': 'Não pode conter segmentos . ou ..'})

    def __str__(self):
        return f"Push de {self.user.username} — {self.band.name} — {'Ativa' if self.is_active else 'Inativa'}"

class WebPushDelivery(models.Model):
    class StatusChoices(models.TextChoices):
        PENDING = 'PENDING', 'Pendente'
        SENDING = 'SENDING', 'Enviando'
        SENT = 'SENT', 'Enviado'
        TEMPORARY_FAILURE = 'TEMPORARY_FAILURE', 'Falha Temporária'
        PERMANENT_FAILURE = 'PERMANENT_FAILURE', 'Falha Permanente'
        SKIPPED = 'SKIPPED', 'Ignorado'

    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name='web_push_deliveries', verbose_name='Notificação')
    subscription = models.ForeignKey(WebPushSubscription, on_delete=models.CASCADE, related_name='deliveries', verbose_name='Inscrição Web Push')
    status = models.CharField(max_length=50, choices=StatusChoices.choices, default=StatusChoices.PENDING, verbose_name='Status')

    attempt_count = models.PositiveSmallIntegerField(default=0, verbose_name='Tentativas')
    last_http_status = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name='Último Status HTTP')
    error_code = models.CharField(max_length=64, blank=True, default='', verbose_name='Código de Erro')

    last_attempt_at = models.DateTimeField(null=True, blank=True, verbose_name='Última Tentativa')
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='Enviado em')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    class Meta:
        verbose_name = 'Entrega Web Push'
        verbose_name_plural = 'Entregas Web Push'
        constraints = [
            models.UniqueConstraint(fields=['notification', 'subscription'], name='uniq_wp_delivery_notif_sub')
        ]
        indexes = [
            models.Index(fields=['status', 'updated_at']),
            models.Index(fields=['notification', 'status']),
        ]

    def __str__(self):
        return f"Notif {self.notification_id} — Sub {self.subscription_id} — {self.status}"

from django.utils import timezone

class WebPushOperationalAlert(models.Model):
    class ScopeChoices(models.TextChoices):
        GLOBAL = 'GLOBAL', 'Global'
        BAND = 'BAND', 'Banda'

    class SeverityChoices(models.TextChoices):
        INFO = 'INFO', 'Info'
        WARNING = 'WARNING', 'Warning'
        CRITICAL = 'CRITICAL', 'Critical'

    class StatusChoices(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Ativo'
        RESOLVED = 'RESOLVED', 'Resolvido'

    scope_type = models.CharField(max_length=20, choices=ScopeChoices.choices)
    band = models.ForeignKey(Band, on_delete=models.PROTECT, null=True, blank=True, related_name='web_push_operational_alerts')
    dedupe_key = models.CharField(max_length=255, unique=True)
    code = models.CharField(max_length=100)
    severity = models.CharField(max_length=20, choices=SeverityChoices.choices)
    status = models.CharField(max_length=20, choices=StatusChoices.choices)

    title = models.CharField(max_length=255)
    message = models.TextField()
    recommended_action = models.TextField(blank=True)

    current_count = models.IntegerField(default=0)
    opened_count = models.IntegerField(default=1)

    first_detected_at = models.DateTimeField(default=timezone.now)
    last_detected_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Alerta Operacional Web Push'
        verbose_name_plural = 'Alertas Operacionais Web Push'
        constraints = [
            models.CheckConstraint(
                condition=(
                    (models.Q(scope_type='GLOBAL') & models.Q(band__isnull=True)) |
                    (models.Q(scope_type='BAND') & models.Q(band__isnull=False))
                ),
                name='wp_alert_scope_band_consistency'
            ),
            models.CheckConstraint(
                condition=models.Q(current_count__gte=0),
                name='wp_alert_current_count_gte_zero'
            ),
            models.CheckConstraint(
                condition=models.Q(opened_count__gte=1),
                name='wp_alert_opened_count_gte_one'
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(status='ACTIVE') & models.Q(resolved_at__isnull=True)) |
                    (models.Q(status='RESOLVED') & models.Q(resolved_at__isnull=False))
                ),
                name='wp_alert_status_resolved_at_consistency'
            )
        ]
        indexes = [
            models.Index(fields=['status', 'severity']),
            models.Index(fields=['band', 'status']),
        ]

    def __str__(self):
        return f"[{self.status}] {self.severity} - {self.dedupe_key}"
class WebPushOperationalAlertEmailDelivery(models.Model):
    EVENT_TYPE_CHOICES = (
        ('OPENED', 'Opened'),
        ('REOPENED', 'Reopened'),
        ('ESCALATED', 'Escalated'),
        ('RESOLVED', 'Resolved'),
    )
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('SENDING', 'Sending'),
        ('SENT', 'Sent'),
        ('TEMPORARY_FAILURE', 'Temporary Failure'),
        ('PERMANENT_FAILURE', 'Permanent Failure'),
        ('SKIPPED', 'Skipped'),
    )

    alert = models.ForeignKey(WebPushOperationalAlert, on_delete=models.PROTECT, related_name='email_deliveries')
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    event_key = models.CharField(max_length=255, unique=True)

    severity_snapshot = models.CharField(max_length=50)
    scope_type_snapshot = models.CharField(max_length=20)
    band_slug_snapshot = models.CharField(max_length=255, null=True, blank=True)
    code_snapshot = models.CharField(max_length=100)
    current_count_snapshot = models.IntegerField()
    opened_count_snapshot = models.IntegerField()

    recipient_set_hash = models.CharField(max_length=255)
    recipient_count = models.IntegerField()

    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='PENDING')
    attempt_count = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=3)

    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    last_error_code = models.CharField(max_length=100, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'web_push_operational_alert_email_delivery'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(recipient_count__gte=1),
                name='wp_alert_email_recip_gte_one'
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__gte=0),
                name='wp_alert_email_attempt_gte_zero'
            ),
            models.CheckConstraint(
                condition=models.Q(max_attempts__gte=1),
                name='wp_alert_email_max_attempts_gte_one'
            ),
            models.CheckConstraint(
                condition=models.Q(attempt_count__lte=models.F('max_attempts')),
                name='wp_alert_email_attempt_lte_max'
            ),
            models.CheckConstraint(
                condition=(
                    (models.Q(status='SENT') & models.Q(sent_at__isnull=False)) |
                    (~models.Q(status='SENT') & models.Q(sent_at__isnull=True))
                ),
                name='wp_alert_email_status_sent_at'
            )
        ]

class WebPushOperationalAlertCycleLease(models.Model):
    key = models.CharField(max_length=100, unique=True, default='web_push_operational_alert_cycle')
    owner_token = models.CharField(max_length=255)
    locked_until = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'web_push_operational_alert_cycle_lease'

class BandDashboardPendingItemQuerySet(models.QuerySet):
    def with_ordering(self):
        from django.db.models import Case, When, Value, IntegerField, F
        from django.db.models.functions import Coalesce
        from django.utils import timezone

        today = timezone.localdate()

        return self.annotate(
            effective_date=Coalesce('due_date', 'show__date')
        ).annotate(
            date_group=Case(
                When(effective_date__isnull=True, then=Value(3)),
                When(effective_date__gte=today, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            ),
            future_date=Case(
                When(effective_date__gte=today, then=F('effective_date')),
                default=None,
            ),
            past_date=Case(
                When(effective_date__lt=today, then=F('effective_date')),
                default=None,
            )
        ).order_by(
            'date_group',
            F('future_date').asc(nulls_last=True),
            F('past_date').desc(nulls_last=True),
            'show__show_time',
            'show__title',
            'pk'
        )

class BandDashboardPendingItem(models.Model):
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='dashboard_pending_items')
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name='dashboard_pending_items', null=True, blank=True)
    description = models.CharField(max_length=500)
    due_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey('User', on_delete=models.PROTECT, related_name='dashboard_pending_items_created')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BandDashboardPendingItemQuerySet.as_manager()

    class Meta:
        ordering = ['-created_at', '-pk']

    @property
    def status_info(self):
        target_date = self.due_date or (self.show.date if self.show else None)
        if not target_date:
            return {'label': 'Geral', 'class': 'bg-secondary'}

        from django.utils import timezone
        hoje = timezone.localdate()
        diff = (target_date - hoje).days

        if diff > 7:
            return {'label': 'No Prazo', 'class': 'bg-success'}
        elif 1 <= diff <= 7:
            return {'label': 'Próximo', 'class': 'bg-warning text-dark'}
        elif diff == 0:
            return {'label': 'Hoje', 'class': 'bg-primary'}
        else:
            return {'label': 'Vencido', 'class': 'bg-danger'}

    def __str__(self):
        return f'{self.show.title if self.show else "Geral"} - {self.description[:50]}'


class BandNotice(models.Model):
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='notices', verbose_name='Banda')
    message = models.TextField(verbose_name='Mensagem')
    scheduled_at = models.DateTimeField(verbose_name='Agendado para')
    sent_at = models.DateTimeField(null=True, blank=True, verbose_name='Enviado em')
    created_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_band_notices', verbose_name='Criado por')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    
    class Meta:
        verbose_name = 'Aviso da Banda'
        verbose_name_plural = 'Avisos da Banda'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sent_at', 'scheduled_at']),
        ]

    def __str__(self):
        return f'{self.band.name} - Aviso {self.id}'


class AdministrativeBandNotice(models.Model):
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='administrative_notices', null=True, blank=True, verbose_name='Banda Destino', help_text='Deixe em branco para enviar a todas as bandas (Todos).')
    created_by = models.ForeignKey('User', on_delete=models.SET_NULL, null=True, blank=True, related_name='created_administrative_notices', verbose_name='Criado por')
    message = models.TextField(verbose_name='Mensagem')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Data de Envio')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Última Atualização')

    class Meta:
        verbose_name = 'Aviso Administrativo'
        verbose_name_plural = 'Avisos Administrativos'
        ordering = ['-created_at']

    def __str__(self):
        dest = self.band.name if self.band else 'Todos os Produtores'
        return f"Aviso de {self.created_at.strftime('%d/%m/%Y')} para {dest}"

class Partner(models.Model):
    name = models.CharField(max_length=200, verbose_name='Nome do Parceiro')
    segment = models.CharField(max_length=100, verbose_name='Segmento de Atuação')
    instagram = models.CharField(max_length=200, blank=True, null=True, verbose_name='Instagram')
    phone = models.CharField(max_length=50, blank=True, null=True, verbose_name='Telefone')
    image = models.ImageField(validators=[validate_file_size_and_type], upload_to='partners/logos/', verbose_name='Logomarca ou Imagem')
    is_active = models.BooleanField(default=True, verbose_name='Ativo')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Parceiro'
        verbose_name_plural = 'Parceiros'
        ordering = ['-is_active', 'name']

    def __str__(self):
        return self.name

    @property
    def instagram_url(self):
        if not self.instagram:
            return None
        ig = self.instagram.strip()
        if not ig:
            return None

        import urllib.parse
        import re
        if ig.startswith('http://') or ig.startswith('https://'):
            parsed = urllib.parse.urlparse(ig)
            if parsed.scheme not in ['http', 'https']:
                return None
            path_parts = [p for p in parsed.path.split('/') if p]
            if path_parts:
                ig = path_parts[0]
            else:
                return None
        elif '://' in ig or (':' in ig and not ig.startswith('@')):
            # Prevent things like javascript:, ftp://, etc when not using http
            return None

        ig = ig.split('?')[0].split('#')[0]
        ig = ig.replace('@', '').replace('/', '')

        if not ig or not re.match(r'^[\w\.]+$', ig):
            return None
        return f'https://www.instagram.com/{ig}/'

    @property
    def instagram_display(self):
        if not self.instagram:
            return None
        url = self.instagram_url
        if not url:
            return None
        username = url.rstrip('/').split('/')[-1]
        return f'@{username}'

    @property
    def whatsapp_url(self):
        if not self.phone:
            return None
        import re
        num = re.sub(r'\D', '', self.phone)
        if not num:
            return None

        if len(num) in (10, 11):
            num = '55' + num

        if not num.startswith('55') or len(num) < 12:
            return None

        return f'https://wa.me/{num}'

    @property
    def formatted_phone(self):
        if not self.phone:
            return None
        import re
        num = re.sub(r'\D', '', self.phone)
        if not num:
            return self.phone

        if num.startswith('55') and len(num) in (12, 13):
            num = num[2:]

        if len(num) == 11:
            return f"({num[:2]}) {num[2:7]}-{num[7:]}"
        elif len(num) == 10:
            return f"({num[:2]}) {num[2:6]}-{num[6:]}"

        return self.phone



class SupportTicket(models.Model):
    STATUS_CHOICES = [
        ('NEW', 'Nova'),
        ('IN_PROGRESS', 'Em análise'),
        ('WAITING_PRODUCER', 'Aguardando produtor'),
        ('WAITING_ADMIN', 'Aguardando administração'),
        ('RESOLVED', 'Resolvida'),
        ('ARCHIVED', 'Arquivada'),
    ]

    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='support_tickets')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_support_tickets')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='NEW')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(auto_now_add=True)

    admin_last_read_at = models.DateTimeField(null=True, blank=True)
    producer_last_read_at = models.DateTimeField(null=True, blank=True)

    resolved_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Atendimento"
        verbose_name_plural = "Atendimentos"
        ordering = ['-last_message_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['band']),
        ]

    def __str__(self):
        return f"Ticket #{self.id} - {self.band.name} ({self.get_status_display()})"


class SupportTicketMessage(models.Model):
    SENDER_CHOICES = [
        ('ADMIN', 'Administração'),
        ('PRODUCER', 'Produtor'),
    ]

    ticket = models.ForeignKey(SupportTicket, on_delete=models.CASCADE, related_name='messages')
    author = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    body = models.TextField()
    sender_type = models.CharField(max_length=20, choices=SENDER_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Mensagem do Atendimento"
        verbose_name_plural = "Mensagens do Atendimento"
        ordering = ['created_at']

    def __str__(self):
        return f"Mensagem de {self.author} em {self.created_at}"


def support_ticket_attachment_path(instance, filename):
    import os
    from core.file_views import sanitize_filename
    safe_name = sanitize_filename(filename)
    return os.path.join('support_tickets', str(instance.message.ticket.id), safe_name)

class SupportTicketAttachment(models.Model):
    message = models.ForeignKey(SupportTicketMessage, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(validators=[validate_file_size_and_type], upload_to=support_ticket_attachment_path)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Anexo do Atendimento"
        verbose_name_plural = "Anexos do Atendimento"
        ordering = ['uploaded_at']

    def __str__(self):
        return self.original_name

class SystemSettings(models.Model):
    """
    Configurações globais do sistema Backstage Pro (Etapa 2), incluindo identidade visual.
    """
    logo = models.ImageField(validators=[validate_file_size_and_type], upload_to='system_logos/', null=True, blank=True)

    ios_installation_guide_image = models.ImageField(
        upload_to="app_install_guides/ios/",
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=['png', 'jpg', 'jpeg', 'webp']),
            validate_image_size
        ],
        verbose_name="Guia de Instalação iOS"
    )

    android_installation_guide_image = models.ImageField(
        upload_to="app_install_guides/android/",
        null=True,
        blank=True,
        validators=[
            FileExtensionValidator(allowed_extensions=['png', 'jpg', 'jpeg', 'webp']),
            validate_image_size
        ],
        verbose_name="Guia de Instalação Android"
    )

    plan_basic_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('19.90'), verbose_name="Plano Básico Mensal")
    plan_basic_annual = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('199.90'), verbose_name="Plano Básico Anual")
    plan_advanced_monthly = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('49.90'), verbose_name="Plano Avançado Mensal")
    plan_advanced_annual = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('499.90'), verbose_name="Plano Avançado Anual")

    class Meta:
        verbose_name = "Configuração do Sistema"
        verbose_name_plural = "Configurações do Sistema"

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(
            pk=1,
            defaults={
                'plan_basic_monthly': Decimal('19.90'),
                'plan_basic_annual': Decimal('199.90'),
                'plan_advanced_monthly': Decimal('49.90'),
                'plan_advanced_annual': Decimal('499.90'),
            }
        )
        return obj

    @classmethod
    def get_canonical_plan_price(cls, plan_name: str, billing_cycle: str) -> Decimal:
        """
        Retorna o preço vigente e canônico do plano a partir das configurações públicas do sistema.
        Normaliza plan_name ('BASICO' / 'AVANCADO') e billing_cycle ('MENSAL' / 'ANUAL').
        """
        settings_obj = cls.get_settings()
        p_name = (plan_name or '').strip().upper()
        c_name = (billing_cycle or '').strip().upper()

        is_basic = 'BASICO' in p_name or 'BÁSICO' in p_name
        is_annual = 'ANUAL' in c_name

        if is_basic:
            if is_annual:
                return settings_obj.plan_basic_annual or Decimal('199.90')
            return settings_obj.plan_basic_monthly or Decimal('19.90')
        else:
            if is_annual:
                return settings_obj.plan_advanced_annual or Decimal('499.90')
            return settings_obj.plan_advanced_monthly or Decimal('49.90')


class LandingPageBandLogo(models.Model):
    name = models.CharField(max_length=255, verbose_name="Nome da banda ou artista")
    image = models.ImageField(validators=[validate_file_size_and_type], upload_to='landing/band_logos/', verbose_name="Logomarca")
    display_order = models.PositiveIntegerField(default=0, verbose_name="Ordem de exibição")
    is_active = models.BooleanField(default=True, verbose_name="Ativo")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-created_at']
        verbose_name = "Logo da Landing Page"
        verbose_name_plural = "Logos da Landing Page"

    def __str__(self):
        return self.name

    def delete(self, *args, **kwargs):
        # Excluir também o arquivo físico do storage
        if self.image:
            self.image.delete(save=False)
        super().delete(*args, **kwargs)

class Integrante(models.Model):
    CATEGORY_CHOICES = [
        ('PRODUCAO', 'Produção'),
        ('MUSICO', 'Músico'),
        ('EQUIPE_TECNICA', 'Equipe Técnica'),
        ('SERVICOS', 'Serviços'),
    ]

    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='integrantes')
    name = models.CharField(max_length=255, verbose_name="Nome")
    role = models.CharField(max_length=150, verbose_name="Função")
    cpf = models.CharField(max_length=20, blank=True, null=True, verbose_name="CPF")
    vehicle = models.CharField(max_length=150, blank=True, null=True, verbose_name="Veículo")
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, verbose_name="Categoria")
    pix_key = models.CharField(max_length=255, blank=True, null=True, verbose_name="Chave-Pix")
    birth_date = models.CharField(max_length=15, blank=True, null=True, verbose_name="Data de Nascimento")
    miles_number = models.CharField(max_length=100, blank=True, null=True, verbose_name="Número Milhas")
    order = models.PositiveIntegerField(default=0, verbose_name="Ordem")
    is_active = models.BooleanField(default=True, db_index=True, verbose_name="Ativo")

    class Meta:
        ordering = ['order', 'id']
        verbose_name = "Integrante"
        verbose_name_plural = "Integrantes"

    def __str__(self):
        return f"{self.name} - {self.role} ({self.get_category_display()})"

class ShowParticipant(models.Model):
    show = models.ForeignKey('Show', on_delete=models.CASCADE, related_name='participants')
    integrante = models.ForeignKey(Integrante, on_delete=models.CASCADE, related_name='show_participations')
    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Escala de Integrante'
        verbose_name_plural = 'Escalas de Integrantes'
        ordering = ['integrante__order', 'integrante__name', 'integrante_id']
        constraints = [
            models.UniqueConstraint(fields=['show', 'integrante'], name='unique_integrante_per_show')
        ]

    def clean(self):
        super().clean()
        if self.show_id and self.integrante_id:
            if self.show.band_id != self.integrante.band_id:
                raise ValidationError({"integrante": "O integrante escalado deve pertencer à mesma banda do show."})

    def __str__(self):
        return f"{self.integrante.name} em {self.show.title}"

# ============================================================
# MÓDULO DE HOSPEDAGEM E ROOM LIST
# ============================================================

class RoomList(models.Model):
    class StatusChoices(models.TextChoices):
        RASCUNHO = 'RASCUNHO', 'Rascunho'
        PUBLICADA = 'PUBLICADA', 'Publicada'
        ARQUIVADA = 'ARQUIVADA', 'Arquivada'

    band = models.ForeignKey('Band', on_delete=models.PROTECT, related_name='room_lists')
    show = models.ForeignKey('Show', on_delete=models.PROTECT, related_name='room_lists')

    hotel_name = models.CharField(max_length=255)
    city = models.CharField(max_length=255)
    address = models.CharField(max_length=500, blank=True, null=True)
    contact = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    reservation_code = models.CharField(max_length=100, blank=True, null=True)

    check_in = models.DateTimeField(blank=True, null=True)
    check_out = models.DateTimeField(blank=True, null=True)

    notes = models.TextField(blank=True, null=True)
    observations = models.TextField(blank=True, default="", max_length=2000)
    status = models.CharField(max_length=20, choices=StatusChoices.choices, default=StatusChoices.RASCUNHO)

    published_at = models.DateTimeField(blank=True, null=True)
    published_by = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, blank=True, related_name='published_room_lists'
    )

    archived_at = models.DateTimeField(blank=True, null=True)
    archived_by = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, blank=True, related_name='archived_room_lists'
    )

    last_sent_to_hotel_at = models.DateTimeField(blank=True, null=True)
    last_sent_by = models.ForeignKey(
        'User', on_delete=models.SET_NULL, null=True, blank=True, related_name='sent_room_lists'
    )

    content_revision = models.PositiveBigIntegerField(default=1)
    last_sent_revision = models.PositiveBigIntegerField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(content_revision__gte=1),
                name='content_revision_gte_1'
            ),
            models.CheckConstraint(
                condition=models.Q(last_sent_revision__lte=models.F('content_revision')) | models.Q(last_sent_revision__isnull=True),
                name='last_sent_rev_lte_content_rev'
            ),
            models.CheckConstraint(
                condition=models.Q(last_sent_revision__isnull=True) | models.Q(last_sent_to_hotel_at__isnull=False),
                name='last_sent_rev_requires_date'
            ),
            models.CheckConstraint(
                condition=models.Q(check_in__isnull=True) | models.Q(check_out__isnull=True) | models.Q(check_out__gt=models.F('check_in')),
                name='check_out_gt_check_in'
            ),
        ]
        indexes = [
            models.Index(fields=['band', 'status']),
            models.Index(fields=['show', 'status']),
            models.Index(fields=['band', 'check_in']),
        ]

    @property
    def was_sent(self):
        return bool(self.last_sent_to_hotel_at and self.last_sent_revision)

    @property
    def needs_resend(self):
        return self.was_sent and self.content_revision > self.last_sent_revision

    @property
    def map_link(self):
        if self.show and self.show.accommodation_link:
            return self.show.accommodation_link
        return None

    def clean(self):
        super().clean()
        if self.show and self.band:
            if self.show.band != self.band:
                raise ValidationError({"band": "RoomList.band deve ser a mesma banda do Show."})

        if self.check_in and self.check_out:
            if self.check_out <= self.check_in:
                raise ValidationError({"check_out": "Check-out deve ser posterior ao check-in quando ambos existirem."})

        if self.content_revision < 1:
            raise ValidationError({"content_revision": "A revisão de conteúdo deve ser maior ou igual a 1."})

        if self.last_sent_revision is not None:
            if self.last_sent_revision > self.content_revision:
                raise ValidationError({"last_sent_revision": "A revisão enviada não pode ser maior que a revisão atual de conteúdo."})
            if self.last_sent_to_hotel_at is None:
                raise ValidationError({"last_sent_to_hotel_at": "Se last_sent_revision existir, last_sent_to_hotel_at também deve existir."})

class Room(models.Model):
    class RoomTypeChoices(models.TextChoices):
        INDIVIDUAL = 'INDIVIDUAL', 'Individual'
        CASAL = 'CASAL', 'Casal'
        DUPLO = 'DUPLO', 'Duplo'
        TRIPLO = 'TRIPLO', 'Triplo'
        QUADRUPLO = 'QUADRUPLO', 'Quádruplo'
        PERSONALIZADO = 'PERSONALIZADO', 'Personalizado'

    room_list = models.ForeignKey(RoomList, on_delete=models.CASCADE, related_name='rooms')
    number_or_name = models.CharField(max_length=100)
    type = models.CharField(max_length=20, choices=RoomTypeChoices.choices)
    capacity = models.PositiveIntegerField()
    beds_config = models.CharField(max_length=255, blank=True, null=True)
    has_ac = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['room_list', 'number_or_name'], name='unique_room_number_per_list'),
            models.CheckConstraint(condition=models.Q(capacity__gt=0), name='room_capacity_gt_0'),
        ]
        indexes = [
            models.Index(fields=['room_list', 'order']),
        ]

    def clean(self):
        super().clean()
        if self.number_or_name:
            self.number_or_name = self.number_or_name.strip()
        if self.capacity is not None and self.capacity <= 0:
            raise ValidationError({"capacity": "A capacidade do quarto deve ser maior que zero."})

class RoomListParticipant(models.Model):
    room_list = models.ForeignKey(RoomList, on_delete=models.CASCADE, related_name='participants')
    original_integrante = models.ForeignKey('Integrante', on_delete=models.SET_NULL, null=True, blank=True, related_name='room_participations')
    room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True, related_name='participants')
    needs_lodging = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    snapshot_name = models.CharField(max_length=255)
    snapshot_cpf = models.CharField(max_length=20, blank=True, null=True)
    snapshot_role = models.CharField(max_length=150, blank=True, null=True)
    snapshot_category = models.CharField(max_length=50, blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def formatted_cpf(self):
        if not self.snapshot_cpf:
            return None
        c = ''.join(filter(str.isdigit, self.snapshot_cpf))
        if len(c) == 11:
            return f"{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}"
        return self.snapshot_cpf

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['room_list', 'original_integrante'],
                condition=models.Q(original_integrante__isnull=False),
                name='unique_integrante_per_room_list'
            ),
        ]
        indexes = [
            models.Index(fields=['room_list', 'room']),
        ]

    def clean(self):
        super().clean()
        if self.original_integrante and self.room_list:
            if self.original_integrante.band != self.room_list.band:
                raise ValidationError({"original_integrante": "O integrante original deve pertencer à mesma banda da Room List."})

        if self.room and self.room_list:
            if self.room.room_list != self.room_list:
                raise ValidationError({"room": "O quarto escolhido deve pertencer à mesma Room List do participante."})


class LodgingTemplate(models.Model):
    band = models.OneToOneField('Band', on_delete=models.CASCADE, related_name='lodging_template')
    default_observations = models.TextField(blank=True, default="", max_length=2000)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class TemplateRoom(models.Model):
    template = models.ForeignKey(LodgingTemplate, on_delete=models.CASCADE, related_name='rooms')
    number_or_name = models.CharField(max_length=50, blank=True, null=True, verbose_name='Número ou Nome')
    type = models.CharField(max_length=20, choices=Room.RoomTypeChoices.choices)
    capacity = models.PositiveIntegerField()
    beds_config = models.CharField(max_length=255, blank=True, null=True)
    has_ac = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(capacity__gt=0), name='template_room_capacity_gt_0'),
        ]
        indexes = [
            models.Index(fields=['template', 'order']),
        ]

    def clean(self):
        super().clean()
        if self.capacity is not None and self.capacity <= 0:
            raise ValidationError({"capacity": "A capacidade do quarto modelo deve ser maior que zero."})

class TemplateParticipant(models.Model):
    template = models.ForeignKey(LodgingTemplate, on_delete=models.CASCADE, related_name='participants')
    room = models.ForeignKey(TemplateRoom, on_delete=models.CASCADE, related_name='participants')
    original_integrante = models.ForeignKey('Integrante', on_delete=models.CASCADE, related_name='template_participations')
    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['template', 'original_integrante'], name='unique_integrante_per_template'),
        ]

    def clean(self):
        super().clean()
        if self.original_integrante and self.template:
            if self.original_integrante.band != self.template.band:
                raise ValidationError({"original_integrante": "Integrante deve pertencer à banda do template."})

        if self.room and self.template:
            if self.room.template != self.template:
                raise ValidationError({"room": "TemplateRoom deve pertencer ao mesmo LodgingTemplate."})


class Expense(models.Model):
    STATUS_CHOICES = (
        ('PENDENTE', 'Pendente'),
        ('PAGO', 'Pago'),
        ('VENCIDO', 'Vencido'),
        ('CANCELADO', 'Cancelado'),
    )
    CYCLE_CHOICES = (
        ('MENSAL', 'Mensal'),
        ('TRIMESTRAL', 'Trimestral'),
        ('SEMESTRAL', 'Semestral'),
        ('ANUAL', 'Anual'),
    )

    description = models.CharField(max_length=200, verbose_name='Descrição')
    provider = models.CharField(max_length=200, blank=True, null=True, verbose_name='Fornecedor / Beneficiário')
    category = models.CharField(max_length=100, verbose_name='Categoria')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor')
    competence_date = models.DateField(verbose_name='Data de Competência')
    due_date = models.DateField(verbose_name='Data de Vencimento')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE', verbose_name='Status')
    paid_date = models.DateField(blank=True, null=True, verbose_name='Data do Pagamento')
    payment_method = models.CharField(max_length=50, blank=True, null=True, verbose_name='Método de Pagamento')
    internal_notes = models.TextField(blank=True, null=True, verbose_name='Observações Internas')
    proof_file = models.FileField(validators=[validate_file_size_and_type], upload_to='expenses_proofs/', blank=True, null=True, verbose_name='Comprovante')
    
    is_recurring = models.BooleanField(default=False, verbose_name='Despesa Recorrente?')
    recurrence_cycle = models.CharField(max_length=20, choices=CYCLE_CHOICES, blank=True, null=True, verbose_name='Ciclo da Recorrência')
    recurrence_end_date = models.DateField(blank=True, null=True, verbose_name='Data Final da Recorrência')
    parent_expense = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='child_expenses', verbose_name='Despesa de Origem')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Despesa Administrativa'
        verbose_name_plural = 'Despesas Administrativas'
        ordering = ['-due_date', '-created_at']

    def __str__(self):
        return f"{self.description} - R$ {self.amount}"


class SignupOrder(models.Model):
    """
    Registro prévio de intenção de contratação / pedido antes do checkout e provisionamento da Band.
    Garante que a Band não seja usada como carrinho/pedido temporário.
    """
    STATUS_CHOICES = (
        ('PENDENTE', 'Pendente'),
        ('PAGO', 'Pago / Aprovado'),
        ('CANCELADO', 'Cancelado'),
        ('FALHOU', 'Falhou'),
        ('EXPIRADO', 'Expirado'),
    )
    PLAN_CHOICES = (
        ('BASICO', 'Básico'),
        ('AVANCADO', 'Avançado'),
    )
    CYCLE_CHOICES = (
        ('MENSAL', 'Mensal'),
        ('ANUAL', 'Anual'),
    )

    external_reference = models.CharField(max_length=64, unique=True, db_index=True, verbose_name='Referência Externa Única')
    gateway_provider = models.CharField(max_length=30, default='ASAAS', verbose_name='Provedor de Gateway')
    gateway_checkout_id = models.CharField(max_length=100, blank=True, null=True, db_index=True, verbose_name='ID do Checkout no Gateway')
    gateway_customer_id = models.CharField(max_length=100, blank=True, null=True, db_index=True, verbose_name='ID do Cliente no Gateway')
    gateway_subscription_id = models.CharField(max_length=100, blank=True, null=True, db_index=True, verbose_name='ID da Assinatura no Gateway')

    band_name = models.CharField(max_length=150, verbose_name='Nome da Banda / Artista')
    responsible_name = models.CharField(max_length=200, verbose_name='Nome do Responsável')
    cpf_cnpj = models.CharField(max_length=30, blank=True, null=True, verbose_name='CPF ou CNPJ')
    email = models.EmailField(verbose_name='E-mail do Responsável')
    phone = models.CharField(max_length=30, blank=True, null=True, verbose_name='Telefone / WhatsApp')
    postal_code = models.CharField(max_length=15, blank=True, null=True, verbose_name='CEP')
    address = models.CharField(max_length=255, blank=True, null=True, verbose_name='Endereço / Logradouro')
    address_number = models.CharField(max_length=30, blank=True, null=True, verbose_name='Número')
    complement = models.CharField(max_length=100, blank=True, null=True, verbose_name='Complemento')
    province = models.CharField(max_length=100, blank=True, null=True, verbose_name='Bairro')
    city = models.CharField(max_length=100, blank=True, null=True, verbose_name='Cidade')
    state = models.CharField(max_length=2, blank=True, null=True, verbose_name='Estado / UF')

    plan_type = models.CharField(max_length=20, choices=PLAN_CHOICES, default='AVANCADO', verbose_name='Plano Escolhido')
    billing_cycle = models.CharField(max_length=20, choices=CYCLE_CHOICES, default='MENSAL', verbose_name='Ciclo de Cobrança')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor da Contratação')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE', db_index=True, verbose_name='Status do Pedido')

    band = models.OneToOneField(Band, on_delete=models.SET_NULL, null=True, blank=True, related_name='signup_order', verbose_name='Banda Provisionada')
    provisioned_at = models.DateTimeField(null=True, blank=True, verbose_name='Data do Provisionamento')

    activated_user = models.OneToOneField(
        'User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activated_signup_order',
        verbose_name='Usuário Inicial Ativado'
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    class Meta:
        verbose_name = 'Pedido de Contratação'
        verbose_name_plural = 'Pedidos de Contratação'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['gateway_provider', 'gateway_checkout_id'],
                condition=models.Q(gateway_checkout_id__isnull=False) & ~models.Q(gateway_checkout_id=''),
                name='unique_signup_order_checkout_per_gateway_provider'
            )
        ]

    def __str__(self):
        return f"Pedido {self.external_reference} - {self.band_name} ({self.get_status_display()})"


class PaymentWebhookEvent(models.Model):
    """
    Tabela de eventos recebidos por webhooks com proteção de idempotência em nível 1.
    Nunca armazena segredos, tokens ou dados sensíveis de cartão.
    """
    provider = models.CharField(max_length=30, default='ASAAS', verbose_name='Provedor')
    gateway_event_id = models.CharField(max_length=150, unique=True, db_index=True, verbose_name='ID do Evento no Gateway')
    event_type = models.CharField(max_length=100, db_index=True, verbose_name='Tipo de Evento')
    payload = models.JSONField(verbose_name='Payload Seguro do Evento')
    processed = models.BooleanField(default=False, db_index=True, verbose_name='Processado?')
    processed_at = models.DateTimeField(null=True, blank=True, verbose_name='Data de Processamento')
    error_message = models.TextField(blank=True, null=True, verbose_name='Mensagem de Erro')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Recebido em')

    class Meta:
        verbose_name = 'Evento de Webhook'
        verbose_name_plural = 'Eventos de Webhook'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.provider}] {self.event_type} - {self.gateway_event_id} (Processado: {self.processed})"


class BandActivationToken(models.Model):
    """
    Token criptográfico de uso único para primeiro acesso e criação de conta do comprador da banda.
    O token em texto puro NUNCA é salvo no banco, apenas seu SHA-256 hash.
    """
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='activation_tokens', verbose_name='Banda')
    signup_order = models.ForeignKey(SignupOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name='activation_tokens', verbose_name='Pedido de Origem')
    email = models.EmailField(verbose_name='E-mail do Destinatário')
    responsible_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='Nome do Responsável')
    token_hash = models.CharField(max_length=64, unique=True, db_index=True, verbose_name='Hash SHA-256 do Token')
    encrypted_token = models.TextField(blank=True, null=True, verbose_name='Token Criptografado (Fernet)')
    expires_at = models.DateTimeField(verbose_name='Expira em')
    used_at = models.DateTimeField(null=True, blank=True, verbose_name='Utilizado em')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')

    class Meta:
        verbose_name = 'Token de Ativação'
        verbose_name_plural = 'Tokens de Ativação'
        ordering = ['-created_at']

    def is_valid(self):
        from django.utils import timezone
        if self.used_at is not None:
            return False
        return timezone.now() <= self.expires_at

    def __str__(self):
        return f"Ativação para {self.band.name} ({self.email}) - Válido: {self.is_valid()}"


class GatewayPaymentMethod(models.Model):
    """
    Armazenamento desacoplado e seguro do meio de pagamento tokenizado (cartão de crédito).
    O token de pagamento NUNCA é armazenado em texto plano — é cifrado com Fernet em repouso.
    Garante que nunca sejam armazenados PAN completo, CVV ou dados brutos não autorizados pelo PCI-DSS.
    """
    subscription = models.ForeignKey(
        'BandSubscription',
        on_delete=models.CASCADE,
        related_name='payment_methods',
        verbose_name='Assinatura Proprietária'
    )
    gateway_provider = models.CharField(
        max_length=30,
        default='ASAAS',
        verbose_name='Provedor do Gateway'
    )
    gateway_customer_id = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name='ID do Cliente no Gateway'
    )
    encrypted_token = models.TextField(
        verbose_name='Token Criptografado (Fernet)'
    )
    card_brand = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='Bandeira do Cartão'
    )
    card_last4 = models.CharField(
        max_length=4,
        blank=True,
        null=True,
        verbose_name='Últimos 4 Dígitos'
    )
    expiration_month = models.CharField(
        max_length=2,
        blank=True,
        null=True,
        verbose_name='Mês de Expiração'
    )
    expiration_year = models.CharField(
        max_length=4,
        blank=True,
        null=True,
        verbose_name='Ano de Expiração'
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name='Método Ativo?'
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    class Meta:
        verbose_name = 'Método de Pagamento Gateway'
        verbose_name_plural = 'Métodos de Pagamento Gateway'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['subscription', 'gateway_provider'],
                condition=models.Q(is_active=True),
                name='unique_active_payment_method_per_subscription_and_provider'
            )
        ]

    def __str__(self):
        brand = self.card_brand or 'Cartão'
        last4 = f"•••• {self.card_last4}" if self.card_last4 else ""
        status = "Ativo" if self.is_active else "Inativo"
        return f"{brand} {last4} ({self.gateway_provider}) - {status}"

    def get_decrypted_token(self) -> str:
        """
        Descriptografa e retorna o token de pagamento em texto plano.
        Utilizado estritamente em memória durante a execução de operações financeiras.
        """
        from core.services.payments.security import decrypt_payment_token
        return decrypt_payment_token(self.encrypted_token)

    def set_token(self, plain_token: str):
        """
        Criptografa o token recebido e persiste em encrypted_token.
        """
        from core.services.payments.security import encrypt_payment_token
        self.encrypted_token = encrypt_payment_token(plain_token)


class AnnualPlanPurchase(models.Model):
    """
    Representa formalmente cada compra/contratação anual (ciclo de 12 meses),
    seja ela a compra inicial ou uma futura renovação anual automática/manual.
    Preserva o histórico imutável de parcelamento, valores e vigência contratada.
    """
    class PurchaseType(models.TextChoices):
        INITIAL = 'INITIAL', 'Compra Inicial'
        RENEWAL = 'RENEWAL', 'Renovação Anual'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendente'
        CONFIRMED = 'CONFIRMED', 'Aprovada / Confirmada'
        CANCELED = 'CANCELED', 'Cancelada'

    band_subscription = models.ForeignKey(
        'BandSubscription',
        on_delete=models.CASCADE,
        related_name='annual_purchases',
        verbose_name='Assinatura da Banda'
    )
    signup_order = models.ForeignKey(
        'SignupOrder',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='annual_purchases',
        verbose_name='Pedido de Origem (se compra inicial)'
    )
    purchase_type = models.CharField(
        max_length=20,
        choices=PurchaseType.choices,
        default=PurchaseType.INITIAL,
        verbose_name='Tipo da Compra'
    )
    gateway_provider = models.CharField(
        max_length=30,
        default='ASAAS',
        verbose_name='Provedor do Gateway'
    )
    gateway_external_reference = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name='Referência Externa no Gateway'
    )
    gateway_installment_id = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name='ID do Parcelamento (Installment) no Gateway'
    )
    installment_count = models.PositiveIntegerField(
        default=1,
        verbose_name='Quantidade de Parcelas Escolhida'
    )
    gross_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Valor Bruto Total (ex: 199.90)'
    )
    net_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name='Valor Líquido Recebido no Gateway'
    )
    coverage_start = models.DateField(
        verbose_name='Início da Vigência (12 meses)'
    )
    coverage_end = models.DateField(
        verbose_name='Fim da Vigência (12 meses)'
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Data de Aprovação Financeira'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.CONFIRMED,
        db_index=True,
        verbose_name='Status da Compra Anual'
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    class Meta:
        verbose_name = 'Compra de Plano Anual'
        verbose_name_plural = 'Compras de Planos Anuais'
        ordering = ['-coverage_start', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['gateway_provider', 'gateway_installment_id'],
                condition=models.Q(gateway_installment_id__isnull=False) & ~models.Q(gateway_installment_id=''),
                name='unique_installment_per_gateway_provider'
            ),
            models.UniqueConstraint(
                fields=['gateway_provider', 'gateway_external_reference'],
                condition=models.Q(gateway_external_reference__isnull=False) & ~models.Q(gateway_external_reference=''),
                name='unique_annual_purchase_external_ref'
            ),
        ]

    def __str__(self):
        band_name = self.band_subscription.band.name if self.band_subscription and self.band_subscription.band else 'Banda'
        return f"Compra Anual {self.get_purchase_type_display()} - {band_name} ({self.installment_count}x R$ {self.gross_amount}) - {self.get_status_display()}"


class AnnualRenewalNotice(models.Model):
    """
    Registra o envio do aviso pré-renovação de 30 dias para contratos anuais.
    Congela o renewal_price_notified para proteger o cliente contra aumentos posteriores.
    """
    class NoticeType(models.TextChoices):
        STANDARD = 'STANDARD', 'Aviso Padrão (Sem alteração)'
        PRICE_CHANGE = 'PRICE_CHANGE', 'Aviso de Atualização de Valor'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendente'
        SENT = 'SENT', 'Enviado com Sucesso'
        FAILED = 'FAILED', 'Falha no Envio'
        SKIPPED = 'SKIPPED', 'Ignorado / Não Entregue'

    band_subscription = models.ForeignKey(
        'BandSubscription',
        on_delete=models.CASCADE,
        related_name='renewal_notices',
        verbose_name='Assinatura'
    )
    renewal_date = models.DateField(
        verbose_name='Data Prevista da Renovação'
    )
    plan_name = models.CharField(
        max_length=100,
        verbose_name='Nome do Plano'
    )
    billing_cycle = models.CharField(
        max_length=20,
        default='ANUAL',
        verbose_name='Ciclo de Cobrança'
    )
    current_contracted_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Valor Contratado Atual'
    )
    notified_renewal_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        verbose_name='Preço Notificado para Renovação'
    )
    installment_count = models.PositiveIntegerField(
        default=1,
        verbose_name='Parcelamento Previsto'
    )
    notice_type = models.CharField(
        max_length=20,
        choices=NoticeType.choices,
        default=NoticeType.STANDARD,
        verbose_name='Tipo de Aviso'
    )
    email_recipient = models.EmailField(
        blank=True,
        null=True,
        verbose_name='E-mail Destinatário'
    )
    scheduled_for = models.DateField(
        verbose_name='Agendado Para (D-30)'
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Data de Envio Efetivo'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name='Status do Aviso'
    )
    error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name='Mensagem de Erro (Sanitizada)'
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado em')

    class Meta:
        verbose_name = 'Aviso de Renovação Anual'
        verbose_name_plural = 'Avisos de Renovação Anual'
        ordering = ['-renewal_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['band_subscription', 'renewal_date'],
                name='unique_annual_renewal_notice_per_cycle'
            )
        ]

    def __str__(self):
        band_name = self.band_subscription.band.name if self.band_subscription and self.band_subscription.band else 'Banda'
        return f"Aviso Renovação {self.get_notice_type_display()} - {band_name} ({self.renewal_date}) - {self.get_status_display()}"


class EmailDelivery(models.Model):
    """
    Fila transacional persistente para entrega assíncrona de e-mails de negócio.
    Garante desacoplamento total entre regras de negócio financeiras e a entrega SMTP do Gmail.
    """
    class EmailType(models.TextChoices):
        SYSTEM_TEST = 'SYSTEM_TEST', 'Teste de Sistema'
        ACCOUNT_ACTIVATION = 'ACCOUNT_ACTIVATION', 'Ativação de Conta'
        ANNUAL_RENEWAL_NOTICE = 'ANNUAL_RENEWAL_NOTICE', 'Aviso Pré-Renovação Anual'
        ANNUAL_RENEWAL_SUCCESS = 'ANNUAL_RENEWAL_SUCCESS', 'Renovação Anual Confirmada'
        PAYMENT_OVERDUE = 'PAYMENT_OVERDUE', 'Aviso de Pagamento em Atraso'
        SUBSCRIPTION_SUSPENDED = 'SUBSCRIPTION_SUSPENDED', 'Assinatura Suspensa'
        SUBSCRIPTION_CANCELLATION_SCHEDULED = 'SUBSCRIPTION_CANCELLATION_SCHEDULED', 'Cancelamento Agendado'
        CREDIT_CARD_CAPTURE_REFUSED = 'CREDIT_CARD_CAPTURE_REFUSED', 'Recusa de Captura do Cartão'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendente'
        PROCESSING = 'PROCESSING', 'Em Processamento'
        RETRY = 'RETRY', 'Aguardando Nova Tentativa'
        SENT = 'SENT', 'Enviado com Sucesso'
        FAILED = 'FAILED', 'Falha Definitiva'

    email_type = models.CharField(
        max_length=50,
        choices=EmailType.choices,
        db_index=True,
        verbose_name='Tipo de E-mail'
    )
    recipient_email = models.EmailField(
        verbose_name='E-mail do Destinatário'
    )
    subject = models.CharField(
        max_length=255,
        verbose_name='Assunto do E-mail'
    )
    template_name = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name='Template Base'
    )
    context_data = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='Contexto Sanitizado (JSON)'
    )
    related_object_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='Tipo do Objeto Relacionado'
    )
    related_object_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='ID do Objeto Relacionado'
    )
    idempotency_key = models.CharField(
        max_length=200,
        unique=True,
        db_index=True,
        verbose_name='Chave de Idempotência'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        verbose_name='Status da Entrega'
    )
    attempt_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Quantidade de Tentativas'
    )
    max_attempts = models.PositiveIntegerField(
        default=6,
        verbose_name='Máximo de Tentativas'
    )
    next_attempt_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name='Próxima Tentativa Em'
    )
    sending_started_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Início do Processamento'
    )
    sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Enviado Em'
    )
    last_error_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='Último Código de Erro (Sanitizado)'
    )
    last_error_message = models.TextField(
        blank=True,
        null=True,
        verbose_name='Última Mensagem de Erro (Sanitizada)'
    )
    message_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name='Message-ID SMTP Determinístico'
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Criado Em')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Atualizado Em')

    class Meta:
        verbose_name = 'Entrega de E-mail'
        verbose_name_plural = 'Entregas de E-mail'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_email_type_display()}] -> {self.recipient_email} ({self.get_status_display()})"


class ScheduledJobRun(models.Model):
    """
    Registro de observabilidade e auditoria para execuções de rotinas agendadas (Cron Jobs Railway).
    NUNCA armazena dados de cartão, tokens ou segredos de clientes.
    """
    class Status(models.TextChoices):
        RUNNING = 'RUNNING', 'Em Execução'
        SUCCESS = 'SUCCESS', 'Sucesso'
        PARTIAL = 'PARTIAL', 'Parcialmente Concluído'
        FAILED = 'FAILED', 'Falha'
        SKIPPED_LOCKED = 'SKIPPED_LOCKED', 'Ignorado (Lock Ativo)'

    job_name = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name='Nome do Job'
    )
    started_at = models.DateTimeField(
        default=timezone.now,
        verbose_name='Iniciado Em'
    )
    finished_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Finalizado Em'
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
        db_index=True,
        verbose_name='Status da Execução'
    )
    processed_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Registros Processados'
    )
    success_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Sucessos'
    )
    skipped_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Ignorados'
    )
    failed_count = models.PositiveIntegerField(
        default=0,
        verbose_name='Falhas'
    )
    error_summary = models.TextField(
        blank=True,
        null=True,
        verbose_name='Resumo de Erros (Sanitizado)'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Criado Em'
    )

    class Meta:
        verbose_name = 'Execução de Job Agendado'
        verbose_name_plural = 'Execuções de Jobs Agendados'
        ordering = ['-started_at']

    def __str__(self):
        return f"[{self.job_name}] {self.started_at.strftime('%Y-%m-%d %H:%M:%S')} - {self.get_status_display()} ({self.processed_count} processados)"



# ============================================================
# AUTOMATIC FILE DELETION ON RECORD DELETE
# ============================================================
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.db.models import FileField
import os

@receiver(post_delete)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Deletes file from filesystem when corresponding object is deleted.
    Applies to all models in the 'core' app with FileField (or ImageField).
    """
    if getattr(sender._meta, 'app_label', None) != 'core':
        return
        
    for field in sender._meta.fields:
        if isinstance(field, FileField):
            file_field = getattr(instance, field.name, None)
            if file_field and hasattr(file_field, 'path'):
                try:
                    if os.path.isfile(file_field.path):
                        os.remove(file_field.path)
                except Exception:
                    pass
