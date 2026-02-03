import sys
from urllib.parse import parse_qsl, urlencode
import xbmcgui
import xbmcplugin
import json
import re
import xbmc
from resources.lib.cdnlive import CDNLiveResolver
from resources.lib.scraper import get_oasport_events, map_channels

import xbmcaddon
import os

# Global variables
ADDON = xbmcaddon.Addon()
ADDON_ID = 'plugin.video.cbtv'
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]
resolver = CDNLiveResolver()

# Ensure absolute path for fanart
FANART = os.path.join(ADDON.getAddonInfo('path'), 'fanart.jpg')

def build_url(query):
    return f"{BASE_URL}?{urlencode(query)}"

def add_directory_item(title, query, is_folder=True, icon=None, is_playable=False):
    url = build_url(query)
    list_item = xbmcgui.ListItem(label=title)
    
    # Set default fanart for everything
    art = {'fanart': FANART}
    if icon:
        art['icon'] = icon
        art['thumb'] = icon
    list_item.setArt(art)

    if is_playable:
        list_item.setProperty('IsPlayable', 'true')
    xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=list_item, isFolder=is_folder)

def main_menu():
    xbmcplugin.setContent(HANDLE, 'videos')
    # Diagnostic count
    all_ch = resolver.get_channels()
    online_count = len(all_ch)
    
    add_directory_item(f"Agenda Sportiva (Eventi di Oggi)", {"action": "list_agenda"})
    
    # Canali Sport Italia
    add_directory_item("[COLOR green][B]Canali Sport Italia[/B][/COLOR]", {"action": "list_country_channels", "country": "Italy"})
    
    # NEW: Premium Section (Mandrakodi Source)
    add_directory_item("[COLOR yellow][B]Canali Cinema & Serie TV[/B][/COLOR]", {"action": "list_premium_menu"})
    
    add_directory_item(f"Canali per Sport", {"action": "list_sport_channels_menu"})
    add_directory_item(f"Tutte le TV Live ({online_count} Canali Online)", {"action": "list_countries"})
    
    xbmcplugin.endOfDirectory(HANDLE)

# --- PREMIUM (MANDRAKODI SOURCE) ---

# Hardcoded config (no remote fetch to avoid load-time issues)
PREMIUM_URL = "https://test34344.herokuapp.com/filter.php"
PREMIUM_UA = "MandraKodi2@@1.1.2@@MandraKodi3@@S63TDC"
PROTECTION_KEY = "amstaff@@"

def list_premium_menu():
    import requests
    url = f"{PREMIUM_URL}?numTest=A1A260"
    headers = {"User-Agent": PREMIUM_UA}
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        sections = data.get("channels", [])
        
        for sec in sections:
            name = sec.get("name", "Unknown Group")
            # Filter specifically for the groups requested by the user
            if any(k in name.upper() for k in ["INTRATTENIMENTO", "CINEMA", "BAMBINI"]):
                add_directory_item(name, {"action": "list_premium_category", "cat_data": json.dumps(sec)})
                
    except Exception as e:
        xbmcgui.Dialog().ok("Errore Premium", f"Impossibile caricare i canali Premium: {str(e)}")
        
    xbmcplugin.endOfDirectory(HANDLE)

def list_premium_category(cat_data):
    sec = json.loads(cat_data)
    items = sec.get("items", [])
    
    for it in items:
        # Mandrakodi uses 'myresolve' with protection key
        resolve_val = it.get("myresolve", "")
        if PROTECTION_KEY in resolve_val:
            payload = resolve_val.split("@@")[1]
            title = it.get("title", "Canale")
            add_directory_item(
                title, 
                {"action": "play_premium", "payload": payload, "title": title},
                is_folder=False,
                is_playable=True,
                icon=it.get("thumbnail")
            )
            
    xbmcplugin.endOfDirectory(HANDLE)

def play_premium(payload, title):
    import base64
    
    # Fix padding for base64
    missing_padding = len(payload) % 4
    if missing_padding:
        payload += '=' * (4 - missing_padding)
        
    try:
        decoded = base64.b64decode(payload).decode('utf-8')
        parts = decoded.split('|')
        
        stream_url = parts[0]
        clearkey = parts[1] if len(parts) > 1 else None
        
        # NowTV/Sky uses these headers
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        host = "https://www.nowtv.it"
        headers = f"User-Agent={ua}&Referer={host}/&Origin={host}&verifypeer=false"
        
        list_item = xbmcgui.ListItem(path=stream_url)
        list_item.setInfo('video', {'title': title})
        
        # Set InputStream Adaptive properties
        list_item.setProperty('inputstream', 'inputstream.adaptive')
        if ".mpd" in stream_url:
            list_item.setProperty('inputstream.adaptive.file_type', 'mpd')
            list_item.setMimeType("application/dash+xml")
        elif ".m3u8" in stream_url:
            list_item.setProperty('inputstream.adaptive.file_type', 'hls')
            list_item.setMimeType("application/x-mpegURL")
            
        if clearkey and clearkey != "0000":
            list_item.setProperty('inputstream.adaptive.drm_legacy', f'org.w3.clearkey|{clearkey}')
            
        list_item.setProperty('inputstream.adaptive.stream_headers', headers)
        list_item.setProperty('inputstream.adaptive.manifest_headers', headers)
        
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=list_item)
        
    except Exception as e:
        xbmcgui.Dialog().notification("Errore Play", f"Errore decodifica: {str(e)}", xbmcgui.NOTIFICATION_ERROR)

def debug_api():
    data = resolver.fetch_api("channels")
    if not data:
        xbmcgui.Dialog().ok("Debug API", "API returned NONE or Empty. Check Internet/VPN.")
    else:
        ch_list = data.get("channels", [])
        online = [c for c in ch_list if c.get("status") == "online"]
        xbmcgui.Dialog().ok("Debug API", f"Total: {len(ch_list)}\nOnline: {len(online)}\nUser: {resolver.user}")

# --- AGENDA (SCRAPER) ---

def list_agenda():
    events = get_oasport_events()
    if not events:
        xbmcgui.Dialog().notification("Agenda", "No events found today", xbmcgui.NOTIFICATION_INFO)
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    # User preferred sports: keep 'calcio' to catch all soccer, then filter by league/exclusion
    requested_sports = ["calcio", "tennis", "volley", "pallavolo", "f1", "motor", "motogp"]
    
    # Explicitly exclude these to clean up the agenda
    excluded_keywords = [
        "ciclismo", "scialpinismo", "sci alpino", "biathlon", "rugby", "basket", 
        "atletica", "nuoto", "pallaman", "pallanuoto", "calcio a 5", "futsal",
        "serie b", "serie c", "lega pro", "calcio femminile"
    ]
    
    # Strictly soccer leagues requested by the user + major ones
    important_leagues = [
        "serie a", "la liga", "premier league", "champions league", "europa league", 
        "laliga", "bundesliga", "ligue 1", "league 1", "eredivisie", "liga", "premier"
    ]

    items_added = 0
    # Use a set to prevent showing the exact same event multiple times
    seen_events = set()
    
    for ev in events:
        sport_lower = ev['sport'].lower()
        title_lower = ev['title'].lower()
        event_key = f"{ev['time']}_{ev['sport']}_{ev['title']}"
        
        if event_key in seen_events: continue

        # 1. Check if it's an excluded sport or specifically excluded soccer league
        if any(ex in sport_lower or ex in title_lower for ex in excluded_keywords):
            continue
            
        # 2. Check if it's a requested sport
        is_requested_sport = any(req in sport_lower for req in requested_sports)
        
        # 3. Check if it's one of the requested SOCCER leagues (extra safety)
        is_important_soccer = any(league in title_lower or league in sport_lower for league in important_leagues)
        
        # Special case: F1/MotoGP might be in title
        is_motor_title = any(req in title_lower for req in ["f1", "motogp"])

        # Inclusion logic: 
        # - If it's Calcio, it MUST be an important league
        # - If it's other requested sports, show them
        show_event = False
        if "calcio" in sport_lower:
            if is_important_soccer:
                show_event = True
        elif is_requested_sport or is_motor_title:
            show_event = True

        if show_event:
            title = f"{ev['time']} | {ev['sport']}: {ev['title']}"
            add_directory_item(title, {"action": "resolve_agenda_event", "event_data": json.dumps(ev)}, is_folder=True)
            items_added += 1
            seen_events.add(event_key)
            
    # FALLBACK: If no requested sports found, show all events (but still respect exclusions if possible)
    if items_added == 0:
        for ev in events:
            sport_lower = ev['sport'].lower()
            if not any(ex in sport_lower for ex in excluded_keywords):
                title = f"{ev['time']} | {ev['sport']}: {ev['title']}"
                add_directory_item(title, {"action": "resolve_agenda_event", "event_data": json.dumps(ev)}, is_folder=True)
            
    xbmcplugin.endOfDirectory(HANDLE)

def resolve_agenda_event(event_data):
    ev = json.loads(event_data)
    
    # --- 1. PREMIUM CHANNELS FETCH & MATCH ---
    # --- 1. PREMIUM CHANNELS FETCH & MATCH ---
    try:
        import requests
        required_channels = [c.lower().strip() for c in ev.get('channels_raw', [])]
        
        url = f"{PREMIUM_URL}?numTest=A1A260"
        headers = {"User-Agent": PREMIUM_UA}
        r = requests.get(url, headers=headers, timeout=5)
        data = r.json()
        
        for sec in data.get("channels", []):
            # WHITELIST: Mostra SOLO le sezioni SPORT (invece di blacklist)
            section_name = sec.get("name", "").upper()
            if "SPORT" not in section_name:
                continue  # Salta tutto ciò che non ha "SPORT" nel nome
                
            for p_item in sec.get("items", []):
                p_title = p_item.get("title", "")
                p_title_clean = p_title.replace("[COLOR lime]", "").replace("[/COLOR]", "").strip().lower()
                
                # MATCHING MIGLIORATO (l'unica modifica necessaria)
                is_match = False
                for req in required_channels:
                    # Exact match
                    if req == p_title_clean:
                        is_match = True
                        break
                    # Partial match con controllo parole intere
                    if req in p_title_clean:
                        req_words = set(req.split())
                        title_words = set(p_title_clean.split())
                        if req_words.issubset(title_words):
                            is_match = True
                            break
                
                if is_match:
                    resolve_val = p_item.get("myresolve", "")
                    if PROTECTION_KEY in resolve_val:
                        payload = resolve_val.split("@@")[1]
                        display_title = f"[COLOR gold][PREMIUM][/COLOR] {p_title.replace('[COLOR lime]', '').replace('[/COLOR]', '')}"
                        
                        add_directory_item(
                            display_title, 
                            {"action": "play_premium", "payload": payload, "title": display_title},
                            is_folder=False,
                            is_playable=True,
                            icon=p_item.get("thumbnail")
                        )

    except Exception as e:
        # Silently fail on premium fetch to allow standard channels to load
        pass

    # --- 2. STANDARD CHANNELS (CDNLive) ---
    all_channels = resolver.get_channels()
    
    sport_kw = ev['sport'].lower()
    search_text = ev['title'].lower()
    
    # Extract team/athlete keywords
    keywords = re.split(r'[-–—:,\s]+', search_text)
    keywords = [kw for kw in keywords if len(kw) > 3]
    
    # 1. High Priority: Channels explicitly mentioned OR matching team names
    priority_matches = map_channels(ev['channels_raw'], all_channels)
    
    if keywords:
        for ch in all_channels:
            name = ch.get("name", "").lower()
            if any(kw in name for kw in keywords):
                priority_matches.append(ch)

    # 2. Medium Priority: Jolly matches based on sport context
    jolly_matches = []
    
    # Define what to include and what to EXCLUDE based on sport
    include_kws = []
    exclude_kws = []
    
    if any(s in sport_kw for s in ["calcio", "soccer"]):
        include_kws = ["sky sport", "bein", "dazn", "tnt sport", "sport tv", "astro", "supersport", "eleven", "canal+", "ziggo", "premier", "la liga"]
        exclude_kws = ["tennis", "f1", "moto", "golf", "cricket", "rugby", "nba", "basket", "racing", "volleyball"]
        # Special handling: for soccer, we want "Sky Sport Football", "Sky Sport Calcio", or just "Sky Sport 1"
    elif "tennis" in sport_kw:
        include_kws = ["tennis", "euro sport", "eurosport", "sky sport tennis", "beIN sport"]
        exclude_kws = ["football", "calcio", "f1", "motor", "golf", "nba"]
    elif any(s in sport_kw for s in ["f1", "motor", "moto"]):
        include_kws = ["sky sport f1", "sky sport motogp", "dazn f1", "motor", "race", "servus"]
        exclude_kws = ["calcio", "football", "tennis", "golf", "basket"]
    else:
        # Default fallback
        include_kws = ["sky sport", "euro sport", "eurosport"]

    for ch in all_channels:
        name = ch.get("name", "").lower()
        
        # Check if it's a potential broadcaster match
        if any(ikw in name for ikw in include_kws):
            # STRICT EXCLUSION: If it's a soccer match and it says "Tennis", skip it
            if any(ekw in name for ekw in exclude_kws):
                continue
            
            # ANTI-SPAM: Limit numbered channels (Sky Sport 3, 4... beIN 5, 6...)
            # unless it's a priority match already
            is_generic = True
            if any(kw in name for kw in keywords): 
                is_generic = False
            
            if is_generic:
                # Only keep main channels (1, 2) or unnumbered ones
                # Skip if it contains numbers from 3 to 251 (251+ are usually backup/event channels)
                if any(f" {n}" in name for n in range(3, 251)):
                    continue
                # Also skip specific numbered sub-channels like "beIN 4", "Sky 5" etc
                if re.search(r'\s[3-9]\b', name) or re.search(r'[a-z][3-9]\b', name):
                    continue

            jolly_matches.append(ch)

    # Combine and Deduplicate
    all_found = priority_matches + jolly_matches
    seen_urls = set()
    seen_names = set()
    unique_matches = []
    
    for m in all_found:
        m_url = m.get('url')
        m_id = f"{m.get('code')}_{m.get('name')}".lower()
        if m_url not in seen_urls and m_id not in seen_names:
            unique_matches.append(m)
            seen_urls.add(m_url)
            seen_names.add(m_id)

    # Group by Country
    by_country = {}
    for ch in unique_matches:
        country = ch.get('code', '??').upper()
        if country not in by_country: by_country[country] = []
        by_country[country].append(ch)

    sorted_countries = sorted(by_country.keys(), key=lambda x: (x != 'IT', x))

    for country in sorted_countries:
        if len(sorted_countries) > 1:
            add_directory_item(f"[COLOR yellow][B]--- {country} CHANNELS ---[/B][/COLOR]", {"action": "ignore"}, is_folder=False)
            
        for ch in by_country[country]:
            add_directory_item(
                f"    {ch.get('name')}",
                {"action": "play_internal", "url": ch.get("url"), "title": ch.get("name")},
                is_folder=False,
                is_playable=True,
                icon=ch.get("image")
            )
    
    if not unique_matches:
        xbmcgui.Dialog().notification("Guide", "No channels found for this event", xbmcgui.NOTIFICATION_INFO)
    
    xbmcplugin.endOfDirectory(HANDLE)

# --- SOCCER (DIRECT) ---

def list_soccer():
    data = resolver.get_sports_categories()
    # The API uses "Soccer" (Capitalized)
    events = data.get("Soccer", [])
    if not events:
         events = data.get("soccer", [])
    
    soccer_whitelist = ["serie a", "premier league", "la liga", "champions league", "europa league", "laliga", "serie b", "ligue 1"]
    tournaments = {}
    for ev in events:
        tourn = ev.get("tournament", "Other")
        tourn_lower = tourn.lower()
        if any(req in tourn_lower for req in soccer_whitelist):
            if tourn not in tournaments: tournaments[tourn] = []
            tournaments[tourn].append(ev)
    
    for tourn in sorted(tournaments.keys()):
        add_directory_item(tourn, {"action": "list_tournament_matches", "category": "Soccer", "tournament": tourn})
    
    if not tournaments:
         xbmcgui.Dialog().notification("Soccer", "No whitelisted leagues live now", xbmcgui.NOTIFICATION_INFO)
         
    xbmcplugin.endOfDirectory(HANDLE)

def list_tournament_matches(category, tournament):
    data = resolver.get_sports_categories()
    # Handle category case sensitivity
    events = data.get("Soccer", [])
    if not events: events = data.get("soccer", [])
    
    filtered = [ev for ev in events if ev.get("tournament") == tournament]
    
    for ev in filtered:
        # Check if at least one channel in the event is online (if status is available)
        # The API doesn't always show status inside event channels, but we can try
        online_channels = [ch for ch in ev.get("channels", [])] 
        # Since status is missing inside event channels, we'll try to match name with main list
        # OR we just show them if they exist.
        
        if online_channels:
            title = f"{ev.get('time', 'Live')} - {ev.get('homeTeam')} vs {ev.get('awayTeam')}"
            add_directory_item(title, {"action": "resolve_match_menu", "match_data": json.dumps(ev)}, is_folder=True)
    xbmcplugin.endOfDirectory(HANDLE)

# --- CHANNELS BY SPORT ---

def list_sport_channels_menu():
    add_directory_item("Calcio", {"action": "list_sport_channels", "sport": "calcio"})
    add_directory_item("Tennis", {"action": "list_sport_channels", "sport": "tennis"})
    add_directory_item("Motori (F1/MotoGP)", {"action": "list_sport_channels", "sport": "motor"})
    add_directory_item("Volley", {"action": "list_sport_channels", "sport": "volley"})
    xbmcplugin.endOfDirectory(HANDLE)

def list_sport_channels(sport):
    all_channels = resolver.get_channels()
    sport_keywords = {
        "calcio": ["calcio", "football", "soccer", "serie a", "premier", "liga", "bein", "sky sport calcio", "dazn", "astro", "supersport", "sport tv"],
        "tennis": ["tennis", "euro sport", "eurosport", "supertennis", "tsn", "polsat"],
        "motor": ["f1", "motogp", "motor", "racing", "servus"],
        "volley": ["volley", "pallavolo", "polsat", "trt", "vbtv", "rai sport"]
    }
    kws = sport_keywords.get(sport, [])
    found = []
    seen = set()
    for ch in all_channels:
        name = ch.get("name", "").lower()
        if any(kw in name for kw in kws):
            # De-duplicate
            ch_id = f"{ch.get('code')}_{ch.get('name')}".lower()
            if ch_id not in seen:
                found.append(ch)
                seen.add(ch_id)
            
    for ch in sorted(found, key=lambda x: x.get('name')):
        add_directory_item(
            f"[{ch.get('code','??').upper()}] {ch.get('name')}",
            {"action": "play_internal", "url": ch.get("url"), "title": ch.get("name")},
            is_folder=False,
            is_playable=True,
            icon=ch.get("image")
        )
    xbmcplugin.endOfDirectory(HANDLE)

# --- LIVE TV ---

def list_countries():
    grouped = resolver.get_channels_grouped()
    for country in sorted(grouped.keys()):
        add_directory_item(country, {"action": "list_country_channels", "country": country})
    xbmcplugin.endOfDirectory(HANDLE)

def list_country_channels(country_name):
    # 1. If Italy, add Premium Sport channels from Mandrakodi
    if country_name.lower() == "italy":
        import requests
        url = f"{PREMIUM_URL}?numTest=A1A260"
        headers = {"User-Agent": PREMIUM_UA}
        try:
            r = requests.get(url, headers=headers, timeout=10)
            data = r.json()
            sections = data.get("channels", [])
            for sec in sections:
                if "SPORT" in sec.get("name", "").upper():
                    items = sec.get("items", [])
                    for it in items:
                        resolve_val = it.get("myresolve", "")
                        if PROTECTION_KEY in resolve_val:
                            payload = resolve_val.split("@@")[1]
                            title = it.get("title", "Canale")
                            # Mark as Premium for the user
                            title = title.replace("[COLOR lime]", "[COLOR gold][PREMIUM] [/COLOR][COLOR lime]")
                            add_directory_item(
                                title, 
                                {"action": "play_premium", "payload": payload, "title": title},
                                is_folder=False,
                                is_playable=True,
                                icon=it.get("thumbnail")
                            )
        except:
            pass # Fallback to standard channels if remote fails

    # 2. Add standard channels from CDNLive
    grouped = resolver.get_channels_grouped()
    channels = grouped.get(country_name, [])
    for ch in channels:
        add_directory_item(
            ch.get("name", "Unknown"),
            {"action": "resolve_menu", "url": ch.get("url"), "title": ch.get("name")},
            is_folder=True,
            icon=ch.get("image")
        )
    xbmcplugin.endOfDirectory(HANDLE)

# --- HELPERS ---

def resolve_match_menu(match_data):
    ev = json.loads(match_data)
    channels = ev.get("channels", [])
    for ch in channels:
        add_directory_item(
            f"[COLOR gold]PLAY STREAM[/COLOR] - {ch.get('channel_name')}",
            {"action": "play_internal", "url": ch.get("url"), "title": ch.get("channel_name")},
            is_folder=False,
            is_playable=True,
            icon=ch.get("image")
        )
    xbmcplugin.endOfDirectory(HANDLE)

def resolve_menu(url, title):
    add_directory_item("[COLOR gold]PLAY STREAM[/COLOR]", {"action": "play_internal", "url": url, "title": title}, is_folder=False, is_playable=True)
    xbmcplugin.endOfDirectory(HANDLE)

def play_internal(url, title):
    resolved_url = resolver.resolve(url)
    if not resolved_url:
        xbmcgui.Dialog().notification("Error", "Could not resolve stream", xbmcgui.NOTIFICATION_ERROR)
        return
    ua = resolver.ua
    final_path = f"{resolved_url}|connection=keepalive&User-Agent={ua}&Referer={url}"
    list_item = xbmcgui.ListItem(path=final_path)
    list_item.setInfo('video', {'title': title})
    list_item.setProperty('inputstream', 'inputstream.ffmpegdirect')
    list_item.setProperty('inputstream.ffmpegdirect.manifest_type', 'hls')
    list_item.setProperty('inputstream.ffmpegdirect.is_realtime_stream', 'true')
    xbmcplugin.setResolvedUrl(HANDLE, True, listitem=list_item)

if __name__ == '__main__':
    params = dict(parse_qsl(sys.argv[2][1:]))
    action = params.get('action')
    if not action: main_menu()
    elif action == 'list_agenda': list_agenda()
    elif action == 'debug_api': debug_api()
    elif action == 'resolve_agenda_event': resolve_agenda_event(params.get('event_data'))
    elif action == 'list_soccer': list_soccer()
    elif action == 'list_tournament_matches': list_tournament_matches(params.get('category'), params.get('tournament'))
    elif action == 'list_sport_channels_menu': list_sport_channels_menu()
    elif action == 'list_sport_channels': list_sport_channels(params.get('sport'))
    elif action == 'list_countries': list_countries()
    elif action == 'list_country_channels': list_country_channels(params.get('country'))
    elif action == 'list_premium_menu': list_premium_menu()
    elif action == 'list_premium_category': list_premium_category(params.get('cat_data'))
    elif action == 'play_premium': play_premium(params.get('payload'), params.get('title'))
    elif action == 'resolve_match_menu': resolve_match_menu(params.get('match_data'))
    elif action == 'resolve_menu': resolve_menu(params.get('url'), params.get('title'))
    elif action == 'play_internal': play_internal(params.get('url'), params.get('title'))
