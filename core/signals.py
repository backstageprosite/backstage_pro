from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from .models import Show, User

# Store the old show object in the instance itself during pre_save
@receiver(pre_save, sender=Show)
def capture_old_show_state(sender, instance, **kwargs):
    if instance.pk:
        try:
            instance._old_show = Show.objects.get(pk=instance.pk)
        except Show.DoesNotExist:
            instance._old_show = None
    else:
        instance._old_show = None

@receiver(post_save, sender=Show)
def send_show_notification(sender, instance, created, **kwargs):
    if not instance.band:
        return
        
    action = None
    changes_text = ""
    
    if created:
        action = "Novo Show Agendado"
        changes_text = "Um novo show foi adicionado à agenda."
    else:
        old_show = getattr(instance, '_old_show', None)
        if not old_show:
            return
            
        if old_show.status != 'CANCELADO' and instance.status == 'CANCELADO':
            action = "Show Cancelado"
            changes_text = "Atenção: O status deste show mudou para CANCELADO."
        else:
            changed_fields = []
            if old_show.date != instance.date:
                changed_fields.append(f"Data")
            if old_show.show_time != instance.show_time:
                changed_fields.append(f"Horário do Show")
            if old_show.departure_time != instance.departure_time:
                changed_fields.append(f"Horário de Saída")
            if old_show.venue != instance.venue or old_show.city != instance.city:
                changed_fields.append(f"Local/Cidade")
                
            if changed_fields:
                action = "Atualização de Logística/Horário"
                changes_text = "Houve mudanças nos seguintes itens: " + ", ".join(changed_fields) + "."
    
    if action:
        # Filtra os emails válidos da banda
        recipients = User.objects.filter(band=instance.band).exclude(email='').values_list('email', flat=True)
        if not recipients:
            return
            
        city_str = instance.city or 'a definir'
        subject = f"📅 [{instance.band.name}] Atualização na Agenda"
        
        event_name = instance.event_name or instance.title or 'Evento'
        date_str = instance.date.strftime('%d/%m/%Y') if instance.date else 'A definir'
        departure_str = instance.departure_time.strftime('%H:%M') if instance.departure_time else 'A definir'
        
        message = f"""Olá,

A produção da banda {instance.band.name} atualizou a agenda!

Resumo: {action} - {changes_text}

🎸 Evento: {event_name}
📍 Local: {city_str}
🗓️ Data: {date_str}
⏰ Horário de Saída: {departure_str}

Para ver o cronograma completo (passagem de som, endereço e mapa), acesse o painel da banda: https://backstagepro.com.br/{instance.band.slug}/

Este é um e-mail automático. Produção {instance.band.name}"""

        from_address = getattr(settings, 'EMAIL_HOST_USER', 'no-reply@backstagepro.site')
        # Algumas configurações exigem que o from seja só o e-mail se não estiver validado, mas vamos tentar o formato "Nome <email>"
        from_email_formatted = f'Produção {instance.band.name} <{from_address}>'

        send_mail(
            subject=subject,
            message=message,
            from_email=from_email_formatted,
            recipient_list=list(recipients),
            fail_silently=True,
        )
