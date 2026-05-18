import requests
import re
import datetime
import urllib3

urllib3.disable_warnings()

# ─── CONFIG FILTRI ────────────────────────────────────────────────

# Tornei di calcio desiderati (match esatto su Categoria e Torneo)
FOOTBALL_FILTERS = [
    # Italia
    {"category": "italy", "tournament": "serie a"},
    {"category": "italy", "tournament": "serie b"},
    {"category": "italy", "tournament": "coppa italia"},
    {"category": "italy", "tournament": "super cup"},
    
    # Coppe europee
    {"category": "international clubs", "tournament": "champions league"},
    {"category": "international clubs", "tournament": "europa league"},
    {"category": "international clubs", "tournament": "conference league"},
    {"category": "international clubs", "tournament": "super cup"},
    
    # Top campionati europei
    {"category": "england", "tournament": "premier league"},
    {"category": "spain", "tournament": "la liga"},
    
    # Nazionali
    {"category": None, "tournament": "euro"},
    {"category": None, "tournament": "world cup"},
    {"category": None, "tournament": "wc qualification"},
    {"category": None, "tournament": "world cup qualification"},
    {"category": None, "tournament": "nations league"},
    {"category": None, "tournament": "international friendly"},
]

# Parole chiave per evidenziare eventi Top (Sincronizzate con WebApp)
W_TOP = ["COPPA ITALIA", "SERIE A", "CHAMPIONS", "EUROPA LEAGUE", "ITALIA", "ITALY", "JUVE", "INTER", "MILAN", "NAPOLI"]

# ─── FUNZIONI CORE ────────────────────────────────────────────────

def _create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    return session

def _fetch_page_json(session, page_url):
    try:
        resp = session.get(page_url, timeout=15, verify=False)
        if resp.status_code != 200:
            return None
        m = re.search(r"listAction:\s*'(.*?)'", resp.text)
        if not m:
            return None
        
        # client_tz_offset=%2B0100 -> fuso orario Europa/Roma (+01:00)
        list_url = "https://www.sporteventz.com" + m.group(1) + "&client_tz_offset=%2B0100"
        
        resp_json = session.get(list_url, headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": page_url
        }, timeout=15, verify=False)
        
        if not resp_json.text.strip():
            return {"Records": []}
            
        return resp_json.json()
    except Exception:
        return None

def _parse_record(rec):
    team1 = rec.get('Team1', {}).get('#text', '') if isinstance(rec.get('Team1'), dict) else ''
    team2 = rec.get('Team2', {}).get('#text', '') if isinstance(rec.get('Team2'), dict) else ''
    begin = rec.get('Begin', '')
    sport = rec.get('Sport', {}).get('#text', '') if isinstance(rec.get('Sport'), dict) else ''
    category = rec.get('Category', {}).get('#text', '') if isinstance(rec.get('Category'), dict) else ''
    tournament = rec.get('Tournament', {}).get('#text', '') if isinstance(rec.get('Tournament'), dict) else ''
    
    channels = []
    ch_section = rec.get('Channels', {})
    if isinstance(ch_section, dict):
        for key in ch_section.keys():
            ch_list = ch_section[key]
            if isinstance(ch_list, dict):
                ch_list = [ch_list]
            
            if isinstance(ch_list, list):
                for ch in ch_list:
                    if isinstance(ch, dict):
                        ch_name = ch.get('Name', '') or ch.get('#text', '?')
                        if ch_name and ch_name != '?':
                            channels.append({
                                "name": ch_name,
                                "country": ch.get('Country', '?')
                            })
                            
    # Rimuovi duplicati
    seen_norm = set()
    unique_channels = []
    for c in channels:
        name_clean = re.sub(r'\s*\(.*?\)', '', c["name"]).strip().lower()
        if name_clean not in seen_norm:
            unique_channels.append(c)
            seen_norm.add(name_clean)
            
    channels = unique_channels
            
    # Estrai data e ora
    date_str = ""
    time_str = begin
    date_m = re.search(r',\s*(\d{1,2}\s+\w+\s+\d{4})', begin)
    if date_m:
        date_str = date_m.group(1).strip()
        
    time_m = re.search(r'(\d{1,2}:\d{2})$', begin)
    if time_m:
        time_str = time_m.group(1)
        
    # Costruisci il titolo
    title = f"{team1} - {team2}" if team2 else team1
    if not title:
        title = tournament
        
    # Rimuovi solo le Emoji per compatibilità Kodi
    title = "".join(c for c in title if ord(c) < 65536).replace('  ', ' ').strip()
        
    return {
        "date": date_str,
        "time": time_str,
        "title": title,
        "sport": sport,
        "category": category,
        "tournament": tournament,
        "sources": channels
    }

def _filter_football(records):
    filtered = []
    for rec in records:
        parsed = _parse_record(rec)
        cat_lower = parsed["category"].lower()
        tourn_lower = parsed["tournament"].lower()
        
        # Esclusione calcio femminile e categorie minori (WSL, ecc.)
        forbidden = ["women", "woman", "women's", "wsl", "(w)", " (fem)", "femminile", "female", "ladies", "u21", "u19", "u17", "u20", "u23", "under 21", "youth"]
        combined_text = (parsed["tournament"] + " " + parsed["title"] + " " + parsed["category"]).lower()
        if any(x in combined_text for x in forbidden):
            continue

        match = False
        for f in FOOTBALL_FILTERS:
            cat_ok = f["category"] is None or f["category"] in cat_lower
            tourn_ok = f["tournament"] is None or f["tournament"] in tourn_lower
            
            if cat_ok and tourn_ok:
                if f.get("category") == "germany" and "amateur" in cat_lower:
                    continue
                match = True
                break
                
        if match:
            filtered.append(parsed)
    return filtered


def get_sporteventz_schedule():
    """Recupera l'agenda sportiva (Sync con WebApp)."""
    session = _create_session()
    all_events = []
    
    # Prepariamo il filtro per oggi
    now = datetime.datetime.now()
    today_num = str(now.day)
    mesi_eng = ["", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    today_month = mesi_eng[now.month]

    # 1. Calcio
    fb_data = _fetch_page_json(session, "https://www.sporteventz.com/en/")
    if fb_data and 'Records' in fb_data:
        all_events.extend(_filter_football(fb_data['Records']))
    
    seen_events = set()
    final_events = []
    
    for ev in all_events:
        # Filtro data: prendiamo solo oggi
        ev_date = (ev.get("date") or "").lower()
        is_today = (today_num in ev_date and today_month.lower() in ev_date) or not ev_date or "today" in ev_date
        
        if is_today:
            key = (ev["time"], ev["title"].lower().strip(), ev["sport"].lower().strip())
            if key not in seen_events:
                # Top Event identification
                t_up = ev["title"].upper()
                tr_up = ev["tournament"].upper()
                ev["is_top"] = any(w in t_up or w in tr_up for w in W_TOP)
                
                # Escludi le amichevoli dai top event (anche se hanno parole chiave come 'ITALIA')
                if "FRIENDLY" in tr_up or "AMICHEVOLE" in tr_up or "FRIENDLY" in t_up or "AMICHEVOLE" in t_up:
                    ev["is_top"] = False
                
                final_events.append(ev)
                seen_events.add(key)
            
    final_events.sort(key=lambda x: x["time"])
    return final_events
