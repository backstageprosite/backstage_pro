from django.db import models
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
    name = models.CharField(max_length=100, verbose_name="Nome da Banda")
    slug = models.SlugField(max_length=100, unique=True, verbose_name="Slug (URL)")
    logo = models.ImageField(upload_to='bands/logos/', blank=True, null=True, verbose_name="Logo da Banda")

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

    def __str__(self):
        return self.name

class User(AbstractUser):
    """
    Modelo customizado de usuário para diferenciar Produtores e Integrantes.
    """
    ROLE_CHOICES = (
        ('PRODUTOR', 'Produtor'),
        ('INTEGRANTE', 'Integrante'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='INTEGRANTE', verbose_name='Perfil')
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='users', null=True, blank=True, verbose_name="Banda")
    email = models.EmailField(unique=False, blank=True, null=True, verbose_name='E-mail')

    def is_produtor(self):
        return self.role == 'PRODUTOR' or self.is_superuser

    class Meta:
        verbose_name = "Usuário"
        verbose_name_plural = "Usuários"

class Show(models.Model):
    STATUS_CHOICES = (
        ('PRE_RESERVADO', 'Reserva'),
        ('CONFIRMADO', 'Confirmado'),
        ('CANCELADO', 'Cancelado'),
    )

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
    accommodation = models.TextField(blank=True, null=True, verbose_name='Hospedagem')
    accommodation_link = models.URLField(max_length=500, blank=True, null=True, verbose_name='Link de Localização da Hospedagem')
    accommodation_contact = models.CharField(max_length=100, blank=True, null=True, verbose_name='Contato (Hospedagem)')
    checkout_time = models.TimeField(blank=True, null=True, verbose_name='Saída Hospedagem')
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

def contract_upload_path(instance, filename):
    return f'shows/{instance.id}/documentos/{filename}'

def receipt_upload_path(instance, filename):
    # Salva o arquivo na pasta media/shows/ID_DO_SHOW/comprovantes/nome_do_arquivo
    return f'shows/{instance.show.id}/comprovantes/{filename}'

class ContractDocument(models.Model):
    show = models.ForeignKey(Show, on_delete=models.CASCADE, related_name='documents')
    description = models.CharField(max_length=200, verbose_name='Descrição do Documento')
    file = models.FileField(upload_to=contract_upload_path, verbose_name='Arquivo / Documento')
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
    file = models.FileField(upload_to=receipt_upload_path, verbose_name='Arquivo / Comprovante')
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
    file = models.FileField(upload_to=payment_upload_path, blank=True, null=True, verbose_name='Arquivo / Comprovante')
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
        ('FORNECEDOR', 'Fornecedor (a)'),
        ('CONTRATANTE', 'Contratante'),
        ('ESTABELECIMENTO', 'Estabelecimento'),
        ('RESTAURANTE', 'Restaurante'),
        ('HOSPEDAGEM', 'Hospedagem'),
        ('PRODUTOR', 'Produtor (a)'),
    )

    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='contacts', verbose_name='Banda')
    name = models.CharField(max_length=200, verbose_name='Nome')
    contact_type = models.CharField(max_length=50, choices=CONTACT_TYPE_CHOICES, default='FORNECEDOR', verbose_name='Tipo')
    phone = models.CharField(max_length=200, blank=True, null=True, verbose_name='Contato (Telefone)')
    email = models.EmailField(max_length=254, blank=True, null=True, verbose_name='E-mail')
    location = models.CharField(max_length=255, blank=True, null=True, verbose_name='Local')
    link = models.URLField(max_length=500, blank=True, null=True, verbose_name='Link')
    notes = models.TextField(blank=True, null=True, verbose_name='Observações')

    class Meta:
        verbose_name = 'Contato (Banco de Dados)'
        verbose_name_plural = 'Banco de Dados'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} - {self.get_contact_type_display()}"

class BandSubscription(models.Model):
    CYCLE_CHOICES = (
        ('MENSAL', 'Mensal'),
        ('SEMESTRAL', 'Semestral'),
        ('ANUAL', 'Anual'),
        ('PERSONALIZADO', 'Personalizado'),
    )
    STATUS_CHOICES = (
        ('ATIVO', 'Ativo'),
        ('VENCENDO', 'Vencendo'),
        ('VENCIDO', 'Vencido'),
        ('SUSPENSO', 'Suspenso'),
        ('TESTE', 'Teste'),
        ('CANCELADO', 'Cancelado'),
    )
    PAYMENT_METHOD_CHOICES = (
        ('PIX', 'Pix'),
        ('BOLETO', 'Boleto'),
        ('CARTAO', 'Cartão'),
        ('TRANSFERENCIA', 'Transferência'),
        ('DINHEIRO', 'Dinheiro'),
        ('OUTRO', 'Outro'),
    )

    band = models.OneToOneField(Band, on_delete=models.CASCADE, related_name='subscription', verbose_name='Banda')
    plan_name = models.CharField(max_length=100, default='Mensal', verbose_name='Nome do Plano')
    billing_cycle = models.CharField(max_length=20, choices=CYCLE_CHOICES, default='MENSAL', verbose_name='Ciclo de Cobrança')
    contracted_value = models.DecimalField(max_digits=10, decimal_places=2, default=300.00, verbose_name='Valor Contratado')
    start_date = models.DateField(blank=True, null=True, verbose_name='Data de Início')
    next_due_date = models.DateField(blank=True, null=True, verbose_name='Próximo Vencimento')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='TESTE', verbose_name='Status da Assinatura')
    payment_method_preference = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, default='PIX', verbose_name='Preferência de Pagamento')

    financial_responsible_name = models.CharField(max_length=200, blank=True, null=True, verbose_name='Responsável Financeiro')
    billing_phone = models.CharField(max_length=30, blank=True, null=True, verbose_name='Telefone de Cobrança (WhatsApp)')
    billing_email = models.EmailField(blank=True, null=True, verbose_name='E-mail de Cobrança')
    internal_notes = models.TextField(blank=True, null=True, verbose_name='Observações Internas')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Assinatura SaaS'
        verbose_name_plural = 'Assinaturas SaaS'

    def __str__(self):
        return f"Assinatura - {self.band.name}"

def billing_proof_upload_path(instance, filename):
    return f'billing/{instance.band.id}/comprovantes/{filename}'

def rider_upload_path(instance, filename):
    return f'bands/{instance.band.slug}/riders/{filename}'

class RiderDocument(models.Model):
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='riders', verbose_name='Banda')
    name = models.CharField(max_length=200, verbose_name='Nome')
    file = models.FileField(upload_to=rider_upload_path, verbose_name='Arquivo')
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
        ('ATRASADO', 'Atrasado'),
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
    band = models.ForeignKey(Band, on_delete=models.CASCADE, related_name='billing_records', verbose_name='Banda')
    reference_period = models.CharField(max_length=100, verbose_name='Período de Referência (Ex: Agosto/2026)')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor Cobrado')
    due_date = models.DateField(verbose_name='Vencimento da Fatura')
    paid_date = models.DateField(blank=True, null=True, verbose_name='Data do Pagamento')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDENTE', verbose_name='Status')
    payment_method = models.CharField(max_length=50, choices=PAYMENT_METHOD_CHOICES, blank=True, null=True, verbose_name='Forma de Pagamento')
    proof_file = models.FileField(upload_to=billing_proof_upload_path, blank=True, null=True, verbose_name='Comprovante')
    notes = models.TextField(blank=True, null=True, verbose_name='Observações')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_billings', verbose_name='Criado por')

    class Meta:
        verbose_name = 'Fatura SaaS'
        verbose_name_plural = 'Faturas SaaS'
        ordering = ['-due_date', '-created_at']

    def __str__(self):
        return f"{self.band.name} - {self.reference_period} ({self.get_status_display()})"

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
    image = models.ImageField(upload_to='partners/logos/', verbose_name='Logomarca ou Imagem')
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
    file = models.FileField(upload_to=support_ticket_attachment_path)
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
    logo = models.ImageField(upload_to='system_logos/', null=True, blank=True)

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

    class Meta:
        verbose_name = "Configuração do Sistema"
        verbose_name_plural = "Configurações do Sistema"

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj


class LandingPageBandLogo(models.Model):
    name = models.CharField(max_length=255, verbose_name="Nome da banda ou artista")
    image = models.ImageField(upload_to='landing/band_logos/', verbose_name="Logomarca")
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

    class Meta:
        ordering = ['order', 'id']
        verbose_name = "Integrante"
        verbose_name_plural = "Integrantes"

    def __str__(self):
        return f"{self.name} - {self.role} ({self.get_category_display()})"

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

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class TemplateRoom(models.Model):
    template = models.ForeignKey(LodgingTemplate, on_delete=models.CASCADE, related_name='rooms')
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

