from django.db import models
from django.contrib.auth.models import AbstractUser
from django.conf import settings

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
    email = models.EmailField(unique=True, blank=False, null=False, verbose_name='E-mail')

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

    class Meta:
        verbose_name = 'Show'
        verbose_name_plural = 'Shows'
        ordering = ['date', 'show_time']

    def __str__(self):
        if self.date:
            return f"{self.date.strftime('%d/%m/%Y')} - {self.title} ({self.city})"
        return f"Sem data - {self.title} ({self.city})"

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

