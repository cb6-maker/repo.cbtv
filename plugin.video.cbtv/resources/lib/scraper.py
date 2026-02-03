import requests
import re
from urllib.parse import unquote

def get_oasport_events():
    url = "https://www.oasport.it/tag/sport-in-tv-oggi/feed/"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        content = r.text
        
        # Use findall to get all items (usually first 5 is enough)
        items = re.findall(r'<item>(.*?)</item>', content, re.DOTALL)
        if not items: return []
        
        import datetime
        today = datetime.datetime.now()
        months_it = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
        weekday_it = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
        
        current_day_num = f"{today.day}"
        current_month_it = months_it[today.month - 1]
        current_wday_it = weekday_it[today.weekday()]
        
        # Date patterns to match
        current_date_str = f"{current_day_num}\\s+{current_month_it}"
        
        # Days to EXCLUDE (if it's Monday, exclude Sunday, Saturday, etc.)
        other_days = [d for d in weekday_it if d != current_wday_it]
        
        events = []
        for item_content in items[:15]: # Check more items just in case
            title_m = re.search(r'<title>(.*?)</title>', item_content)
            item_title = title_m.group(1).lower() if title_m else ""
            
            # PubDate check: Skip if older than ~36 hours
            pub_m = re.search(r'<pubDate>(.*?)</pubDate>', item_content)
            if pub_m:
                try:
                    # e.g. "Mon, 02 Feb 2026 06:21:56 +0000"
                    pub_str = pub_m.group(1)
                    # Simple check: month and day must be somewhat recent
                    # We can check if the month is correct and day is within [today-1, today]
                    parts = pub_str.split()
                    if len(parts) >= 4:
                        p_day = int(parts[1])
                        p_month_abrv = parts[2] # "Feb", "Jan"...
                        months_map = {"Jan":"gennaio", "Feb":"febbraio", "Mar":"marzo", "Apr":"aprile", "May":"maggio", "Jun":"giugno", "Jul":"luglio", "Aug":"agosto", "Sep":"settembre", "Oct":"ottobre", "Nov":"novembre", "Dec":"dicembre"}
                        p_month_it = months_map.get(p_month_abrv, "")
                        
                        # Strict check: must be current month or very end of previous if it's day 1
                        if p_month_it != current_month_it:
                            # Unless it was yesterday and month changed
                            if not (today.day == 1 and p_day >= 28): 
                                continue
                        # Day check: must be today or yesterday
                        if p_day not in [today.day, (today - datetime.timedelta(days=1)).day]:
                             continue
                except:
                    pass

            # Title pattern check
            is_recent_title = any(x in item_title for x in [current_date_str, "oggi", "stasera"])
            mentions_wrong_day = any(d in item_title for d in other_days)
            
            # If it mentions another day but NOT today's date, skip it
            if mentions_wrong_day and current_date_str not in item_title:
                continue
                
            if not is_recent_title and "calcio" not in item_title:
                continue
            
            text = ""
            for tag in ["content:encoded", "description"]:
                 m = re.search(f'<{tag}>(?:<!\\[CDATA\\[)?(.*?)(?:\\]\\]>)?</{tag}>', item_content, re.DOTALL)
                 if m:
                     text = m.group(1)
                     break
            
            if not text: continue
            
            # CRITICAL: Replace paragraph tags and breaks with real newlines BEFORE stripping
            text = text.replace('</p>', '\n').replace('<p>', '\n')
            text = text.replace('<br />', '\n').replace('<br>', '\n').replace('<br/>', '\n')
            
            # Strip remaining HTML
            text = re.sub(r'<.*?>', '', text)
            text = text.replace('&ndash;', '–').replace('&mdash;', '—').replace('&nbsp;', ' ').replace('&#8211;', '–')
            
            for line in text.split('\n'):
                line = line.strip()
                if not line: continue
                
                # Improved regex: Split by the LAST dash group (en-dash, em-dash, or hyphen surrounded by spaces)
                # This helps when team names contain hyphens (e.g., Brighton-Everton)
                # We look for a time followed by text, then a separator, then more text.
                m = re.search(r'^(\d{1,2}[:\.]\w{2})\s+(.*)', line)
                if m:
                    time_str = m.group(1).replace('.', ':').replace('o', '0').replace('O', '0')
                    rest = m.group(2)
                    
                    # Split at the last occurance of a dash preceded or followed by space, or just an en/em dash
                    # Most OA Sport entries use " – " (en-dash) or " — " (em-dash) as channel separator
                    split_patterns = [r' – ', r' — ', r' - ', r'–', r'—']
                    parts = None
                    for pat in split_patterns:
                        if re.search(pat, rest):
                            parts = re.split(pat, rest)
                            if len(parts) > 1:
                                # Join all but last if there were multiple (though usually it's just one)
                                channels_raw = parts[-1].strip()
                                main_info = (pat.join(parts[:-1])).strip()
                                break
                    
                    if not parts:
                        continue # Could not find separator
                    
                    sport = "Sport"
                    title = main_info
                    
                    # Normalize sport/title
                    if ',' in main_info:
                        s_parts = main_info.split(',', 1)
                        sport = s_parts[0].strip()
                        title = s_parts[1].strip()
                    elif '(' in main_info and main_info.find('(') < main_info.find(')'):
                        s_parts = re.match(r'(.*?)\s*\((.*?)\)(.*)', main_info)
                        if s_parts:
                            sport = s_parts.group(1).strip()
                            title = s_parts.group(2).strip() + s_parts.group(3).strip()
                    
                    # SPECIAL HANDLING FOR SOCCER (and others) with multiple separators
                    # e.g., "CALCIO (Premier League) – Brighton-Everton (diretta tv su...)"
                    if "(diretta" in channels_raw.lower() or "su sky" in channels_raw.lower() or "su dazn" in channels_raw.lower():
                        # If channels_raw looks like it contains teams + channel info in parens
                        # e.g. "Brighton-Everton (diretta tv su Sky)"
                        m_teams = re.match(r'(.*?)\s*\((diretta.*?)\)', channels_raw, re.IGNORECASE)
                        if m_teams:
                            teams = m_teams.group(1).strip()
                            real_channels = m_teams.group(2).strip()
                            if teams:
                                title = f"{title}: {teams}" if title else teams
                                channels_raw = real_channels

                    events.append({
                        "time": time_str,
                        "sport": sport,
                        "title": title.strip(),
                        "channels_raw": channels_raw
                    })
        
        import xbmc
        xbmc.log(f"CDNLive Scraper: Successfully parsed {len(events)} events", xbmc.LOGINFO)
        return events
    except Exception as e:
        import xbmc
        xbmc.log(f"CDNLive Scraper Fatal Error: {str(e)}", xbmc.LOGERROR)
        return []

def map_channels(raw_str, all_cdn_channels):
    """
    Search for mention of channels in the raw string and match them with CDN Live channels.
    """
    found = []
    # Key channel names to look for
    keywords = [
        "Eurosport 1", "Eurosport 2", "Sky Sport Uno", "Sky Sport Arena", 
        "Sky Sport Tennis", "Sky Sport F1", "Sky Sport MotoGP", "Sky Sport Calcio",
        "Sky Sport 251", "Sky Sport 252", "Sky Sport 253", "Sky Sport 254", 
        "Sky Sport 255", "Sky Sport 256", "Sky Sport 257", "Sky Sport 258",
        "Rai 1", "Rai 2", "Rai Sport", "SuperTennis", "DAZN", "Nove", "TNT Sports",
        "BeIN Sports", "ESPN", "Canale 5", "Italia 1", "Rete 4", "TV8", "Prime Video"
    ]
    
    raw_lower = raw_str.lower()
    for kw in keywords:
        if kw.lower() in raw_lower:
            # Try to find a match in all_cdn_channels
            # We look for a suffix match or flexible match
            matches = [ch for ch in all_cdn_channels if kw.lower() in ch.get("name", "").lower()]
            found.extend(matches)
    
    # Deduplicate by URL
    seen = set()
    unique = []
    for f in found:
        if f['url'] not in seen:
            unique.append(f)
            seen.add(f['url'])
    return unique
