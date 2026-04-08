
import requests
import re
import json
import base64
import xbmc
import xbmcgui
import xbmcplugin
from .epg_client import EPGClient

# --- PREMIUM (MANDRAKODI SOURCE) --- Archiviato il 2026-03-25
PREMIUM_URL = "https://test34344.herokuapp.com/filter.php"
PREMIUM_UA = "MandraKodi2@@1.1.2@@MandraKodi3@@S63TDC"
PROTECTION_KEY = "amstaff@@"

def list_premium_sport(HANDLE, add_directory_item, FANART=None):
    """Show SPORT premium channels directly (no subfolder)"""
    url = f"{PREMIUM_URL}?numTest=A1A260"
    headers = {"User-Agent": PREMIUM_UA}
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        sections = data.get("channels", [])
        
        for sec in sections:
            name = sec.get("name", "Unknown Group")
            if "SPORT" in name.upper():
                for it in sec.get("items", []):
                    resolve_val = it.get("myresolve", "")
                    if PROTECTION_KEY in resolve_val:
                        payload = resolve_val.split("@@")[1]
                        title = it.get("title", "Canale")
                        clean_title = re.sub(r'\[.*?\]', '', title).strip().upper()
                        
                        if clean_title.endswith("FHD") or " FHD " in clean_title:
                            continue
                            
                        add_directory_item(
                            title, 
                            {"action": "play_premium", "payload": payload, "title": title},
                            is_folder=False,
                            is_playable=True,
                            icon=it.get("thumbnail")
                        )
                
    except Exception as e:
        xbmc.log(f"Error list_premium_sport: {e}", xbmc.LOGERROR)

def list_premium_cinema(HANDLE, add_directory_item):
    """Show Cinema, Intrattenimento, and Bambini channels"""
    url = f"{PREMIUM_URL}?numTest=A1A260"
    headers = {"User-Agent": PREMIUM_UA}
    
    try:
        r = requests.get(url, headers=headers, timeout=10)
        data = r.json()
        sections = data.get("channels", [])
        
        for sec in sections:
            name = sec.get("name", "Unknown Group")
            if "SPORT" not in name.upper():
                 add_directory_item(name, {"action": "list_premium_category", "cat_data": json.dumps(sec)})
                
    except Exception as e:
        xbmc.log(f"Error list_premium_cinema: {e}", xbmc.LOGERROR)

def play_premium(HANDLE, payload, title):
    missing_padding = len(payload) % 4
    if missing_padding:
        payload += '=' * (4 - missing_padding)
        
    try:
        decoded = base64.b64decode(payload).decode('utf-8')
        parts = decoded.split('|')
        
        stream_url = parts[0]
        clearkey = parts[1] if len(parts) > 1 else None
        
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        host = "https://www.nowtv.it"
        headers = f"User-Agent={ua}&Referer={host}/&Origin={host}&verifypeer=false"
        
        list_item = xbmcgui.ListItem(path=stream_url)
        list_item.setInfo('video', {'title': title})
        
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
        xbmc.log(f"Error play_premium: {e}", xbmc.LOGERROR)

def list_epg_entertainment(HANDLE, get_remote_config):
    """Mostra Guida TV Entertainment (Archiviato)"""
    epg = EPGClient()
    epg.get_data()
    
    cfg = get_remote_config()
    ent_channels = cfg.get("entertainment", [])
    
    for ch in ent_channels:
        ch_name = ch["name"]
        epg_info = epg.get_program(ch_name)
        
        if epg_info:
            label = f"[COLOR white][B]{epg_info['start']} - {epg_info['stop']}[/B][/COLOR]  [COLOR yellow][B]{ch_name}[/B][/COLOR] | {epg_info['title']}"
            plot = f"In onda: {epg_info['title']}"
        else:
            label = f"[COLOR gray]{ch_name} (Senza EPG)[/COLOR]"
            plot = "Dati palinsesto non disponibili."
        
        li = xbmcgui.ListItem(label=label)
        li.setInfo('video', {'plot': plot, 'title': label})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url="", listitem=li, isFolder=False)
    
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)
