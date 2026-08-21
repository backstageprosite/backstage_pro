import os
from django.core.management.base import BaseCommand
from django.conf import settings
from core.models import (
    ContractDocument, FinancialReceipt, ShowPayment, RiderDocument,
    Band, SupportTicketAttachment, Partner, SystemSettings,
    LandingPageBandLogo, Expense, Show
)

class Command(BaseCommand):
    help = 'Audit uploaded files in the system.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', default=True, help='Dry run (default True)')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        self.stdout.write(self.style.WARNING(f'Starting audit... (Dry Run: {dry_run})'))

        allowed_extensions = {'.pdf', '.jpg', '.jpeg', '.png', '.webp', '.docx', '.xlsx'}
        
        # 1. Shows with > 7 attachments or > 35MB
        self.stdout.write(self.style.SUCCESS('\n--- Shows with > 7 attachments or > 35MB ---'))
        shows = Show.objects.all()
        for show in shows:
            attachments = []
            attachments.extend(list(show.documents.all()))
            attachments.extend(list(show.receipts.all()))
            attachments.extend(list(show.payments.exclude(file='').exclude(file__isnull=True)))
            
            count = len(attachments)
            total_size = 0
            for att in attachments:
                if att.file and hasattr(att.file, 'path') and os.path.exists(att.file.path):
                    total_size += os.path.getsize(att.file.path)
            
            total_size_mb = total_size / (1024 * 1024)
            if count > 7 or total_size_mb > 35:
                self.stdout.write(f"Show {show.id} ({show.title}): {count} attachments, {total_size_mb:.2f} MB")

        # Gather all file paths from DB for next checks
        db_files = []
        
        def process_model(queryset, field_name):
            for obj in queryset:
                file_field = getattr(obj, field_name)
                if file_field and file_field.name:
                    db_files.append((obj, file_field))

        process_model(ContractDocument.objects.all(), 'file')
        process_model(FinancialReceipt.objects.all(), 'file')
        process_model(ShowPayment.objects.exclude(file='').exclude(file__isnull=True), 'file')
        process_model(RiderDocument.objects.all(), 'file')
        process_model(Band.objects.exclude(logo='').exclude(logo__isnull=True), 'logo')
        process_model(SupportTicketAttachment.objects.all(), 'file')
        process_model(Partner.objects.exclude(image='').exclude(image__isnull=True), 'image')
        process_model(SystemSettings.objects.exclude(logo='').exclude(logo__isnull=True), 'logo')
        process_model(LandingPageBandLogo.objects.exclude(image='').exclude(image__isnull=True), 'image')
        process_model(Expense.objects.exclude(proof_file='').exclude(proof_file__isnull=True), 'proof_file')

        large_files = []
        forbidden_extensions = []
        db_orphans = []
        db_file_paths = set()

        for obj, file_field in db_files:
            try:
                path = file_field.path
            except NotImplementedError:
                continue
                
            db_file_paths.add(os.path.abspath(path))
            
            if not os.path.exists(path):
                db_orphans.append(f"{obj.__class__.__name__} ID {obj.id}: File missing on disk ({path})")
                continue
            
            size_mb = os.path.getsize(path) / (1024 * 1024)
            if size_mb > 10:
                large_files.append(f"{obj.__class__.__name__} ID {obj.id}: {size_mb:.2f} MB ({path})")
                
            ext = os.path.splitext(path)[1].lower()
            if ext not in allowed_extensions:
                forbidden_extensions.append(f"{obj.__class__.__name__} ID {obj.id}: Extension {ext} ({path})")

        # 2. Files > 10MB
        self.stdout.write(self.style.SUCCESS('\n--- Files > 10MB ---'))
        for lf in large_files:
            self.stdout.write(lf)

        # 3. Forbidden Extensions
        self.stdout.write(self.style.SUCCESS('\n--- Files with forbidden extensions ---'))
        for fe in forbidden_extensions:
            self.stdout.write(fe)

        # 4. Orphaned files
        self.stdout.write(self.style.SUCCESS('\n--- Orphaned Files ---'))
        for do in db_orphans:
            self.stdout.write(do)

        # Files on disk not in DB
        media_root = settings.MEDIA_ROOT
        disk_orphans = []
        if os.path.exists(media_root):
            for root, dirs, files in os.walk(media_root):
                for file in files:
                    full_path = os.path.abspath(os.path.join(root, file))
                    if full_path not in db_file_paths:
                        disk_orphans.append(full_path)
                        
            for do in disk_orphans:
                self.stdout.write(f"Orphan on disk: {do}")

        self.stdout.write(self.style.SUCCESS('\nAudit complete.'))
