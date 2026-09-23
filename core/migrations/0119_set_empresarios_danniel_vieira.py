from django.db import migrations


def set_empresarios(apps, schema_editor):
    Band = apps.get_model('core', 'Band')
    User = apps.get_model('core', 'User')
    UserBandMembership = apps.get_model('core', 'UserBandMembership')

    band = Band.objects.filter(id=1).first()
    if not band:
        band = Band.objects.filter(slug='danniel-vieira').first()

    if not band:
        return

    for username in ['vinicius', 'glauber']:
        user = User.objects.filter(username=username).first()
        if user:
            membership, created = UserBandMembership.objects.get_or_create(
                user=user,
                band=band,
                defaults={'role': 'EMPRESARIO', 'is_active': True}
            )
            if membership.role != 'EMPRESARIO':
                membership.role = 'EMPRESARIO'
                membership.save(update_fields=['role'])

            if user.role != 'EMPRESARIO':
                user.role = 'EMPRESARIO'
                user.save(update_fields=['role'])


def reverse_empresarios(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0118_financialreceipt_created_by'),
    ]

    operations = [
        migrations.RunPython(set_empresarios, reverse_empresarios),
    ]

