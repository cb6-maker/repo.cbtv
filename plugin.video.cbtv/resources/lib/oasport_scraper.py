import requests
import re
from datetime import datetime
import urllib3

urllib3.disable_warnings()

# Emittenti note per la mappatura dell'agenda
KNOWN_CHANNELS = {
    "eurosport 1": "Eurosport 1",
    "eurosport 2": "Eurosport 2",
    "eurosport player": "Eurosport Player",
    "eurosport": "Eurosport",
    "sky sport uno": "Sky Sport Uno",
    "sky sport calcio": "Sky Sport Calcio",
    "sky sport basket": "Sky Sport Basket",
    "sky sport arena": "Sky Sport Arena",
    "sky sport tennis": "Sky Sport Tennis",
    "sky sport f1": "Sky Sport F1",
    "sky sport motogp": "Sky Sport MotoGP",
    "sky sport max": "Sky Sport Max",
    "sky sport 24": "Sky Sport 24",
    "sky sport": "Sky Sport",
    "dazn": "DAZN",
    "rai 2": "Rai 2",
    "raisporthd": "Rai Sport",
    "rai sport hd": "Rai Sport",
    "rai sport": "Rai Sport",
    "now": "NOW",
    "discovery plus": "Discovery+",
    "hbo max": "HBO Max",
}

def clean_html_tags(raw_html):
    """Rimuove i tag HTML e decodifica le entità comuni in modo sicuro."""
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    cleantext = cleantext.replace('&#8211;', '–').replace('&amp;', '&').replace('&#215;', 'x').replace('&nbsp;', ' ')
    cleantext = cleantext.replace('’', "'").replace('‘', "'").replace('“', '"').replace('”', '"')
    return cleantext.strip()

def get_oasport_schedule():
    """
    Recupera la programmazione sportiva odierna da OA Sport.
    Essendo un sito editoriale italiano, è completamente immune ai blocchi AGCOM.
    """
    homepage_url = "https://www.oasport.it/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    }
    
    try:
        resp = requests.get(homepage_url, headers=headers, timeout=12, verify=False)
        if resp.status_code != 200:
            return []
            
        html = resp.text
        
        # 1. Ricerca dell'articolo odierno "Sport in tv oggi"
        article_url = None
        links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
        
        now = datetime.now()
        day_num = now.strftime("%d").lstrip("0")
        months_it = {
            1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
            7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre"
        }
        today_month_it = months_it[now.month]
        
        for href, text in links:
            text_clean = clean_html_tags(text).lower()
            href_low = href.lower()
            
            # Cerca pattern come "sport-in-tv-oggi" o "sport in tv oggi"
            if "sport-in-tv-oggi" in href_low or "sport in tv oggi" in text_clean:
                # Controlla che appartenga al mese corrente
                if today_month_it[:4] in href_low or today_month_it[:4] in text_clean:
                    article_url = href
                    break
                    
        # Fallback se la ricerca mirata fallisce (cerca qualsiasi link sport-in-tv-oggi recente)
        if not article_url:
            for href, text in links:
                if "sport-in-tv-oggi" in href.lower():
                    article_url = href
                    break
                    
        if not article_url:
            return []
            
        # 2. Fetch dell'articolo
        art_resp = requests.get(article_url, headers=headers, timeout=12, verify=False)
        if art_resp.status_code != 200:
            return []
            
        art_html = art_resp.text
        
        # 3. Parsing flessibile e multi-strategia degli eventi
        raw_events = []
        
        # Strategia A: Analisi degli elementi <li> (il formato standard di OA Sport)
        li_items = re.findall(r'<li[^>]*>(.*?)</li>', art_html, re.DOTALL)
        for item in li_items:
            text = clean_html_tags(item)
            # Verifica che inizi con un orario valido (es: "11:00" o "Ore 15.30")
            if re.match(r'^(?:ore\s+)?\d{2}[:\.]\d{2}', text, re.IGNORECASE):
                raw_events.append(text)
                
        # Strategia B: Fallback sugli elementi <p> (se gli articoli sono scritti senza liste puntate)
        if len(raw_events) < 4:
            p_items = re.findall(r'<p[^>]*>(.*?)</p>', art_html, re.DOTALL)
            for item in p_items:
                text = clean_html_tags(item)
                if re.match(r'^(?:ore\s+)?\d{2}[:\.]\d{2}', text, re.IGNORECASE):
                    raw_events.append(text)
                    
        # Strategia C: Fallback split per <br> (se è tutto un blocco unico)
        if len(raw_events) < 4:
            blocks = re.split(r'<br\s*/?>', art_html)
            for b in blocks:
                text = clean_html_tags(b)
                if re.match(r'^(?:ore\s+)?\d{2}[:\.]\d{2}', text, re.IGNORECASE):
                    raw_events.append(text)
                    
        all_events = []
        
        for ev in raw_events:
            ev_clean = ev.replace('\n', ' ').replace('\r', '').replace('  ', ' ').strip()
            
            # Estrazione sicura dell'orario
            time_m = re.match(r'^(?:ore\s+)?(\d{2})[:\.](\d{2})', ev_clean, re.IGNORECASE)
            if not time_m:
                continue
            
            hh = int(time_m.group(1))
            mm = int(time_m.group(2))
            
            # Validazione orario reale
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                continue
                
            time_str = f"{str(hh).zfill(2)}:{str(mm).zfill(2)}"
            
            # Pulizia descrizione evento
            desc = re.sub(r'^(?:ore\s+)?\d{2}[:\.]\d{2}\s*', '', ev_clean, flags=re.IGNORECASE).strip()
            if not desc:
                continue
                
            desc_low = desc.lower()
            
            # --- CLASSIFICAZIONE SPORT DINAMICA ---
            sport_cat = "Altri Sport"
            if any(x in desc_low for x in ["tennis", "roland garros", "atp", "wta", "davis", "wimbledon", "open"]):
                sport_cat = "Tennis"
            elif any(x in desc_low for x in ["f1", "formula 1", "motogp", "moto gp", "moto2", "moto3", "superbike", "sbk", "ferrari"]):
                sport_cat = "Motorsport"
            elif any(x in desc_low for x in ["volley", "pallavolo", "superlega", "cev"]):
                sport_cat = "Volley"
            elif any(x in desc_low for x in ["basket", "pallacanestro", "lba", "euroleague", "nba"]):
                continue  # Escluso Basket
            elif any(x in desc_low for x in ["ciclismo", "giro d'italia", "tour de france", "vuelta", "tappa"]):
                continue  # Escluso Ciclismo
            elif any(x in desc_low for x in ["calcio", "serie a", "serie b", "champions", "europa league", "conference"]):
                continue  # Escluso calcio (gestito da SportEventz)
                
            # --- RILEVAMENTO CANALI IN STREAMING (MAPPATURA DIRETTA) ---
            channels = []
            matched_keys = []
            
            for k in KNOWN_CHANNELS.keys():
                if k in desc_low:
                    matched_keys.append(k)
                    
            matched_keys.sort(key=len, reverse=True)
            
            seen_channels = set()
            for k in matched_keys:
                ch_name = KNOWN_CHANNELS[k]
                is_overlap = False
                for existing in seen_channels:
                    if ch_name in existing or existing in ch_name:
                        is_overlap = True
                        break
                if not is_overlap:
                    channels.append({
                        "name": ch_name,
                        "country": "OA Sport"
                    })
                    seen_channels.add(ch_name)
            
            # Fallback suggerimenti generici
            if not channels:
                if sport_cat == "Tennis":
                    channels.append({"name": "Sky Sport Tennis", "country": "Suggerito"})
                    channels.append({"name": "Eurosport 1", "country": "Suggerito"})
                elif sport_cat == "Motorsport":
                    if "motogp" in desc_low:
                        channels.append({"name": "Sky Sport MotoGP", "country": "Suggerito"})
                    else:
                        channels.append({"name": "Sky Sport F1", "country": "Suggerito"})
                elif sport_cat == "Volley":
                    channels.append({"name": "Rai Sport", "country": "Suggerito"})
                    channels.append({"name": "Sky Sport Arena", "country": "Suggerito"})
            
            # --- PARSING E DE-RAGGRUPPAMENTO EVENTI MULTIPLI ---
            cleaned_desc = re.sub(r'\s*[-–]\s*(?:Diretta|Dalle|streaming|live|tv|solo|su\b).*$', '', desc, flags=re.IGNORECASE).strip()
            
            parenthesis_match = re.search(r'\(([^)]+)\)', cleaned_desc)
            split_titles = []
            
            if parenthesis_match:
                inner_content = parenthesis_match.group(1)
                split_pattern = r',\s*(?=\d+°\s+match|a\s+seguire|non\s+prima|ore\s+\d|\d{1,2}[:\.]\d{2})'
                sub_matches = re.split(split_pattern, inner_content)
                
                if len(sub_matches) > 1:
                    prefix = cleaned_desc.split('(')[0].strip()
                    prefix = re.sub(r'[:\-–\s]+$', '', prefix).strip()
                    
                    for sm in sub_matches:
                        sm_clean = sm.strip()
                        if sm_clean:
                            split_titles.append(f"{prefix} - {sm_clean}")
            
            if not split_titles:
                split_titles.append(cleaned_desc)
                
            for title_item in split_titles:
                # Rimozione emoji per Kodi
                title_item = "".join(c for c in title_item if ord(c) < 65536)
                all_events.append({
                    "date": now.strftime("%d %B %Y"),
                    "time": time_str,
                    "title": title_item,
                    "sport": sport_cat,
                    "category": sport_cat,
                    "tournament": sport_cat,
                    "sources": channels,
                    "is_top": False
                })
            
        return all_events
        
    except Exception:
        return []
