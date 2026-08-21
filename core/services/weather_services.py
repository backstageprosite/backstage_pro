import requests

def get_weather_for_show(city_name, show_date):
    if not city_name or not show_date:
        return None
    
    try:
        # Convert "Salvador/BA" or "Salvador - BA" to "Salvador, BA" for better API accuracy
        search_city = city_name.replace('/', ', ').replace(' - ', ', ')
        
        # Geocode
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={search_city}&count=1&language=pt&format=json"
        geo_resp = requests.get(geo_url, timeout=5)
        geo_data = geo_resp.json()
        
        if not geo_data.get('results'):
            return None
            
        lat = geo_data['results'][0]['latitude']
        lon = geo_data['results'][0]['longitude']
        
        # Format date as YYYY-MM-DD
        date_str = show_date.strftime("%Y-%m-%d")
        
        # Get weather
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode&timezone=America%2FSao_Paulo&start_date={date_str}&end_date={date_str}"
        w_resp = requests.get(weather_url, timeout=5)
        w_data = w_resp.json()
        
        if 'error' in w_data or 'daily' not in w_data:
            return None
            
        daily = w_data['daily']
        if not daily.get('weathercode') or len(daily['weathercode']) == 0:
            return None
            
        weathercode = daily['weathercode'][0]
        temp_max = daily['temperature_2m_max'][0]
        temp_min = daily['temperature_2m_min'][0]
        precip = daily['precipitation_probability_max'][0]
        
        # Simple weather mapping
        weather_map = {
            0: "Céu limpo",
            1: "Ensolarado",
            2: "Parc. nublado",
            3: "Nublado",
            45: "Nevoeiro",
            48: "Nevoeiro geada",
            51: "Garoa leve",
            53: "Garoa",
            55: "Garoa forte",
            61: "Chuva leve",
            63: "Chuva",
            65: "Chuva forte",
            71: "Neve leve",
            80: "Pancadas de chuva",
            81: "Chuva intensa",
            82: "Chuva torrencial",
            95: "Tempestade"
        }
        
        condition = weather_map.get(weathercode, "Misto")
        
        return {
            'min': round(temp_min) if temp_min is not None else '-',
            'max': round(temp_max) if temp_max is not None else '-',
            'precip': precip if precip is not None else '-',
            'condition': condition
        }
    except Exception as e:
        print("Weather error:", e)
        return None
