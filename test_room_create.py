import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth import get_user_model
from core.models import Band, RoomList, Room
from core.views import room_list_room_create
from django.contrib.messages.storage.fallback import FallbackStorage

User = get_user_model()
band = Band.objects.first()
produtor = User.objects.filter(band=band, role__in=['PRODUTOR', 'EMPRESARIO']).first()
if not produtor:
    produtor = User.objects.first()
room_list = RoomList.objects.filter(show__band=band).first()

if room_list:
    req = RequestFactory().post('/fake/', data={
        'quantity': '3',
        'number_or_name': '',
        'type': 'DUPLO',
        'capacity': '2',
        'has_ac': 'on'
    })
    req.user = produtor
    req.band = band
    setattr(req, 'session', 'session')
    messages = FallbackStorage(req)
    setattr(req, '_messages', messages)

    initial_count = Room.objects.filter(room_list=room_list).count()
    resp = room_list_room_create(req, band.slug, room_list.pk)
    final_count = Room.objects.filter(room_list=room_list).count()
    print(f"Initial: {initial_count}, Final: {final_count}")
    for msg in messages:
        print("Message:", msg)
else:
    print('No room list found')
