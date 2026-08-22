import requests
import re
import datetime
import urllib3

urllib3.disable_warnings()

# ─── CONFIG FILTRI E CANALI ───────────────────────────────────────

# Esclusioni per evitare match minori o giovanili
FORBIDDEN_KEYWORDS = [
    "women", "(w)", " (fem)", "femminile", "female", "ladies", 
    "u21", "u19", "u17", "u20", "u23", "under 21", "youth"
]

# Canali Italiani suggeriti per competizione
ITALIAN_BROADCASTERS = {
    "world cup": [("Rai 1", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT")],
    "mondiali": [("Rai 1", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT")],
    "euro": [("Rai 1", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT")],
    "serie a": [("DAZN", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT")],
    "serie b": [("DAZN", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT")],
    "coppa italia": [("Italia 1", "IT"), ("Canale 5", "IT"), ("Mediaset Infinity", "IT")],
    "champions league": [("Sky Sport Uno", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT"), ("Prime Video", "IT"), ("TV8", "IT")],
    "europa league": [("Sky Sport Uno", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT"), ("TV8", "IT")],
    "conference league": [("Sky Sport Uno", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT"), ("TV8", "IT")],
    "premier league": [("Sky Sport Uno", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT")],
    "la liga": [("DAZN", "IT")],
    "nations league": [("Rai 1", "IT"), ("Sky Sport Calcio", "IT"), ("NOW", "IT")],
}

# Parole chiave per definire i TOP EVENT
W_TOP = [
    "WORLD CUP", "MONDIALI", "MONDIALE",
    "COPPA ITALIA", "CHAMPIONS LEAGUE", "EUROPA LEAGUE", "CONFERENCE",
    "ITALIA", "ITALY", "JUVE", "JUVENTUS", "INTER", "MILAN", "NAPOLI", "ROMA", "LAZIO",
    "FIORENTINA", "ATALANTA", "BOLOGNA", "CAGLIARI",
    "REAL MADRID", "BARCELONA", "CITY", "LIVERPOOL", "ARSENAL", "BAYERN", "PSG",
]

# Squadre/Nazionali accettate nelle amichevoli
TOP_FRIENDLY_TEAMS = [
    "ITALY", "ITALIA", "JUVENTUS", "JUVE", "INTER", "MILAN", "NAPOLI", "ROMA", "LAZIO",
    "FIORENTINA", "ATALANTA", "CAGLIARI", "BOLOGNA", "TORINO",
    "REAL MADRID", "BARCELONA", "BARCA", "MANCHESTER CITY", "LIVERPOOL",
    "ARSENAL", "CHELSEA", "BAYERN", "PSG", "PARIS"
]

# Tornei e competizioni Top Ammessi (Scd / Ccd)
TOP_COMPETITIONS = {
    # Italia
    ("italy", "serie-a"),
    ("italy", "serie-b"),
    ("italy", "coppa-italia"),
    ("italy", "super-cup"),
    ("italy", "supercoppa"),
    # Europa / UEFA / FIFA
    ("europe", "champions-league"),
    ("europe", "europa-league"),
    ("europe", "europa-conference-league"),
    ("europe", "uefa-super-cup"),
    ("europe", "nations-league"),
    ("europe", "euro"),
    ("international", "world-cup"),
    ("international", "friendlies"),
    ("international", "club-friendlies"),
    # Inghilterra
    ("england", "premier-league"),
    ("england", "fa-cup"),
    ("england", "efl-cup"),
    ("england", "community-shield"),
    # Spagna
    ("spain", "laliga"),
    ("spain", "laliga-ea-sports"),
    ("spain", "primera-division"),
    ("spain", "copa-del-rey"),
    ("spain", "super-cup"),
    # Germania
    ("germany", "bundesliga"),
    ("germany", "dfb-pokal"),
    ("germany", "super-cup"),
    # Francia
    ("france", "ligue-1"),
    ("france", "coupe-de-france"),
    ("france", "super-cup"),
    # Altri Top
    ("saudi-arabia", "pro-league"),
    ("usa", "mls"),
}

def _is_allowed_stage(ccd, scd, cnm, snm):
    ccd = ccd.lower()
    scd = scd.lower()
    cnm = cnm.lower()
    snm = snm.lower()
    
    # Escludi campionati minori/regionali inglesi o minori esteri
    if "northern-premier" in scd or "southern-premier" in scd or "isthmian" in scd:
        return False

    # 1. Tupla esatta (Ccd, Scd)
    if (ccd, scd) in TOP_COMPETITIONS:
        return True
        
    # 2. Serie C italiana
    if ccd == "italy" and "serie-c" in scd:
        return True
        
    # 3. Match testuali per competizioni italiane
    if ccd == "italy" and any(k in snm for k in ["serie a", "serie b", "coppa italia", "supercoppa"]):
        return True
        
    # 4. Match testuali per UEFA / FIFA / Nazionali
    if ccd in ("europe", "international") and any(k in snm for k in ["champions league", "europa league", "conference league", "nations league", "mondiale", "world cup"]):
        return True

    # 5. Top 5 campionati (solo 1ª divisione)
    if ccd == "england" and scd == "premier-league":
        return True

    if ccd == "spain" and (scd == "laliga" or "laliga" in scd or "la liga" in snm) and "2" not in snm:
        return True

    if ccd == "germany" and (scd == "bundesliga" or "bundesliga" in scd) and "2" not in snm and "women" not in snm and "frauen" not in snm:
        return True

    if ccd == "france" and (scd == "ligue-1" or "ligue 1" in snm):
        return True

    return False

def _get_suggested_it_channels(comp_name, title_name):
    text = (comp_name + " " + title_name).lower()
    suggested = []
    for key, channels in ITALIAN_BROADCASTERS.items():
        if key in text:
            for ch_name, ch_country in channels:
                suggested.append({"name": ch_name, "country": ch_country})
            break
    
    if not suggested:
        suggested.append({"name": "Sky Sport Calcio", "country": "IT"})
        suggested.append({"name": "DAZN", "country": "IT"})
    return suggested

def get_sporteventz_schedule():
    """
    Recupera l'agenda CALCIO di oggi dalle API veloci e complete di LiveScore (prod-public-api.livescore.com).
    Filtra RIGOROSAMENTE solo i tornei ed i campionati TOP (Serie A, B, C, Champions, Europa League, Premier, LaLiga, Bundesliga, Ligue 1).
    """
    try:
        from zoneinfo import ZoneInfo
        rome_tz = ZoneInfo("Europe/Rome")
    except Exception:
        rome_tz = datetime.timezone(datetime.timedelta(hours=2))

    now_local = datetime.datetime.now(rome_tz)
    today_str = now_local.strftime("%Y%m%d")
    
    url = f"https://prod-public-api.livescore.com/v1/api/app/date/soccer/{today_str}/0?locale=it"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.livescore.com",
        "Referer": "https://www.livescore.com/"
    }

    events = []
    seen = set()
    
    try:
        resp = requests.get(url, headers=headers, timeout=8, verify=False)
        if resp.status_code != 200:
            return events
            
        data = resp.json()
        stages = data.get("Stages", [])
        
        for stage in stages:
            ccd = stage.get("Ccd", "")
            scd = stage.get("Scd", "")
            country = stage.get("Cnm", "")
            comp_name = stage.get("Snm", "") or country
            
            # FILTRO TORNEI: Accetta SOLO le competizioni Top ammesse
            if not _is_allowed_stage(ccd, scd, country, comp_name):
                continue

            # Filtro keyword vietate (femminili, under) sul torneo/paese
            if any(kw in (country + " " + comp_name).lower() for kw in FORBIDDEN_KEYWORDS):
                continue

            for ev in stage.get("Events", []):
                t1_list = ev.get("T1", [{}])
                t2_list = ev.get("T2", [{}])
                t1 = t1_list[0].get("Nm", "") if t1_list else ""
                t2 = t2_list[0].get("Nm", "") if t2_list else ""
                
                if not t1 or not t2:
                    continue
                    
                name_title = f"{t1} vs {t2}"
                
                # Filtro keyword vietate sul nome della partita
                if any(kw in name_title.lower() for kw in FORBIDDEN_KEYWORDS):
                    continue
                    
                # Filtro amichevoli: se è un'amichevole accettiamo solo i top team
                is_friendly = "friendly" in scd or "amichevol" in comp_name.lower()
                if is_friendly:
                    is_top_friendly = any(tf in (name_title + " " + comp_name).upper() for tf in TOP_FRIENDLY_TEAMS)
                    if not is_top_friendly:
                        continue

                # Parsing orario: Esd è nel formato YYYYMMDDHHMMSS UTC
                esd_str = str(ev.get("Esd", ""))
                if len(esd_str) >= 12:
                    try:
                        dt_utc = datetime.datetime.strptime(esd_str[:14], "%Y%m%d%H%M%S").replace(tzinfo=datetime.timezone.utc)
                        dt_local = dt_utc.astimezone(rome_tz)
                        local_time_str = dt_local.strftime("%H:%M")
                        date_str = dt_local.strftime("%d %B %Y")
                    except Exception:
                        local_time_str = "00:00"
                        date_str = now_local.strftime("%d %B %Y")
                else:
                    local_time_str = "00:00"
                    date_str = now_local.strftime("%d %B %Y")

                tourn_label = f"{country}: {comp_name}" if country and country.lower() not in comp_name.lower() else comp_name
                it_channels = _get_suggested_it_channels(tourn_label, name_title)

                title_up = name_title.upper()
                tourn_up = tourn_label.upper()
                is_top = any(w in title_up or w in tourn_up for w in W_TOP)

                event_obj = {
                    "date": date_str,
                    "time": local_time_str,
                    "title": name_title,
                    "sport": "Football",
                    "category": "Football",
                    "tournament": tourn_label,
                    "sources": it_channels,
                    "is_top": is_top
                }
                
                key = (local_time_str, name_title.lower())
                if key not in seen:
                    events.append(event_obj)
                    seen.add(key)

    except Exception as e:
        pass

    events.sort(key=lambda x: x["time"])
    return events

if __name__ == "__main__":
    events = get_sporteventz_schedule()
    print(f"Trovate {len(events)} partite TOP filtrate:")
    for ev in events:
        print(f"[{ev['time']}] ({ev['tournament']}) {ev['title']} -> {[s['name'] for s in ev['sources']]}")
