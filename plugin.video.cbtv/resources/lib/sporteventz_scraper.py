import requests
import re
import datetime
import concurrent.futures
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

# Endpoint ESPN per i principali tornei
ESPN_LEAGUE_SLUGS = [
    ("fifa.world", "FIFA World Cup"),
    ("ita.1", "Serie A"),
    ("uefa.champions", "UEFA Champions League"),
    ("uefa.europa", "UEFA Europa League"),
    ("uefa.ecoconference", "UEFA Conference League"),
    ("ita.coppa_italia", "Coppa Italia"),
    ("eng.1", "Premier League"),
    ("esp.1", "La Liga"),
    ("ger.1", "Bundesliga"),
    ("fra.1", "Ligue 1"),
    ("fifa.friendly", "Amichevole Internazionale"),
    ("club.friendly", "Amichevole Club"),
]

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

def _fetch_espn_league_matches(slug_info):
    slug, default_comp_name = slug_info
    url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    events_found = []
    try:
        resp = requests.get(url, headers=headers, timeout=8, verify=False)
        if resp.status_code != 200:
            return events_found
            
        data = resp.json()
        raw_events = data.get("events", [])
        
        # Fuso orario italiano
        try:
            from zoneinfo import ZoneInfo
            rome_tz = ZoneInfo("Europe/Rome")
        except ImportError:
            rome_tz = datetime.timezone(datetime.timedelta(hours=2))

        now_local = datetime.datetime.now(rome_tz)
        
        for ev in raw_events:
            competitions = ev.get("competitions", [])
            if not competitions:
                continue
                
            comp = competitions[0]
            start_date_iso = comp.get("startDate") or ev.get("date")
            if not start_date_iso:
                continue
                
            # Conversione data in fuso orario italiano
            try:
                dt_utc = datetime.datetime.fromisoformat(start_date_iso.replace("Z", "+00:00"))
                dt_local = dt_utc.astimezone(rome_tz)
            except Exception:
                continue
                
            # Verifichiamo se l'evento è oggi (in ora locale italiana)
            if dt_local.date() != now_local.date():
                continue
                
            # Squadre
            competitors = comp.get("competitors", [])
            if len(competitors) < 2:
                name_title = ev.get("name", "")
            else:
                t1 = competitors[0].get("team", {}).get("displayName", "")
                t2 = competitors[1].get("team", {}).get("displayName", "")
                if t1 and t2:
                    name_title = f"{t1} vs {t2}"
                else:
                    name_title = ev.get("name", "")
                    
            if not name_title:
                continue
                
            # Nome torneo / fase
            league_name = default_comp_name
            note_text = ""
            notes = comp.get("notes", [])
            if notes:
                note_text = notes[0].get("headline", "")
            alt_note = comp.get("altGameNote", "")
            
            tourn_label = alt_note or note_text or league_name
            
            # Filtro keyword vietate (femminili, under)
            combined_text = (tourn_label + " " + name_title).lower()
            if any(kw in combined_text for kw in FORBIDDEN_KEYWORDS):
                continue
                
            # Filtro specifico per le AMICHEVOLI: vogliamo solo Italia, Juventus, o Big Club
            if "friendly" in slug.lower():
                is_top_friendly = any(tf in combined_text.upper() for tf in TOP_FRIENDLY_TEAMS)
                if not is_top_friendly:
                    continue
                    
            local_time_str = dt_local.strftime("%H:%M")
            date_str = dt_local.strftime("%d %B %Y")
            
            # Canali italiani suggeriti
            it_channels = _get_suggested_it_channels(tourn_label, name_title)
            
            # Calcolo flag is_top
            title_up = name_title.upper()
            tourn_up = tourn_label.upper()
            is_top = any(w in title_up or w in tourn_up for w in W_TOP)
            
            events_found.append({
                "date": date_str,
                "time": local_time_str,
                "title": name_title,
                "sport": "Football",
                "category": "Football",
                "tournament": tourn_label,
                "sources": it_channels,
                "is_top": is_top
            })
            
    except Exception:
        pass
        
    return events_found

def get_sporteventz_schedule():
    """
    Recupera l'agenda CALCIO di oggi interrogando le API JSON pubbliche di ESPN in parallelo.
    """
    all_events = []
    seen = set()
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        results = executor.map(_fetch_espn_league_matches, ESPN_LEAGUE_SLUGS)
        for res in results:
            for ev in res:
                key = (ev["time"], ev["title"].lower())
                if key not in seen:
                    all_events.append(ev)
                    seen.add(key)
                    
    all_events.sort(key=lambda x: x["time"])
    return all_events

if __name__ == "__main__":
    events = get_sporteventz_schedule()
    for ev in events:
        print(f"[{ev['time']}] ({ev['tournament']}) {ev['title']} -> {[s['name'] for s in ev['sources']]}")
