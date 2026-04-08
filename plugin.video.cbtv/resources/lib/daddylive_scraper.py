import requests
import re
from datetime import datetime, timedelta
import concurrent.futures

# Squadre di volley italiane (femminili e maschili principali + nazionale)
ITALIAN_VOLLEY_TEAMS = [
    "perugia", "civitanova", "trento", "trentino", "modena", "monza", "milano",
    "piacenza", "verona", "padova", "taranto", "cisterna", "ravenna", "latina",
    "cuneo", "castellana", "lube", "vibo valentia",
    "conegliano", "novara", "scandicci", "busto arsizio", "firenze",
    "bergamo", "chieri", "roma", "vallefoglia", "casalmaggiore",
    "italy", "italia"
]

def scrape_daddylive_page(cat_name, url):
    """Estrae gli eventi da una specifica pagina di DaddyLive (es. cat=Tennis) gestendo i blocchi per data."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    try:
        # Assicurati che l'URL sia completo
        if url.startswith('/'):
            url = f"https://dlstreams.top{url}"
            
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        
        html = resp.text
        all_events = []
        
        # Oggi per il confronto (es: "25 March")
        now = datetime.now()
        today_num = now.strftime("%d").lstrip("0")
        today_month = now.strftime("%B")
        
        # Divisione in blocchi per data: <div class="schedule__day">
        day_blocks = re.split(r'<div class="schedule__day">', html)
        
        for block in day_blocks:
            if not block.strip():
                continue
            
            # 1. Estrai la data del blocco (es: "Tuesday 24th March 2026...")
            date_m = re.search(r'<div class="schedule__dayTitle">\s*(.*?)\s*</div>', block, re.DOTALL)
            if not date_m:
                continue
                
            date_text = date_m.group(1).strip()
            
            # 2. Verifica se è oggi (rimuovi suffissi ordinali come 'st', 'nd', 'rd', 'th')
            clean_date = re.sub(r'(\d+)(st|nd|rd|th)', r'\1', date_text).lower()
            is_today = today_num in clean_date and today_month.lower() in clean_date
            
            # Se la pagina ha eventi di più giorni, prendiamo solo quelli di oggi
            if not is_today:
                continue

            # 4. Determina l'offset timezone (UK GMT/BST -> Local)
            # Se il titolo dice GMT, la fonte è UTC+0. Se BST, è UTC+1.
            # In Italia siamo UTC+1 (Inverno) o UTC+2 (Estate).
            # La differenza tra Italia e UK è costantemente di +1 ora.
            uk_offset = 0 # Default GMT
            if "BST" in date_text.upper():
                uk_offset = 1
            
            # 3. Estrai eventi in questo blocco di data
            events_in_day = block.split('<div class="schedule__event">')
            
            for ev_block in events_in_day[1:]:
                time_m = re.search(r'data-time="(\d{2}:\d{2})"', ev_block)
                title_m = re.search(r'<span class="schedule__eventTitle">(.*?)</span>', ev_block)
                
                if not time_m or not title_m:
                    continue
                
                time_str = time_m.group(1)
                title = title_m.group(1).strip()
                
                # --- FILTRAGGIO AGGIUNTIVO ---
                t_low = title.lower()
                c_low = cat_name.lower()
                
                # Esclusione globale Sport Femminile e Minorili
                forbidden = ["women", "woman", "women's", "wsl", "(w)", " (fem)", "femminile", "female", "ladies", "u21", "u19", "u17", "u20", "u23", "under 21", "youth"]
                if any(x in t_low or x in c_low for x in forbidden):
                    continue
                
                # Tennis: solo ATP/WTA, no Challenger/ITF/Table Tennis
                if ("tennis" in c_low or "tennis" in t_low) and "table tennis" not in t_low and "table tennis" not in c_low:
                    major_keywords = [
                        "atp", "wta", "grand slam", "wimbledon", "roland garros", 
                        "australian open", "us open", "masters", "open", "cup", 
                        "finals", "united", "series", "davis", "billie jean"
                    ]
                    is_major = any(x in t_low or x in c_low for x in major_keywords)
                    is_challenger = "challenger" in t_low or "challenger" in c_low
                    is_itf = "itf" in t_low or "itf" in c_low
                    
                    if not is_major or is_challenger or is_itf:
                        continue
                
                # Volley: solo Italiano o CEV (Escludendo Superliga/Super League Brasiliana)
                if "volley" in c_low or "volley" in t_low:
                    has_italian = any(team in t_low for team in ITALIAN_VOLLEY_TEAMS)
                    is_cev = any(x in t_low for x in ["cev", "champions league"])
                    # Filtro esplicito per la Superliga Brasiliana (spesso chiamata Super League o Superliga)
                    is_brazil = any(kw in t_low for kw in ["brazil", "brasil", "superliga", "super league"])
                    
                    if is_brazil and not has_italian:
                        continue
                    if not (has_italian or is_cev):
                        continue
                        
                # Motorsport: solo F1 e MotoGP (+ Moto2/3)
                if "motorsport" in c_low or "f1" in c_low or "motogp" in c_low:
                    ms_keywords = ["formula 1", "f1", "motogp", "moto gp", "moto2", "moto3"]
                    if not any(kw in t_low for kw in ms_keywords):
                        continue
                
                # Calcio: ESCLUSO da DaddyLive come richiesto
                if "soccer" in c_low or "football" in c_low or "soccer" in t_low or "football" in t_low:
                    continue

                # Channels
                channels = []
                ch_block_m = re.search(r'<div class="schedule__channels">(.*?)</div>', ev_block, re.DOTALL)
                if ch_block_m:
                    ch_links = re.findall(r'<a[^>]*title="([^"]+)"[^>]*>', ch_block_m.group(1))
                    for ch_title in ch_links:
                        channels.append({
                            "name": ch_title.strip(),
                            "country": "DaddyLive"
                        })
                
                unique_ch = []
                seen_ch = set()
                for c in channels:
                    if c["name"] not in seen_ch:
                        unique_ch.append(c)
                        seen_ch.add(c["name"])
                channels = unique_ch
                
                try:
                    # Orario estivo: +2 ore rispetto a GMT
                    t = datetime.strptime(time_str, "%H:%M")
                    t = t + timedelta(hours=2)
                    time_str = t.strftime("%H:%M")
                except:
                    pass
                
                all_events.append({
                    "date": now.strftime("%d %B %Y"),
                    "time": time_str,
                    "title": title,
                    "sport": cat_name,
                    "category": cat_name,
                    "tournament": "",
                    "sources": channels,
                    "is_top": False
                })
                
        return all_events
    except Exception:
        return []

def get_daddylive_schedule():
    """Recupera l'agenda da DaddyLive."""
    base_url = "https://dlstreams.top/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    }
    
    try:
        resp = requests.get(base_url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return []
        
        # Parole chiave requests (Rimosso calcio come richiesto)
        KEYWORDS = ["tennis", "motorsport", "volley", "f1", "motogp", "pallavolo"]
        
        cat_links = re.findall(r'<a[^>]*href="(/index\.php\?cat=[^"]+)"[^>]*>(.*?)</a>', resp.text)
        
        to_scrape = []
        seen_urls = set()
        
        for url, name in cat_links:
            name_low = name.lower()
            if any(kw in name_low for kw in KEYWORDS) and "table tennis" not in name_low:
                full_url = f"https://dlstreams.top{url}"
                if full_url not in seen_urls:
                    to_scrape.append((name, full_url))
                    seen_urls.add(full_url)
        
        all_events = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(len(to_scrape), 1)) as executor:
            futures = {executor.submit(scrape_daddylive_page, name, url): name for name, url in to_scrape}
            
            for future in concurrent.futures.as_completed(futures):
                results = future.result()
                if results:
                    all_events.extend(results)
                    
        return all_events
        
    except Exception:
        return []
