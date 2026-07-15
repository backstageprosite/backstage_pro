import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Band, BandSubscription, BillingRecord
from django.db.models import Count

class Command(BaseCommand):
    help = 'Gera um relatório de verificação financeira (Modo DRY-RUN)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=7,
            help='Janela de vencimento em dias (padrão: 7)',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Aplica as mudanças de status seguras no banco de dados',
        )

    def handle(self, *args, **options):
        days = options['days']
        apply_mode = options['apply']
        mode_text = "APPLY (Mudanças serão aplicadas)" if apply_mode else "DRY-RUN (Nenhum dado será alterado)"
        tag = "[APPLY]" if apply_mode else "[DRY-RUN]"

        today = timezone.now().date()
        window_end = today + datetime.timedelta(days=days)

        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write(self.style.SUCCESS("BACKSTAGE PRO — VERIFICAÇÃO FINANCEIRA"))
        self.stdout.write(self.style.SUCCESS(f"Modo: {mode_text}"))
        self.stdout.write(self.style.SUCCESS(f"Data da análise: {today.strftime('%d/%m/%Y')}"))
        self.stdout.write(self.style.SUCCESS(f"Janela de vencimento: {days} dias (Até {window_end.strftime('%d/%m/%Y')})"))
        if apply_mode:
            self.stdout.write(self.style.WARNING("ATENÇÃO: MODO APPLY ATIVADO"))
            self.stdout.write(self.style.WARNING("O comando irá atualizar status financeiros."))
            self.stdout.write(self.style.WARNING("Nenhuma fatura será criada."))
            self.stdout.write(self.style.WARNING("Nenhuma banda será bloqueada."))
            self.stdout.write(self.style.WARNING("Nenhum WhatsApp/e-mail será enviado."))
        self.stdout.write(self.style.SUCCESS("=" * 60))
        self.stdout.write("")

        # A. Assinaturas vencidas (next_due_date < hoje, status em ATIVO, VENCENDO, TESTE)
        subs_vencidas = BandSubscription.objects.filter(
            next_due_date__lt=today,
            status__in=['ATIVO', 'VENCENDO', 'TESTE']
        ).select_related('band')

        # B. Assinaturas vencendo nos próximos X dias (next_due_date >= hoje e <= window_end, status em ATIVO, TESTE)
        subs_vencendo = BandSubscription.objects.filter(
            next_due_date__gte=today,
            next_due_date__lte=window_end,
            status__in=['ATIVO', 'TESTE']
        ).select_related('band')

        # C. Faturas pendentes vencidas (status=PENDENTE, due_date < hoje)
        faturas_vencidas = BillingRecord.objects.filter(
            status='PENDENTE',
            due_date__lt=today
        ).select_related('band')

        # D. Faturas pendentes vencendo nos próximos X dias (status=PENDENTE, due_date >= hoje e <= window_end)
        faturas_vencendo = BillingRecord.objects.filter(
            status='PENDENTE',
            due_date__gte=today,
            due_date__lte=window_end
        ).select_related('band')

        # E. Bandas sem assinatura (ativas sem BandSubscription)
        bandas_sem_assinatura = Band.objects.filter(is_active=True, subscription__isnull=True)

        # F. Possíveis faturas ausentes
        assinaturas_ativas = BandSubscription.objects.filter(status='ATIVO').select_related('band')
        faturas_ausentes = []
        for sub in assinaturas_ativas:
            if not sub.next_due_date:
                continue
            # Verifica se tem fatura em até 15 dias antes ou depois do next_due_date
            tem_fatura = BillingRecord.objects.filter(
                band=sub.band,
                due_date__gte=sub.next_due_date - datetime.timedelta(days=15),
                due_date__lte=sub.next_due_date + datetime.timedelta(days=15)
            ).exists()
            if not tem_fatura:
                faturas_ausentes.append(sub)

        # G. Possíveis duplicidades
        duplicidades_raw = BillingRecord.objects.values('band__name', 'due_date', 'reference_period').annotate(qtd=Count('id')).filter(qtd__gt=1)
        duplicidades = list(duplicidades_raw)

        # Print Resumo
        self.stdout.write(self.style.WARNING("RESUMO:"))
        self.stdout.write(f"- Assinaturas analisadas: {BandSubscription.objects.count()}")
        self.stdout.write(f"- Assinaturas vencidas: {subs_vencidas.count()}")
        self.stdout.write(f"- Assinaturas vencendo em {days} dias: {subs_vencendo.count()}")
        self.stdout.write(f"- Faturas pendentes vencidas: {faturas_vencidas.count()}")
        self.stdout.write(f"- Faturas pendentes vencendo: {faturas_vencendo.count()}")
        self.stdout.write(f"- Bandas ativas sem assinatura: {bandas_sem_assinatura.count()}")
        self.stdout.write(f"- Possíveis faturas ausentes: {len(faturas_ausentes)}")
        self.stdout.write(f"- Possíveis duplicidades: {len(duplicidades)}")
        self.stdout.write("")

        # Details
        self.stdout.write(self.style.ERROR("ASSINATURAS VENCIDAS:"))
        if subs_vencidas:
            for s in subs_vencidas:
                dt = s.next_due_date.strftime('%d/%m/%Y') if s.next_due_date else 'N/A'
                if s.status in ['ATIVO', 'VENCENDO']:
                    old_status = s.status
                    if apply_mode:
                        s.status = 'VENCIDO'
                        s.save(update_fields=['status'])
                    self.stdout.write(f"{tag} Assinatura {s.band.name} seria alterada de {old_status} para VENCIDO." if not apply_mode else f"{tag} Assinatura {s.band.name} alterada de {old_status} para VENCIDO.")
                else:
                    self.stdout.write(f"- {s.band.name} | {s.plan_name} | Venceu: {dt} | Status atual: {s.status} | Ação sugerida: Nenhuma (Apenas listado)")
        else:
            self.stdout.write("- Nenhuma")
        self.stdout.write("")

        self.stdout.write(self.style.WARNING("ASSINATURAS VENCENDO:"))
        if subs_vencendo:
            for s in subs_vencendo:
                dt = s.next_due_date.strftime('%d/%m/%Y') if s.next_due_date else 'N/A'
                if s.status == 'ATIVO':
                    old_status = s.status
                    if apply_mode:
                        s.status = 'VENCENDO'
                        s.save(update_fields=['status'])
                    self.stdout.write(f"{tag} Assinatura {s.band.name} seria alterada de {old_status} para VENCENDO." if not apply_mode else f"{tag} Assinatura {s.band.name} alterada de {old_status} para VENCENDO.")
                else:
                    self.stdout.write(f"- {s.band.name} | {s.plan_name} | Vencimento: {dt} | Status atual: {s.status} | Ação sugerida: Nenhuma (Apenas listado)")
        else:
            self.stdout.write("- Nenhuma")
        self.stdout.write("")

        self.stdout.write(self.style.ERROR("FATURAS PENDENTES VENCIDAS:"))
        if faturas_vencidas:
            for f in faturas_vencidas:
                dt = f.due_date.strftime('%d/%m/%Y') if f.due_date else 'N/A'
                old_status = f.status
                if apply_mode:
                    f.status = 'ATRASADO'
                    f.save(update_fields=['status'])
                self.stdout.write(f"{tag} Fatura {f.reference_period} ({f.band.name}) seria alterada de {old_status} para ATRASADO." if not apply_mode else f"{tag} Fatura {f.reference_period} ({f.band.name}) alterada de {old_status} para ATRASADO.")
        else:
            self.stdout.write("- Nenhuma")
        self.stdout.write("")

        self.stdout.write(self.style.WARNING("FATURAS VENCENDO:"))
        if faturas_vencendo:
            for f in faturas_vencendo:
                dt = f.due_date.strftime('%d/%m/%Y') if f.due_date else 'N/A'
                self.stdout.write(f"- {f.band.name} | Período: {f.reference_period} | R$ {f.amount} | Vencimento: {dt} | Status atual: {f.status} | Nenhuma ação (Não existe status VENCENDO para fatura)")
        else:
            self.stdout.write("- Nenhuma")
        self.stdout.write("")

        self.stdout.write(self.style.WARNING("BANDAS SEM ASSINATURA:"))
        if bandas_sem_assinatura:
            for b in bandas_sem_assinatura:
                self.stdout.write(f"- {b.name} | Status da banda: Ativa | Ação sugerida: avaliar bloqueio manual.")
        else:
            self.stdout.write("- Nenhuma")
        self.stdout.write("")

        self.stdout.write(self.style.WARNING("POSSÍVEIS FATURAS AUSENTES:"))
        if faturas_ausentes:
            for s in faturas_ausentes:
                dt = s.next_due_date.strftime('%d/%m/%Y') if s.next_due_date else 'N/A'
                self.stdout.write(f"- {s.band.name} | {s.plan_name} | Próximo vencimento: {dt} | Valor contratado: R$ {s.contracted_value} | Ação sugerida: criar manualmente ou aguardar Etapa 4C")
        else:
            self.stdout.write("- Nenhuma")
        self.stdout.write("")

        self.stdout.write(self.style.ERROR("POSSÍVEIS DUPLICIDADES:"))
        if duplicidades:
            for d in duplicidades:
                dt = d['due_date'].strftime('%d/%m/%Y') if d['due_date'] else 'N/A'
                self.stdout.write(f"- {d['band__name']} | Período: {d['reference_period']} | Vencimento: {dt} | Quantidade encontrada: {d['qtd']}")
        else:
            self.stdout.write("- Nenhuma")
        self.stdout.write("")

        self.stdout.write(self.style.SUCCESS("CONCLUSÃO:"))
        if apply_mode:
            self.stdout.write("- Atualizações de status aplicadas com sucesso.")
            self.stdout.write("- Nenhuma fatura foi criada automaticamente nesta etapa.")
        else:
            self.stdout.write("- Nenhum dado foi alterado.")
            self.stdout.write("- Este relatório é apenas diagnóstico.")
        self.stdout.write("")
