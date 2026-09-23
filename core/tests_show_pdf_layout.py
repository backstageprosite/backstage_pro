import datetime
from django.test import TestCase, Client
from django.urls import reverse
from core.models import Band, User, Show


class ShowPdfLayoutCronogramaLogisticaTests(TestCase):
    """
    Testes específicos para o PDF do Show:
    1. Caixas superiores 'Dados do Evento' e 'Cronograma' com 5 linhas fixas,
       preservação de Local e Endereço, ordem e redação exatas.
    2. Links 'Abrir no mapa' independentes para Saída (departure_location_link)
       e para Cidade / Local (address_link).
    3. Transporte principal exibido em Produção (e ausente do Cronograma),
       com link clicável de WhatsApp para o contato com DDI 55 e dígitos.
    4. Seção 'Deslocamento & Transporte' (logística separada) oculta quando não há
       logística específica de técnica ou artista.
    5. Seção 'Deslocamento & Transporte' visível quando há logística específica de técnica ou artista,
       sem duplicar informações da logística principal que já constam no Cronograma.
    """

    def setUp(self):
        self.client = Client()
        self.band = Band.objects.create(
            name='Danniel Vieira',
            slug='danniel-vieira',
            is_active=True,
            subscription_plan='ADVANCED'
        )
        self.user = User.objects.create_user(
            username='produtor_dv',
            email='produtor@dv.com.br',
            password='password123',
            role='PRODUTOR',
            band=self.band
        )
        self.client.login(username='produtor_dv', password='password123')

    def test_01_show_com_logistica_principal_apenas(self):
        """
        Cenário 1: Show com logística principal apenas.
        - Exibe 5 linhas em Dados do Evento e 5 linhas em Cronograma.
        - Não exibe a seção 'Deslocamento & Transporte' de logística separada.
        - Exibe 'Meio de transporte' e 'Contato' em Produção com link de WhatsApp.
        - Links de mapa independentes e clicáveis.
        """
        show = Show.objects.create(
            band=self.band,
            title='ITAITÉ/BA',
            date=datetime.date(2026, 9, 24),
            event_name='EMANCIPAÇÃO POLÍTICA',
            city='Itaíté/BA',
            venue='Praça Pública',
            address='Praça Pública',
            address_link='https://maps.google.com/?q=PracaPublicaItaite',
            # Cronograma
            departure_time=datetime.datetime(2026, 9, 24, 10, 30),
            departure_location='Pituba Ville',
            departure_location_link='https://maps.google.com/?q=PitubaVille',
            distance_km='390km',
            travel_time='7:30h',
            arrival_time=datetime.datetime(2026, 9, 24, 18, 0),
            arrival_location='Itaíté/BA',
            soundcheck_time=datetime.time(20, 0),
            soundcheck_end_time=datetime.time(22, 0),
            show_time=datetime.time(22, 0),
            show_end_time=datetime.time(23, 30),
            duration='1:30',
            # Transporte principal
            transport='Ônibus',
            transport_contact='(71) 98142-4054',
            # Sem logística separada
            has_specific_tech_logistics=False,
            has_specific_artist_logistics=False
        )

        url = reverse('show_pdf', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # 1. Dados do Evento (5 linhas)
        self.assertIn('<strong>Nome do Show:</strong> ITAITÉ/BA', content)
        self.assertIn('<strong>Data:</strong> 24/09/2026', content)
        self.assertIn('<strong>Nome do Evento:</strong> EMANCIPAÇÃO POLÍTICA', content)
        self.assertIn('<strong>Cidade / Local:</strong> Itaíté/BA · Praça Pública · <a href="https://maps.google.com/?q=PracaPublicaItaite"', content)
        self.assertIn('<strong>Endereço:</strong> Praça Pública', content)

        # 2. Cronograma (5 linhas com redação exata)
        self.assertIn('<strong>Saída:</strong> 10:30 · Pituba Ville · <a href="https://maps.google.com/?q=PitubaVille"', content)
        self.assertIn('<strong>Distância:</strong> 390km | <strong>Tempo de Desloc.:</strong> 7:30h', content)
        self.assertIn('<strong>Chegada prevista:</strong> 18:00 · Itaíté/BA', content)
        self.assertIn('<strong>Passagem de Som:</strong> Início: 20:00 | Final: 22:00', content)
        self.assertIn('<strong>Show:</strong> Início: 22:00 | Final: 23:30 | Tempo: 1:30', content)

        # 3. Links de mapa distintos
        self.assertIn('href="https://maps.google.com/?q=PitubaVille"', content)
        self.assertIn('href="https://maps.google.com/?q=PracaPublicaItaite"', content)

        # 4. Transporte em Produção com link de WhatsApp
        self.assertIn('<strong>Meio de transporte:</strong> Ônibus', content)
        self.assertIn('<strong>Contato:</strong>', content)
        self.assertIn('href="https://wa.me/5571981424054"', content)
        self.assertIn('(71) 98142-4054', content)

        # 5. Deslocamento & Transporte oculto pois não há logística separada
        self.assertNotIn('Deslocamento & Transporte', content)

    def test_02_show_com_deslocamento_separado_tecnica_ou_artista(self):
        """
        Cenário 2: Show com deslocamento separado para técnica ou artista.
        - Exibe a seção 'Deslocamento & Transporte (Logística Separada)'.
        - Não duplica a logística principal nessa seção.
        """
        show = Show.objects.create(
            band=self.band,
            title='FESTIVAL DE VERÃO',
            date=datetime.date(2026, 12, 10),
            city='Salvador/BA',
            venue='Parque de Exposições',
            address='Av. Paralela',
            # Logística principal
            departure_location='Base Banda',
            transport='Van',
            transport_contact='71999998888',
            # Logística separada ativada para Técnica
            has_specific_tech_logistics=True,
            tech_departure_location='Galpão de Equipamentos',
            tech_arrival_location='Parque de Exposições',
            tech_departure_time=datetime.datetime(2026, 12, 10, 8, 0),
            tech_travel_time='1h',
            tech_distance_km='20km',
            tech_transport='Caminhão Baú'
        )

        url = reverse('show_pdf', kwargs={'band_slug': self.band.slug, 'pk': show.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')

        # Seção de Logística Separada deve ser exibida
        self.assertIn('Deslocamento & Transporte (Logística Separada)', content)
        self.assertIn('Logística Específica — Técnica', content)
        self.assertIn('Galpão de Equipamentos', content)
        self.assertIn('Caminhão Baú', content)

        # Logística principal NÃO é duplicada dentro desta seção
        self.assertNotIn('Logística Principal —', content)
