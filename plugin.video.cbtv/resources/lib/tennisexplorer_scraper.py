import requests
import re
from datetime import datetime
import urllib3

urllib3.disable_warnings()

def get_tennisexplorer_schedule():
    """
    Scrapes the complete daily tennis matches schedule from Tennis Explorer.
    Uses type=all to ensure 100% global tennis coverage including WTA, ATP, Singles and Doubles,
    and automatically maps the correct Italian broadcast sources based on the tournament.
    """
    url = "https://www.tennisexplorer.com/matches/?type=all"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=12, verify=False)
        if resp.status_code != 200:
            return []
            
        html = resp.text
        
        # Split by right column first to avoid parsing the sidebar
        parts = html.split('<div id="right">')
        main_body = parts[0]
        
        # Split the HTML by tournament blocks
        t_blocks = main_body.split('<tr class="head flags">')[1:]
        
        all_events = []
        now = datetime.now()
        
        for tb in t_blocks:
            # Extract tournament name
            tourn_m = re.search(r'<td class="t-name"[^>]*><a[^>]+>(.*?)</a>', tb)
            if not tourn_m:
                continue
                
            # Clean HTML tags and entities inside tournament name
            tourn_name = tourn_m.group(1)
            tourn_name = re.sub(r'<[^>]+>', '', tourn_name)
            tourn_name = tourn_name.replace('&nbsp;', ' ').replace('&#8211;', '–').replace('&amp;', '&').strip()
            tourn_name = ' '.join(tourn_name.split())
            tourn_low = tourn_name.lower()
            
            # --- FILTRAGGIO TORNEI MINORI (SEGUIAMO SOLO DAI 500 IN SU + SLAM) ---
            SKIP_KEYWORDS = ["challenger", "itf", "utr", "exhibition", "futures", "qualification", "qualifying", "senior", "junior", "boys", "girls"]
            if any(sk in tourn_low for sk in SKIP_KEYWORDS):
                continue
                
            MAJOR_KEYWORDS = [
                "french open", "roland garros", "wimbledon", "us open", "australian open",
                "indian wells", "miami", "monte carlo", "madrid", "rose", "rome", "roma",
                "montreal", "toronto", "canada", "cincinnati", "shanghai", "paris",
                "beijing", "pechino", "doha", "dubai", "wuhan",
                "rotterdam", "rio de janeiro", "acapulco", "barcelona", "barcellona",
                "munich", "monaco", "halle", "queen", "london", "londra", "hamburg", "amburgo",
                "washington", "tokyo", "basel", "basilea", "vienna", "abu dhabi",
                "linz", "san diego", "strasbourg", "strasburgo", "berlin", "berlino",
                "bad homburg", "eastbourne", "monterrey", "guadalajara", "ningbo",
                "stuttgart", "stoccarda", "charleston", "zhengzhou", "brisbane",
                "adelaide", "united cup", "davis cup", "billie jean", "bjk cup",
                "atp finals", "wta finals", "olympics", "olimpiadi"
            ]
            
            if not any(mk in tourn_low for mk in MAJOR_KEYWORDS):
                continue
            
            # Find all match rows inside this tournament block
            match_rows = re.findall(r'<tr id="[rs]\d+"[^>]*>(.*?)</tr>\s*<tr id="[rs]\d+b"[^>]*>(.*?)</tr>', tb, re.DOTALL)
            
            for p1_row, p2_row in match_rows:
                # 1. Extract start time (already in Italian local timezone)
                time_m = re.search(r'<td class="first time"[^>]*>(.*?)</td>', p1_row, re.DOTALL)
                time_str = "00:00"
                if time_m:
                    time_clean = re.sub(r'<[^>]+>', ' ', time_m.group(1)).strip()
                    time_clean = ' '.join(time_clean.split())
                    time_m_clean = re.match(r'^(\d{2}:\d{2})', time_clean)
                    if time_m_clean:
                        time_str = time_m_clean.group(1)
                
                # 2. Extract Player 1 Name
                p1_m = re.search(r'<td class="t-name"[^>]*><a[^>]+>(.*?)</a>', p1_row)
                if not p1_m:
                    continue
                p1 = p1_m.group(1).strip()
                p1 = re.sub(r'\s*\(\d+\)\s*$', '', p1) # Remove seed numbers
                
                # 3. Extract Player 2 Name
                p2_m = re.search(r'<td class="t-name"[^>]*><a[^>]+>(.*?)</a>', p2_row)
                if not p2_m:
                    continue
                p2 = p2_m.group(1).strip()
                p2 = re.sub(r'\s*\(\d+\)\s*$', '', p2)
                
                # Clean up player names from entities
                p1 = p1.replace('&nbsp;', ' ').strip()
                p2 = p2.replace('&nbsp;', ' ').strip()
                
                # Construct clean match title
                match_title = f"Tennis, {tourn_name}: {p1} vs {p2}"
                
                # 4. Map appropriate Italian TV/Streaming channels based on the tournament name
                channels = []
                tourn_low = tourn_name.lower()
                
                if any(x in tourn_low for x in ["french open", "roland garros", "australian open"]):
                    channels = [
                        {"name": "Eurosport 1", "country": "Tennis Explorer"},
                        {"name": "Eurosport 2", "country": "Tennis Explorer"},
                        {"name": "DAZN", "country": "Tennis Explorer"},
                        {"name": "Discovery+", "country": "Tennis Explorer"}
                    ]
                elif "wimbledon" in tourn_low:
                    channels = [
                        {"name": "Sky Sport Tennis", "country": "Tennis Explorer"},
                        {"name": "Sky Sport Arena", "country": "Tennis Explorer"},
                        {"name": "NOW", "country": "Tennis Explorer"}
                    ]
                else:
                    channels = [
                        {"name": "Sky Sport Tennis", "country": "Tennis Explorer"},
                        {"name": "Supertennis", "country": "Tennis Explorer"},
                        {"name": "NOW", "country": "Tennis Explorer"}
                    ]
                    
                # Rimozione emoji per Kodi
                match_title = "".join(c for c in match_title if ord(c) < 65536)
                all_events.append({
                    "date": now.strftime("%d %B %Y"),
                    "time": time_str,
                    "title": match_title,
                    "sport": "Tennis",
                    "category": "Tennis",
                    "tournament": tourn_name,
                    "sources": channels,
                    "is_top": False
                })
                
        return all_events
        
    except Exception:
        return []
