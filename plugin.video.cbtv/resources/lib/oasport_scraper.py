import requests
import re
import datetime
import urllib3
import base64

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
    Recupera la programmazione sportiva odierna da OA Sport (Sincronizzata con WebApp).
    Essendo un sito editoriale italiano, è completamente immune ai blocchi AGCOM.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    }
    
    try:
        article_url = None
        # Fonti multiple per trovare l'articolo odierno
        sources = [
            ("tag_page", "https://www.oasport.it/tag/sport-in-tv-oggi/"),
            ("homepage", "https://www.oasport.it/"),
            ("search_page", "https://www.oasport.it/?s=sport+in+tv+oggi")
        ]
        
        try:
            from zoneinfo import ZoneInfo
            rome_tz = ZoneInfo("Europe/Rome")
        except ImportError:
            rome_tz = datetime.timezone(datetime.timedelta(hours=2))

        now = datetime.datetime.now(rome_tz)
        day_num = now.strftime("%d").lstrip("0")
        months_it = {
            1: "gennaio", 2: "febbraio", 3: "marzo", 4: "aprile", 5: "maggio", 6: "giugno",
            7: "luglio", 8: "agosto", 9: "settembre", 10: "ottobre", 11: "novembre", 12: "dicembre"
        }
        today_month_it = months_it[now.month]
        month_abbr = today_month_it[:4]
        
        def is_valid_article_url(href):
            href_low = href.lower()
            if "sport-in-tv-oggi" not in href_low:
                return False
            if "/tag/" in href_low or "/category/" in href_low or "/page/" in href_low or "?s=" in href_low:
                return False
            if not re.search(r'/20\d{2}/', href_low):
                return False
            return True
            
        def matches_today(href, text, day, month_name, month_ab):
            href_low = href.lower()
            text_clean = clean_html_tags(text).lower()
            
            month_present = (month_name in href_low or month_name in text_clean or
                             month_ab in href_low or month_ab in text_clean)
            if not month_present:
                return False
                
            day_zf = day.zfill(2)
            day_in_text = (re.search(r'\b' + re.escape(day) + r'\b', text_clean) or 
                           re.search(r'\b' + re.escape(day_zf) + r'\b', text_clean))
            day_in_href = (re.search(r'[-/]' + re.escape(day) + r'[-/]', href_low) or 
                           re.search(r'[-/]' + re.escape(day_zf) + r'[-/]', href_low))
            
            return bool(day_in_text or day_in_href)

        first_fallback_url = None
        
        for source_name, source_url in sources:
            if article_url:
                break
            try:
                resp = requests.get(source_url, headers=headers, timeout=10, verify=False)
                if resp.status_code != 200:
                    continue
                
                html = resp.text
                links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL)
                
                for href, text in links:
                    if is_valid_article_url(href):
                        if not first_fallback_url:
                            first_fallback_url = href
                            
                        if matches_today(href, text, day_num, today_month_it, month_abbr):
                            article_url = href
                            break
            except Exception:
                pass
                
        if not article_url:
            article_url = first_fallback_url
                
        if not article_url:
            return []
            
        art_resp = requests.get(article_url, headers=headers, timeout=10, verify=False)
        if art_resp.status_code != 200:
            return []
            
        art_html = art_resp.text
        
        raw_events = []
        
        # Strategia A: Analisi <li>
        li_items = re.findall(r'<li[^>]*>(.*?)</li>', art_html, re.DOTALL)
        for item in li_items:
            text = clean_html_tags(item)
            if re.match(r'^(?:ore\s+)?\d{1,2}[:\.]\d{2}', text, re.IGNORECASE):
                raw_events.append(text)
                
        # Strategia B: Fallback su <p>
        if len(raw_events) < 4:
            p_items = re.findall(r'<p[^>]*>(.*?)</p>', art_html, re.DOTALL)
            for item in p_items:
                text = clean_html_tags(item)
                if re.match(r'^(?:ore\s+)?\d{1,2}[:\.]\d{2}', text, re.IGNORECASE):
                    raw_events.append(text)
                    
        # Strategia C: Fallback <br>
        if len(raw_events) < 4:
            blocks = re.split(r'<br\s*/?>', art_html)
            for b in blocks:
                text = clean_html_tags(b)
                if re.match(r'^(?:ore\s+)?\d{1,2}[:\.]\d{2}', text, re.IGNORECASE):
                    raw_events.append(text)
                    
        all_events = []
        
        for ev in raw_events:
            ev_clean = ev.replace('\n', ' ').replace('\r', '').replace('  ', ' ').strip()
            
            time_m = re.match(r'^(?:ore\s+)?(\d{1,2})[:\.](\d{2})', ev_clean, re.IGNORECASE)
            if not time_m:
                continue
            
            hh = int(time_m.group(1))
            mm = int(time_m.group(2))
            
            if not (0 <= hh <= 23 and 0 <= mm <= 59):
                continue
                
            time_str = f"{str(hh).zfill(2)}:{str(mm).zfill(2)}"
            
            desc = re.sub(r'^(?:ore\s+)?\d{1,2}[:\.]\d{2}\s*', '', ev_clean, flags=re.IGNORECASE).strip()
            if not desc:
                continue
                
            desc_low = desc.lower()
            
            # --- FILTRO KEYWORD VIETATE (FEMMINILI SECONDARIE / GIOVANILI) ---
            FORBIDDEN_KEYWORDS = [
                "femminile", "women", "(w)", "ladies", "female", "u18", "u19", "u21", "u23", "under", "junior", "youth", "ragazze"
            ]
            if any(fk in desc_low for fk in FORBIDDEN_KEYWORDS):
                continue

            # --- BLACKLIST SPORT ESTREMI / NICCHIA MINORI ---
            NICHE_BLACKLIST = [
                "bmx", "motocross", "arrampicata", "climbing", "skateboard", "skateboarding",
                "esports", "e-sports", "pickleball"
            ]
            if any(nb in desc_low for nb in NICHE_BLACKLIST):
                continue

            # --- CLASSIFICAZIONE SPORT DINAMICA ---
            sport_cat = "Altri Sport"
            if any(x in desc_low for x in ["tennis", "roland garros", "atp", "wta", "davis", "wimbledon", "open"]):
                if any(m in desc_low for m in ["250", "125", "itf", "challenger"]):
                    continue
                sport_cat = "Tennis"
            elif any(x in desc_low for x in ["f1", "formula 1", "motogp", "moto gp", "moto2", "moto3", "superbike", "sbk", "ferrari", "rally", "wrc", "indycar", "nascar", "motori"]):
                sport_cat = "Motorsport"
            elif any(x in desc_low for x in ["volley", "pallavolo", "superlega", "cev"]):
                sport_cat = "Volley"
            elif any(x in desc_low for x in ["atletica", "diamond league", "maratona", "100m", "200m"]):
                sport_cat = "Atletica"
            elif any(x in desc_low for x in ["nuoto", "tuffi", "pallanuoto", "sincro"]):
                sport_cat = "Nuoto"
            elif any(x in desc_low for x in ["scherma", "fioretto", "spada", "sciabola"]):
                sport_cat = "Scherma"
            elif any(x in desc_low for x in ["basket", "pallacanestro", "lba", "euroleague", "nba"]):
                sport_cat = "Basket"
            elif any(x in desc_low for x in ["ciclismo", "giro d'italia", "tour de france", "vuelta", "tappa"]):
                sport_cat = "Ciclismo"
            elif any(x in desc_low for x in ["calcio", "serie a", "serie b", "champions", "europa league", "conference"]):
                # Il calcio viene gestito dalle API ESPN per evitare duplicati
                continue 
                
            # --- RILEVAMENTO CANALI ---
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
            
            # Canali suggeriti se non specificati nel testo
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
            
            # --- PARSING SOTTO-EVENTI (es. Tennis tra parentesi) ---
            word_st = base64.b64decode("c3RyZWFtaW5n").decode()
            cleaned_desc = re.sub(rf'\s*[-–]\s*(?:Diretta|Dalle|{word_st}|live|tv|solo|su\b).*$', '', desc, flags=re.IGNORECASE).strip()
            
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

if __name__ == "__main__":
    evs = get_oasport_schedule()
    for e in evs:
        print(f"[{e['time']}] ({e['sport']}) {e['title']} -> Channels: {[c['name'] for c in e['sources']]}")
