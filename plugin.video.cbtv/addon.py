import sys
from urllib.parse import parse_qsl, urlencode
import xbmcgui
import xbmcplugin
import json
import re
import xbmc
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import xbmcvfs
import gzip
# from resources.lib.scraper import get_oasport_events # Rimosso in favore di EPG reale
from resources.lib.epg_client import EPGClient
from resources.lib.eagle_stalker import EagleStalkerClient
import time
import threading
import hashlib
import random

import xbmcaddon
import os
import requests
import ssl
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context
from urllib.parse import urlsplit, parse_qs, quote

LIB_PATH = os.path.join(os.path.dirname(__file__), 'lib')
if LIB_PATH not in sys.path:
    sys.path.insert(0, LIB_PATH)

# Global variables
ADDON = xbmcaddon.Addon()
ADDON_ID = 'plugin.video.cbtv'
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.sky.it",
    "Referer": "https://www.sky.it/"
}
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]

# Sorgenti Premium (Mimetizzate)
_P_URL = "https://test34344.herokuapp.com/filter.php"
_P_UA = "MandraKodi2@@1.2.80@@MandraKodi3@@S63TDC"
_P_KEY = "my_secret_key"

def _sc_decode(data_b64, key):
    try:
        data = base64.b64decode(data_b64)
        key_bytes = key.encode()
        out = bytearray()
        for i in range(len(data)):
            out.append(data[i] ^ key_bytes[i % len(key_bytes)])
        return out.decode("utf-8")
    except: return ""

SC_DOMAIN = "streamingcommunityz.nl"
CIPHERS = "ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-AES256-GCM-SHA384"

class SCAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context(ciphers=CIPHERS)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
        super().init_poolmanager(*args, **kwargs)


        
def get_scraper():
    """Create a requests.Session with custom SSL adapter"""
    try:
        session = requests.Session()
        session.mount('https://', SCAdapter())
        session.headers.update({
            'User-Agent': HEADERS["User-Agent"],
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3',
            'Accept-Encoding': 'gzip',
        })
        session.verify = False
        return session
    except Exception as e:
        xbmc.log(f"[CBTV] SC Session error: {e}", xbmc.LOGERROR)
        return None

def extract_data_page(html):
    match = re.search(r'data-page="([^"]+)"', html)
    if match:
        data_json_str = match.group(1).replace('&quot;', '"')
        try: return json.loads(data_json_str)
        except: pass
    return None

def sc_search(query, filter_type=None):
    scraper = get_scraper()
    if not scraper: return []
    url = f"https://{SC_DOMAIN}/it/search?q={quote(query)}"
    try:
        r = scraper.get(url, timeout=10)
        data = extract_data_page(r.text)
        if not data: return []
        titles = data.get('props', {}).get('titles', [])
        results = []
        for i in titles:
            thumb = ''
            if i.get('images'):
                img_obj = next((img for img in i['images'] if img.get('type') == 'poster'), None)
                if not img_obj: img_obj = i['images'][0]
                if img_obj and img_obj.get('filename'):
                    thumb = f"https://cdn.{SC_DOMAIN}/images/{img_obj['filename']}"
            
            type_val = "tvshow" if "tv" in i.get('type','').lower() else "movie"
            if filter_type and type_val != filter_type: continue
                
            results.append({"id": i.get('id'), "title": i.get('name') or i.get('title'), "slug": i.get('slug'), "type": type_val, "thumb": thumb})
        return results
    except Exception as e:
        xbmc.log(f"[CBTV] SC_SEARCH Error: {e}", xbmc.LOGERROR)
        return []

def sc_get_seasons_episodes(sc_id, slug):
    scraper = get_scraper()
    if not scraper: return []
    url = f"https://{SC_DOMAIN}/it/titles/{sc_id}-{slug}"
    try:
        r = scraper.get(url, timeout=10)
        data = extract_data_page(r.text)
        if not data: return []
        seasons = data.get('props', {}).get('title', {}).get('seasons', [])
        all_s = []
        for s in seasons:
            s_num = s['number']
            s_url = f"{url}/season-{s_num}"
            sr = scraper.get(s_url, timeout=10)
            sd = extract_data_page(sr.text)
            if sd:
                eps = sd.get('props', {}).get('loadedSeason', {}).get('episodes', [])
                parsed_eps = []
                for e in eps:
                    thumb = ''
                    if e.get('images'):
                        img_obj = next((img for img in e['images'] if img.get('type') == 'cover'), None)
                        if not img_obj: img_obj = e['images'][0]
                        if img_obj and img_obj.get('filename'):
                            thumb = f"https://cdn.{SC_DOMAIN}/images/{img_obj['filename']}"
                    
                    parsed_eps.append({"number": e['number'], "title": e.get('name', f"Ep {e['number']}"), "id": e['id'], "plot": e.get('plot', ''), "thumb": thumb})
                
                all_s.append({"number": s_num, "episodes": parsed_eps})
        return all_s
    except: return []

def sc_resolve(sc_id, ep_id=None):
    import html
    scraper = get_scraper()
    if not scraper: return None
    iframe_url = f"https://{SC_DOMAIN}/it/iframe/{sc_id}"
    if ep_id: iframe_url += f"?episode_id={ep_id}"
    try:
        r = scraper.get(iframe_url, timeout=15)
        m = re.search(r'embed_url="([^"]+)', r.text) or re.search(r'<iframe [^>]+src="([^"]+)', r.text)
        if not m: m = re.search(r'src="(https://vixcloud\.co/embed/[^"]+)"', r.text)
        if not m: return None
        raw_embed_url = m.group(1).replace('&amp;', '&')
        embed_url = html.unescape(raw_embed_url)
        r2 = scraper.get(embed_url, headers={'Referer': iframe_url}, timeout=15)
        m2 = re.search(r"window\.masterPlaylist\s+=\s+{[^{]+({[^}]+}),\s+url:\s+'([^']+).*?canPlayFHD\s*=\s*(true|false)", r2.text, re.DOTALL)
        if not m2: return None
        params_str = m2.group(1)
        playlist_base = m2.group(2)
        canPlayFHD = m2.group(3)
        import ast
        try: masterPlaylistParams = ast.literal_eval(params_str)
        except: masterPlaylistParams = {}
        if canPlayFHD == 'true': masterPlaylistParams['h'] = 1
        parsed_embed = urlsplit(embed_url)
        embed_params = parse_qs(parsed_embed.query)
        embed_params = {k: v[0] for k, v in embed_params.items()}
        if 'b' in embed_params or 'ub' in embed_params: masterPlaylistParams['b'] = 1
        split_playlist = urlsplit(playlist_base)
        playlist_params = dict(parse_qsl(split_playlist.query))
        masterPlaylistParams.update(playlist_params)
        final_url = f"{split_playlist.scheme}://{split_playlist.netloc}{split_playlist.path}?{urlencode(masterPlaylistParams)}"
        return final_url, iframe_url
    except: return None

def sc_save_library(title, item_type, sc_id, slug=None, thumb=None):
    try: base_path = xbmcvfs.translatePath('special://profile/addon_data/plugin.video.cbtv/Library')
    except: base_path = xbmc.translatePath('special://profile/addon_data/plugin.video.cbtv/Library')
        
    stitle = re.sub(r'[\\/*?:"<>|]', "", title).strip()
    plugin_base = f"plugin://{ADDON_ID}"
    
    if item_type == 'movie':
        tdir = os.path.join(base_path, 'Movies', stitle)
        os.makedirs(tdir, exist_ok=True)
        with open(os.path.join(tdir, f"{stitle}.strm"), 'w', encoding='utf-8') as f:
            f.write(f"{plugin_base}/?action=play_sc&sc_id={sc_id}")
            
        if thumb:
            with open(os.path.join(tdir, f"{stitle}.nfo"), 'w', encoding='utf-8') as f:
                f.write(f"<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<movie>\n  <title>{title}</title>\n  <thumb>{thumb}</thumb>\n</movie>")
                
    else:
        seasons = sc_get_seasons_episodes(sc_id, slug)
        tdir = os.path.join(base_path, 'TVShows', stitle)
        os.makedirs(tdir, exist_ok=True)
        
        if thumb:
            with open(os.path.join(tdir, "tvshow.nfo"), 'w', encoding='utf-8') as f:
                f.write(f"<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<tvshow>\n  <title>{title}</title>\n  <thumb>{thumb}</thumb>\n</tvshow>")
                
        for s in seasons:
            sdir = os.path.join(tdir, f"Season {s['number']}")
            os.makedirs(sdir, exist_ok=True)
            for e in s['episodes']:
                prefix = f"S{str(s['number']).zfill(2)}E{str(e['number']).zfill(2)}"
                clean_ep_title = re.sub(r'[\\/*?:"<>|]', "", e['title']).strip()
                sep = f"{prefix} - {clean_ep_title}.strm"
                with open(os.path.join(sdir, sep), 'w', encoding='utf-8') as f:
                    f.write(f"{plugin_base}/?action=play_sc&sc_id={sc_id}&ep_id={e['id']}")
                    
                if e.get('thumb'):
                    nfo_name = f"{prefix} - {clean_ep_title}.nfo"
                    safe_plot = e.get('plot', '').replace('<', '&lt;').replace('>', '&gt;')
                    with open(os.path.join(sdir, nfo_name), 'w', encoding='utf-8') as f:
                        f.write(f"<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n<episodedetails>\n  <title>{e['title']}</title>\n  <plot>{safe_plot}</plot>\n  <thumb>{e['thumb']}</thumb>\n</episodedetails>")
                        
    xbmcgui.Dialog().notification("Libreria", f"{stitle} salvato con successo!")
    xbmc.executebuiltin('UpdateLibrary(video)')


# Ensure absolute path for fanart
FANART = os.path.join(ADDON.getAddonInfo('path'), 'fanart.jpg')

# URL config remota su GitHub Pages
REMOTE_CONFIG_URL = "https://cb6-maker.github.io/repo.cbtv/channels_config.json"

# Cache config per evitare download multipli nella stessa sessione
_cached_config = None

def get_remote_config():
    """Scarica la config remota da GitHub. Se fallisce o se la locale è più recente (test), usa i default hardcoded."""
    global _cached_config
    if _cached_config is not None:
        return _cached_config
    # Scarico config remota da GitHub
    import requests
    try:
        xbmc.log(f"[CBTV] Scaricando config da {REMOTE_CONFIG_URL}", xbmc.LOGINFO)
        r = requests.get(REMOTE_CONFIG_URL, headers=HEADERS, timeout=5)
        if r.status_code == 200:
            remote_cfg = r.json()
            # Se la remota è effettivamente più nuova, usala
            if remote_cfg.get("version", 0) > DEFAULT_CONFIG.get("version", 0):
                _cached_config = remote_cfg
                xbmc.log(f"[CBTV] Config remota caricata (v{_cached_config.get('version', '?')})", xbmc.LOGINFO)
                return _cached_config
    except Exception as e:
        xbmc.log(f"[CBTV] Config remota non disponibile: {e}. Uso defaults.", xbmc.LOGWARNING)
    
    _cached_config = DEFAULT_CONFIG
    return _cached_config

# Default hardcoded (usato se GitHub non risponde)
# Default hardcoded (usato se GitHub non risponde)
DEFAULT_CONFIG = {
    "version": 54,
    "sky_it_api_base": "https://apid.sky.it/gtv/v1/events",
    "mediahosting": {
        "embed_base_url": "https://mediahosting.space/embed/player?stream=",
        "no_register_param": "&no_register=true",
        "referer": "https://mediahosting.space/",
        "source_regex": "<source src=\"(.*?)\"",
        "channels": [
            {"name": "Sky Sport 24", "code": "334", "sky_id": 9094},
            {"name": "Sky Sport Uno", "code": "326", "sky_id": 9097},
            {"name": "Sky Sport Calcio", "code": "333", "sky_id": 9113},
            {"name": "Sky Sport Arena", "code": "331", "sky_id": 9093},
            {"name": "Sky Sport Max", "code": "332", "sky_id": 9103},
            {"name": "Sky Sport Tennis", "code": "329", "sky_id": 11237},
            {"name": "Sky Sport F1", "code": "327", "sky_id": 9096},
            {"name": "Sky Sport MotoGP", "code": "330", "sky_id": 9102},
            {"name": "Sky Sport Basket", "code": "335", "sky_id": 9116},
            {"name": "Sky Sport Golf", "code": "237", "sky_id": 10254},
            {"name": "Sky Sport Mix", "code": "337", "sky_id": 12345},
            {"name": "DAZN 1", "code": "325", "sky_id": 11402}
        ]
    },
    "freeshot_v3": {
        "player_base_url": "https://lovetier.bz/player/",
        "stream_base_url": "https://beautifulpeople.lovecdn.ru/",
        "stream_path": "/tracks-v1a1/mono.m3u8",
        "referer": "https://lovetier.bz/",
        "token_regex": "currentToken: \"([^\"]+)\"",
        "channels": [
            {"name": "Sky Sport Max", "code": "715", "sky_id": 9103},
            {"name": "Sky Sport Mix", "code": "700", "sky_id": 12345}
        ]
    },
    "international_sport_fs": {
        "Arabia (beIN)": [
            {"name": "beIN Arabia 1", "code": "beINAR1"},
            {"name": "beIN Arabia 2", "code": "beINAR2"},
            {"name": "beIN Arabia 3", "code": "beINAR3"},
            {"name": "beIN Arabia 4", "code": "beINAR4"},
            {"name": "beIN Arabia 5", "code": "beINAR5"},
            {"name": "beIN Arabia 6", "code": "beINAR6"},
            {"name": "beIN Arabia 7", "code": "beINAR7"},
            {"name": "beIN Arabia 8", "code": "beINAR8"},
            {"name": "beIN Arabia 9", "code": "beINAR9"}
        ],
        "Croazia (Arena)": [
            {"name": "Arena Sport 1 HR", "code": "ARENASPORT1HR"},
            {"name": "Arena Sport 2 HR", "code": "ARENASPORT2HR"},
            {"name": "Arena Sport 3 HR", "code": "ARENASPORT3HR"},
            {"name": "Arena Sport 4 HR", "code": "ARENASPORT4HR"},
            {"name": "Arena Sport 5 HR", "code": "ARENASPORT5HR"},
            {"name": "Arena Sport 6 HR", "code": "ARENASPORT6HR"},
            {"name": "Arena Sport 7 HR", "code": "ARENASPORT7HR"},
            {"name": "Arena Sport 8 HR", "code": "ARENASPORT8HR"}
        ],
        "Regno Unito (TNT)": [
            {"name": "TNT Sports 1 UK", "code": "TNT1UK"},
            {"name": "TNT Sports 2 UK", "code": "tntsports2"},
            {"name": "TNT Sports 3 UK", "code": "tntsports3"},
            {"name": "TNT Sports 4 UK", "code": "tntsports4"}
        ],
        "Francia (beIN)": [
            {"name": "BeIN Sports 1 FR", "code": "BEINSPORT1FR"},
            {"name": "BeIN Sports 2 FR", "code": "BEINSPORT2FR"},
            {"name": "BeIN Sports 3 FR", "code": "BEINSPORT3FR"},
            {"name": "BeIN MAX 4 FR", "code": "beINMAX4FR"},
            {"name": "BeIN MAX 5 FR", "code": "beINMAX5FR"},
            {"name": "BeIN MAX 6 FR", "code": "beINMAX6FR"},
            {"name": "BeIN MAX 7 FR", "code": "beINMAX7FR"},
            {"name": "BeIN MAX 8 FR", "code": "beINMAX8FR"},
            {"name": "BeIN MAX 9 FR", "code": "beINMAX9FR"}
        ],
        "Romania (Digi/Prima)": [
            {"name": "Prima Sport 1 RO", "code": "PrimaSport1"},
            {"name": "Prima Sport 2 RO", "code": "PrimaSport2"},
            {"name": "Prima Sport 3 RO", "code": "PrimaSport3"},
            {"name": "Prima Sport 4 RO", "code": "PrimaSport4"},
            {"name": "Prima Sport 5 RO", "code": "PrimaSport5"},
            {"name": "Digi Sport 1 RO", "code": "DIGISPORT1"},
            {"name": "Digi Sport 2 RO", "code": "DIGISPORT2"},
            {"name": "Digi Sport 3 RO", "code": "DIGISPORT3"},
            {"name": "Digi Sport 4 RO", "code": "DIGISPORT4"}
        ],
        "Albania": [
            {"name": "Tring Sport 1", "code": "TringSport1"},
            {"name": "Tring Sport 2", "code": "TringSport2"},
            {"name": "Tring Sport 3", "code": "TringSport3"}
        ],
        "Bulgaria": [
            {"name": "Max Sport 1 BG", "code": "MaxSportBG"},
            {"name": "Max Sport 2 BG", "code": "MaxSport2BG"},
            {"name": "Max Sport 3 BG", "code": "MaxSport3BG"},
            {"name": "Max Sport 4 BG", "code": "MaxSport4BG"},
            {"name": "Eurosport 1 BG", "code": "EURO1BG"},
            {"name": "Eurosport 2 BG", "code": "EURO2BG"},
            {"name": "Nova Sport BG", "code": "NOVASPORTBG"},
            {"name": "Diema Sport", "code": "DiemaSport"},
            {"name": "Diema Sport 2", "code": "DiemaSport2"},
            {"name": "Diema Sport 3", "code": "DiemaSport3"}
        ],
        "Grecia": [
            {"name": "Cosmote Sport 1", "code": "COSMOTESPORT1"},
            {"name": "Cosmote Sport 2", "code": "COSMOTESPORT2"},
            {"name": "Cosmote Sport 3", "code": "COSMOTESPORT3"},
            {"name": "Cosmote Sport 5", "code": "COSMOTESPORT5"},
            {"name": "Cosmote Sport 6", "code": "COSMOTESPORT6"},
            {"name": "Cosmote Sport 7", "code": "COSMOTESPORT7"},
            {"name": "Cosmote Sport 8", "code": "COSMOTESPORT8"},
            {"name": "Cosmote Sport 9", "code": "COSMOTESPORT9"},
            {"name": "Nova Sports 1", "code": "NOVASPORTS1"},
            {"name": "Nova Sports 3", "code": "NOVASPORTS3"},
            {"name": "Nova Sports 4", "code": "NOVASPORTS4"},
            {"name": "Nova Sports 5", "code": "NOVASPORTS5"},
            {"name": "Nova Sports Prime", "code": "NOVASPORTSPR"},
            {"name": "Nova Sports Start", "code": "NOVASPORTSST"}
        ],
        "Polonia": [
            {"name": "Canal+ Sport PL", "code": "Canal+SportPL"},
            {"name": "Canal+ Sport 2 PL", "code": "Canal+Sport2PL"},
            {"name": "Canal+ Sport 3 PL", "code": "Canal+Sport3PL"},
            {"name": "Canal+ Sport 4 PL", "code": "Canal+Sport4PL"},
            {"name": "Canal+ Sport 5 PL", "code": "Canal+Sport5PL"},
            {"name": "Polsat Sport PL", "code": "PolsatSportPL"},
            {"name": "Polsat Sport Extra", "code": "PolsatSportExtra"},
            {"name": "Polsat Sport News", "code": "PolsatSportNews"},
            {"name": "Polsat Sport Premium 1", "code": "PolsatSportPremium1"},
            {"name": "Polsat Sport Premium 2", "code": "PolsatSportPremium2"},
            {"name": "Eleven Sports 1 PL", "code": "ElevenSports1PL"},
            {"name": "Eleven Sports 2 PL", "code": "ElevenSports2PL"},
            {"name": "Eleven Sports 3 PL", "code": "ElevenSports3PL"},
            {"name": "Eleven Sports 4 PL", "code": "ElevenSports4PL"},
            {"name": "Eurosport 1 PL", "code": "EurosportPL"},
            {"name": "Eurosport 2 PL", "code": "Eurosport2PL"}
        ],
        "Portogallo": [
            {"name": "Sport TV 1", "code": "SPT1"},
            {"name": "Sport TV 2", "code": "SPT2"},
            {"name": "Sport TV 3", "code": "SPT3"},
            {"name": "Sport TV 4", "code": "SPT4"},
            {"name": "Sport TV 5", "code": "SPT5"},
            {"name": "Sport TV 6", "code": "SPT6"}
        ],
        "Repubblica Ceca": [
            {"name": "Nova Sport 1 CZ", "code": "NOVASPORT1CZ"},
            {"name": "Sport 1 CZ", "code": "SPORT1CZ"},
            {"name": "Sport 2 CZ", "code": "SPORT2CZ"}
        ],
        "Russia": [
            {"name": "Match TV", "code": "MatchTV"},
            {"name": "Match TV 1", "code": "MatchTV1"},
            {"name": "Match TV 2", "code": "MatchTV2"},
            {"name": "Match TV 3", "code": "MatchTV3"}
        ],
        "Spagna": [
            {"name": "Vamos ES", "code": "VamosES"},
            {"name": "M+ Deportes", "code": "MDEPORTES"},
            {"name": "Movistar Golf ES", "code": "MOVISTARGOLFES"},
            {"name": "LaLiga ES", "code": "LALIGAES"},
            {"name": "M. Liga de Campeones", "code": "MLIGADECAMPEONES"}
        ],
        "UK": [
            {"name": "Premier Sports 1", "code": "PREMIERSPORTS1"},
            {"name": "Premier Sports 2", "code": "PREMIERSPORTS2"}
        ],
        "USA": [
            {"name": "ESPN", "code": "ESPN"},
            {"name": "ESPN 2", "code": "ESPN2"},
            {"name": "ESPN News", "code": "ESPNNews"},
            {"name": "ESPN U", "code": "ESPNUUSA"},
            {"name": "Fox Sports 1", "code": "FoxSports1"},
            {"name": "Fox Sports 2", "code": "FoxSports2"},
            {"name": "CBS Sports Network", "code": "CBSSportsNetwork"},
            {"name": "NFL Network", "code": "NFLNetwork"},
            {"name": "Golf Channel", "code": "GolfChannel"},
            {"name": "Tennis Channel", "code": "TennisChannel"},
            {"name": "Willow Cricket", "code": "WillowCricket"},
            {"name": "Willow Xtra", "code": "WillowXtra"}
        ]
    },
    "international_sport": {
        "Bulgaria": [
            {"name": "Max Sport 1 BG", "code": "MaxSportBG"},
            {"name": "Max Sport 2 BG", "code": "MaxSport2BG"},
            {"name": "Max Sport 3 BG", "code": "MaxSport3BG"},
            {"name": "Max Sport 4 BG", "code": "MaxSport4BG"},
            {"name": "Eurosport 1 BG", "code": "EURO1BG"},
            {"name": "Eurosport 2 BG", "code": "EURO2BG"},
            {"name": "Nova Sport BG", "code": "NOVASPORTBG"},
            {"name": "Diema Sport", "code": "DiemaSport"},
            {"name": "Diema Sport 2", "code": "DiemaSport2"},
            {"name": "Diema Sport 3", "code": "DiemaSport3"}
        ],
        "Polonia": [
            {"name": "Canal+ Sport PL", "code": "Canal+SportPL"},
            {"name": "Canal+ Sport 2 PL", "code": "Canal+Sport2PL"},
            {"name": "Canal+ Sport 3 PL", "code": "Canal+Sport3PL"},
            {"name": "Canal+ Sport 4 PL", "code": "Canal+Sport4PL"},
            {"name": "Canal+ Sport 5 PL", "code": "Canal+Sport5PL"},
            {"name": "Polsat Sport PL", "code": "PolsatSportPL"},
            {"name": "Polsat Sport Extra", "code": "PolsatSportExtra"},
            {"name": "Polsat Sport News", "code": "PolsatSportNews"},
            {"name": "Polsat Sport Premium 1", "code": "PolsatSportPremium1"},
            {"name": "Polsat Sport Premium 2", "code": "PolsatSportPremium2"},
            {"name": "Eleven Sports 1 PL", "code": "ElevenSportsPL"},
            {"name": "Eleven Sports 2 PL", "code": "ElevenSports2PL"},
            {"name": "Eleven Sports 3 PL", "code": "ElevenSports3PL"},
            {"name": "Eleven Sports 4 PL", "code": "ElevenSports4PL"},
            {"name": "Eurosport 1 PL", "code": "EurosportPL"},
            {"name": "Eurosport 2 PL", "code": "Eurosport2PL"}
        ],
        "Portogallo": [
            {"name": "Sport TV 1", "code": "SPT1"},
            {"name": "Sport TV 2", "code": "SPT2"},
            {"name": "Sport TV 3", "code": "SPT3"},
            {"name": "Sport TV 4", "code": "SPT4"},
            {"name": "Sport TV 5", "code": "SPT5"},
            {"name": "Sport TV 6", "code": "SPT6"}
        ],
        "USA": [
            {"name": "ESPN", "code": "ESPN"},
            {"name": "ESPN 2", "code": "ESPN2"},
            {"name": "ESPN News", "code": "ESPNNews"},
            {"name": "ESPN U", "code": "ESPNUUSA"},
            {"name": "Fox Sports 1", "code": "FoxSports1"},
            {"name": "Fox Sports 2", "code": "FoxSports2"},
            {"name": "CBS Sports Network", "code": "CBSSportsNetwork"},
            {"name": "NFL Network", "code": "NFLNetwork"},
            {"name": "Golf Channel", "code": "GolfChannel"},
            {"name": "Tennis Channel", "code": "TennisChannel"},
            {"name": "Willow Cricket", "code": "WillowCricket"},
            {"name": "Willow Xtra", "code": "WillowXtra"}
        ]
    },
    "mpd_matching": [
        {"name": "DAZN F1 ES", "match": ["DAZN F1", "F1", "FORMULA 1"], "country": "Spain"},
        {"name": "M+ LALIGA", "match": ["LALIGA", "CALCIO", "REAL MADRID", "BARCELONA"], "country": "Spain"},
        {"name": "CANAL+ SPORT", "match": ["SPORT", "FOOTBALL", "PREMIER LEAGUE"], "country": "France"},
        {"name": "POLSAT SPORT", "match": ["VOLLEY", "TENNIS", "SPORT"], "country": "Poland"}
    ],

}

def build_url(query):
    return f"{BASE_URL}?{urlencode(query)}"

# Funzioni EPG legacy rimosse.
# Vedere resources/lib/epg_client.py

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
    
    import time
    # Il parametro 'reload' con timestamp forza Kodi a NON usare la cache della cartella
    reload_salt = str(int(time.time()))
    
    add_directory_item("[COLOR lime][B]Agenda Sportiva (Eventi di Oggi)[/B][/COLOR]", {"action": "list_agenda"})
    add_directory_item("[COLOR gold][B]Canali Sport[/B][/COLOR]", {"action": "list_sport"})
    
    # NOVITÀ: Canali Intrattenimento (Fonte Premium Stabile)
    add_directory_item("[COLOR lightblue][B]Canali Intrattenimento[/B][/COLOR]", {"action": "list_eagle_genres", "eb_type": "sky_tv"})
    
    add_directory_item("[COLOR lime][B]Cerca Film[/B][/COLOR]", {"action": "sc_search", "search_type": "movie"}, icon=FANART)
    add_directory_item("[COLOR lime][B]Cerca Serie TV[/B][/COLOR]", {"action": "sc_search", "search_type": "tvshow"}, icon=FANART)
    # Impostiamo is_folder=False per far sì che agisca come un comando, non come una cartella vuota
    add_directory_item("[COLOR cyan][B]Cerca Canale TV[/B][/COLOR]", {"action": "search_channels"}, is_folder=False, icon=FANART)

    xbmcplugin.endOfDirectory(HANDLE)

def search_live_channels(query=None):
    """Ricerca globale di canali live in tutte le sorgenti (Locali e Remote)"""
    if not query:
        # Fase 1: Finestra di dialogo (chiamata dal menu principale con is_folder=False)
        query = xbmcgui.Dialog().input("Cerca Canale TV", type=xbmcgui.INPUT_ALPHANUM)
        if query:
            # Se abbiamo una query, apriamo una NUOVA finestra di Kodi con i risultati.
            # Usiamo ActivateWindow(10025, ...) che apre la vista video sul nostro URL.
            # Questo crea un nuovo livello nell'addon con URL persistente.
            url = f"{BASE_URL}?action=search_channels&query={quote(query)}"
            xbmc.executebuiltin(f'ActivateWindow(10025,"{url}",return)')
        return

    # Fase 2: Visualizzazione risultati (chiamata da ActivateWindow con query presente)
    xbmcplugin.setContent(HANDLE, 'videos')
    q = query.lower()
    results = []
    
    cfg = get_remote_config()
    

    # - Freeshot V3
    for ch in cfg.get("freeshot_v3", {}).get("channels", []):
        if q in ch["name"].lower():
            results.append((f"{ch['name']} [COLOR gray](Fonte FS)[/COLOR]", {"action": "play_freeshot_v3", "code": ch["code"], "title": ch["name"]}, None, False))

    # - Internazionali FS
    int_fs = cfg.get("international_sport_fs", {})
    for country in int_fs:
        for ch in int_fs[country]:
            if q in ch["name"].lower():
                results.append((f"{ch['name']} [COLOR cyan]({country})[/COLOR] [COLOR gray](FS)[/COLOR]", {"action": "play_freeshot_v3", "code": ch["code"], "title": ch["name"]}, None, False))


    # 3. Canali da FONTE PREMIUM (Remoto - Live)
    try:
        r = requests.get(f"{_P_URL}?numTest=A1A260", headers={"User-Agent": _P_UA}, timeout=5)
        mandra_data = r.json()
        sections = mandra_data.get("channels", [])
        for sec in sections:
            for it in sec.get("items", []):
                title = it.get("title", "")
                clean_title = re.sub(r'\[.*?\]', '', title).strip()
                if q in clean_title.lower():
                    if clean_title.upper().endswith("FHD") or " FHD " in clean_title.upper():
                        continue
                    resolve_val = it.get("myresolve", "")
                    if "sky@@" in resolve_val:
                        ch_id = resolve_val.split("@@")[1]
                        results.append((f"{clean_title} [COLOR lightblue](Premium)[/COLOR]", {"action": "play_premium", "ch_id": ch_id, "title": clean_title}, it.get("thumbnail"), False))
    except Exception as e:
        xbmc.log(f"[CBTV] Search Premium Error: {e}", xbmc.LOGERROR)

    # 4. Canali da EAGLE STALKER (EB)
    try:
        eb_client = EagleStalkerClient()
        # Sky TV/Cinema
        for ch in eb_client.get_sky_tv_channels():
            if q in ch['name'].lower():
                results.append((f"{ch['name']} [COLOR lightblue](EB Cinema)[/COLOR]", {"action": "play_eagle_stalker", "cmd": ch['cmd'], "title": ch['name']}, None, False))
        # DAZN
        for ch in eb_client.get_dazn_channels():
            if q in ch['name'].lower():
                results.append((f"{ch['name']} [COLOR orange](EB Dazn)[/COLOR]", {"action": "play_eagle_stalker", "cmd": ch['cmd'], "title": ch['name']}, None, False))
    except Exception as e:
        xbmc.log(f"[CBTV] EB Search Error: {e}", xbmc.LOGERROR)

    # 5. Mostra i risultati
    if not results:
        xbmcgui.Dialog().notification("Cerca Canale", f"Nessun canale trovato per '{query}'", xbmcgui.NOTIFICATION_WARNING)
    else:
        for title, params, icon, is_folder in results:
            add_directory_item(title, params, is_folder=is_folder, icon=icon, is_playable=not is_folder)
            
    xbmcplugin.endOfDirectory(HANDLE)

def list_sport():
    """Sottomenu Sport con tutte le sorgenti"""
    xbmcplugin.setContent(HANDLE, 'videos')
    

    add_directory_item("[COLOR cyan][B]Sky Sport (Lista FS)[/B][/COLOR]", {"action": "list_freeshot_v3"})
    add_directory_item("[COLOR cyan][B]Sky Sport (Premium)[/B][/COLOR]", {"action": "list_premium_sport"})
    add_directory_item("[COLOR orange][B]Dazn (EB)[/B][/COLOR]", {"action": "list_eagle_genres", "eb_type": "dazn_only"})
    
    add_directory_item("[COLOR violet][B]Canali Internazionali[/B][/COLOR]", {"action": "list_international_sport"})
    
    xbmcplugin.endOfDirectory(HANDLE)

def list_international_sport():
    """Menu principale Canali Internazionali"""
    xbmcplugin.setContent(HANDLE, 'videos')
    add_directory_item("[COLOR cyan][B]Canali Esteri (Lista 1 FS)[/B][/COLOR]", {"action": "list_international_fs"})
    add_directory_item("[COLOR gold][B]Canali Esteri (Lista 2 MPD)[/B][/COLOR]", {"action": "list_mpd_nazioni"})
    
    xbmcplugin.endOfDirectory(HANDLE)





def list_international_country(country):
    """Lista canali per una specifica nazione"""
    xbmcplugin.setContent(HANDLE, 'videos')
    
    cfg = get_remote_config()
    int_cfg = cfg.get("international_sport", DEFAULT_CONFIG.get("international_sport", {}))
    channels = int_cfg.get(country, [])
    
    for ch in channels:
        add_directory_item(
            ch["name"],
            {"action": "play_freeshot_v3", "code": ch["code"], "title": ch["name"]},
            is_folder=False,
            is_playable=True
        )
        
    xbmcplugin.endOfDirectory(HANDLE)


from resources.lib.cbtv_proxy import ProxyManager

def play_with_proxy(code, title, source_type):
    """Metodo condiviso per le fonti che necessitano token refresh continuo (FS)"""
    try:
        xbmc.log(f"[CBTV] Avvio proxy locale per {title} ({code})", xbmc.LOGINFO)
        proxy = ProxyManager()
        port = proxy.start()
        
        proxy_url = f"http://127.0.0.1:{port}/proxy.m3u8?code={code}&source={source_type}"
        
        list_item = xbmcgui.ListItem(path=proxy_url)
        list_item.setInfo('video', {'title': title})
        
        list_item.setProperty('inputstream', 'inputstream.ffmpegdirect')
        list_item.setProperty('inputstream.ffmpegdirect.is_realtime_stream', 'true')
        list_item.setProperty('inputstream.ffmpegdirect.manifest_type', 'hls')
        list_item.setMimeType('application/x-mpegURL')
        list_item.setContentLookup(False)
        
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=list_item)
        
        # Keep-alive loop
        for i in range(15):
            if xbmc.Player().isPlaying():
                break
            xbmc.sleep(1000)
            
        while xbmc.Player().isPlaying():
            xbmc.sleep(1000)
            
        proxy.stop()
        
    except Exception as e:
        xbmcgui.Dialog().notification("Errore Proxy", str(e), xbmcgui.NOTIFICATION_ERROR)

def list_freeshot_v3():
    """Lista canali via Freeshot V3 (Nuovo player lovetier.bz)"""
    xbmcplugin.setContent(HANDLE, 'videos')
    cfg = get_remote_config()
    fs_cfg = cfg.get("freeshot_v3", DEFAULT_CONFIG.get("freeshot_v3", {}))
    channels = fs_cfg.get("channels", [])
    
    for ch in channels:
        add_directory_item(
            ch["name"],
            {"action": "play_freeshot_v3", "code": ch["code"], "title": ch["name"]},
            is_folder=False,
            is_playable=True
        )
    xbmcplugin.endOfDirectory(HANDLE)

def play_freeshot_v3(code, title):
    """Risolvi e riproduci un canale Freeshot V3 (Fonte FS) usando il proxy locale"""
    play_with_proxy(code, title, "freeshot_v3")

def list_international_fs():
    """Menu nazioni per Canali Internazionali Lista 1 FS"""
    xbmcplugin.setContent(HANDLE, 'videos')
    cfg = get_remote_config()
    int_fs_cfg = cfg.get("international_sport_fs", DEFAULT_CONFIG.get("international_sport_fs", {}))
    
    countries = sorted(int_fs_cfg.keys())
    for country in countries:
        add_directory_item(country, {"action": "list_international_fs_country", "country": country})
    
    xbmcplugin.endOfDirectory(HANDLE)

def list_international_fs_country(country):
    """Lista canali via Freeshot V3 per una specifica nazione"""
    xbmcplugin.setContent(HANDLE, 'videos')
    cfg = get_remote_config()
    int_fs_cfg = cfg.get("international_sport_fs", DEFAULT_CONFIG.get("international_sport_fs", {}))
    channels = int_fs_cfg.get(country, [])
    
    for ch in channels:
        add_directory_item(
            ch["name"],
            {"action": "play_freeshot_v3", "code": ch["code"], "title": ch["name"]},
            is_folder=False,
            is_playable=True
        )
    xbmcplugin.endOfDirectory(HANDLE)




# --- AGENDA (SCRAPER) ---

# --- AGENDA INTELLIGENTE (EPG DRIVEN) ---

def get_today_dates():
    from datetime import datetime
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    return today

def get_cache_path(filename):
    """Ritorna il percorso della cache per l'addon"""
    path = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
    if not os.path.exists(path):
        os.makedirs(path)
    return os.path.join(path, filename)

# Funzioni EPG legacy rimosse in favore del sistema Unified

# DaddyLive deprecato, WTM scraper usato per extra

def get_mpd_link_for_foreign(channel_name, country):
    """Cerca un link MPD Amstaff per un canale straniero"""
    mapping = {
        "MOVISTAR LALIGA": "amstaff@@...", 
        "CANAL+ SPORT": "amstaff@@...",
    }
    return {"name": channel_name, "country": country}

def list_agenda():
    """Agenda Sportiva: Calcio, Tennis, Volley, Motorsport (SportEventz + DaddyLive)"""
    xbmcplugin.setContent(HANDLE, 'videos')
    p_dialog = xbmcgui.DialogProgress()
    p_dialog.create('CBTV', 'Caricamento agenda...')
    
    p_dialog.update(30, "Scarico palinsesti sportivi...")
    
    import concurrent.futures
    from resources.lib.sporteventz_scraper import get_sporteventz_schedule
    from resources.lib.daddylive_scraper import get_daddylive_schedule
    
    events = []
    try:
        # Recupero in parallelo per velocità
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            se_future = executor.submit(get_sporteventz_schedule)
            dl_future = executor.submit(get_daddylive_schedule)
            
            se_events = se_future.result() or []
            dl_events = dl_future.result() or []
    except Exception as e:
        xbmc.log(f"[CBTV] Errore caricamento agenda: {e}", xbmc.LOGERROR)
        se_events = []
        dl_events = []
    
    # Parole chiave per evidenziare eventi Top (Sincronizzate con WebApp)
    W_TOP = ["PAOLINI", "SINNER", "MUSETTI", "CEV", "COPPA ITALIA", "SERIE A", "CHAMPIONS", "EUROPA LEAGUE", "FERRARI", "BAGNAIA", "ITALIA", "ITALY", "JUVE", "INTER", "MILAN", "NAPOLI", "MOTOGP", "FORMULA 1", "F1", "LEWIS HAMILTON", "LECLERC"]
    
    p_dialog.update(70, "Deduplicazione eventi...")
    
    combined = []
    seen_keys = set()
    
    # 1. Priorità a SportEventz (metadati più ricchi)
    for ev in se_events:
        # Chiave per deduplicazione: ora e inizio titolo
        key = (ev["time"], ev["title"].lower().strip()[:15], ev["sport"].lower().strip())
        if key not in seen_keys:
            combined.append(ev)
            seen_keys.add(key)
            
    # 2. Aggiungi Eventi DaddyLive se non duplicati
    for ev in dl_events:
        key = (ev["time"], ev["title"].lower().strip()[:15], ev["sport"].lower().strip())
        if key not in seen_keys:
            combined.append(ev)
            seen_keys.add(key)
            

            
    # Ordina cronologicamente
    combined.sort(key=lambda x: x["time"])
    events = combined
    
    p_dialog.update(90, f"Identificati {len(events)} eventi")
    
    # Salva eventi per l'accesso successivo (visualizzazione canali)
    cache_file = get_cache_path("agenda_events.json")
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False)
    
    for idx, ev in enumerate(events):
        title_up = ev["title"].upper()
        tourn_up = ev.get("tournament", "").upper()
        
        # Identificazione TOP: rispetta il valore dello scraper ma ricalcola per sicurezza, escludendo amichevoli e campionati minori
        is_top = ev.get("is_top", False) or any(w in title_up or w in tourn_up for w in W_TOP)
        
        # Filtri negativi: escludiamo amichevoli e Champions League asiatica (AFC)
        if any(x in tourn_up or x in title_up for x in ["FRIENDLY", "AMICHEVOLE", "AFC"]):
            is_top = False
        
        tourn_str = f" [{ev.get('tournament', '')}]" if ev.get('tournament') else ""
        
        # Format label
        label = f"[B]{ev['time']}[/B] - {ev['title']} [COLOR darkorange]{tourn_str}[/COLOR]"
        if is_top:
            label = f"[COLOR yellow][B]{ev['time']}[/B] - {ev['title']}[/COLOR] [COLOR darkorange]{tourn_str}[/COLOR]"
        
        # Se il titolo contiene già colori (es. GP da fallback), usiamolo così com'è o adattiamolo
        if "[COLOR" in ev["title"]:
            label = f"[B]{ev['time']}[/B] - {ev['title']} [COLOR darkorange]{tourn_str}[/COLOR]"

        n = len(ev.get("sources", []))
        ch_str = f"{n} canali" if n != 1 else "1 canale"
        list_item = xbmcgui.ListItem(label=f"{label} [COLOR gray]({ch_str})[/COLOR]")
        
        # Aggiungi info plot per vedere sport/torneo nel dettaglio
        plot = f"Sport: {ev['sport']}\nTorneo: {ev.get('tournament', 'N/A')}\nCanali: {', '.join([s['name'] for s in ev.get('sources', [])])}"
        list_item.setInfo('video', {'title': ev['title'], 'plot': plot})
        
        url = f"{sys.argv[0]}?action=list_sources_agenda&idx={idx}"
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=list_item, isFolder=True)
    
    p_dialog.close()
    
    if not events:
        xbmcgui.Dialog().notification("CBTV", "Nessun evento sportivo trovato per oggi", xbmcgui.NOTIFICATION_INFO, 3000)
    
    xbmcplugin.endOfDirectory(HANDLE)


def list_sources_agenda():
    """Mostra i nomi dei canali (solo info, non playable)"""
    params = dict(parse_qsl(sys.argv[2][1:]))
    idx = int(params.get('idx', 0))
    
    cache_file = get_cache_path("agenda_events.json")
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            events = json.load(f)
        ev = events[idx]
    except:
        xbmcplugin.endOfDirectory(HANDLE)
        return
    
    xbmcplugin.setContent(HANDLE, 'videos')
    
    for s in ev.get("sources", []):
        name = s.get('name', 'Canale Sconosciuto')
        country = s.get('country', '')
        
        # Niente emoji per massimizzare la compatibilità con Kodi
        label = f"{name}"
        if country:
            label += f" ({country})"
            
        list_item = xbmcgui.ListItem(label=label)
        list_item.setProperty('IsPlayable', 'false')
        xbmcplugin.addDirectoryItem(handle=HANDLE, url="", listitem=list_item, isFolder=False)
    
    if not ev.get("sources"):
        xbmcgui.Dialog().notification("CBTV", "Nessun canale disponibile per questo evento", xbmcgui.NOTIFICATION_WARNING, 2000)
    
    xbmcplugin.endOfDirectory(HANDLE)

def play_daddy_direct():
    """Prova a riprodurre un link web diretto"""
    params = dict(parse_qsl(sys.argv[2][1:]))
    url = params.get('url')
    xbmcgui.Dialog().notification("CBTV", "Apertura stream...", xbmcgui.NOTIFICATION_INFO, 3000)
    play_freeshot(url, "Stream")


# --- MPD NAZIONI (MANDRAKODI SPORT SOURCE) ---

MPD_NAZIONI_URL = "https://test34344.herokuapp.com/filter.php?numTest=A1A134A"
MPD_UA = "MandraKodi2@@1.2.78@@MandraKodi3@@S63TDC"

def list_mpd_nazioni():
    """Show list of countries from MPD Nazioni"""
    import requests
    xbmcplugin.setContent(HANDLE, 'videos')
    
    # Blacklist di nazioni da nascondere (non funzionanti o non desiderate)
    BLACKLIST = [
        "argentina", "australia", "belgium", "brasile", "canada", "colombia",
        "germania", "grecia", "portugal", "serbia", "spain", "south korea",
        "united arab emirated", "united arab emirates", "united kindom", 
        "united kingdom", "usa", "other"
    ]
    
    try:
        headers = {"User-Agent": MPD_UA}
        r = requests.get(MPD_NAZIONI_URL, headers=headers, timeout=10)
        data = r.json()
        countries = data.get("channels", [])
        
        for country in countries:
            name = country.get("name", "Unknown")
            # Clean color tags for display
            clean_name = re.sub(r'\[.*?\]', '', name).strip()
            
            # Filtro blacklist
            if clean_name.lower() in BLACKLIST:
                continue
                
            thumb = country.get("thumbnail")
            
            add_directory_item(
                clean_name,
                {"action": "list_mpd_channels", "country_data": json.dumps(country)},
                icon=thumb
            )
    except Exception as e:
        xbmc.log(f"[CBTV] Errore MPD Nazioni: {str(e)}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("MPD Nazioni", f"Errore: {str(e)}", xbmcgui.NOTIFICATION_ERROR)
    
    xbmcplugin.endOfDirectory(HANDLE)

def list_mpd_channels(country_data):
    """Show channels for selected country"""
    import requests
    xbmcplugin.setContent(HANDLE, 'videos')
    
    try:
        country = json.loads(country_data)
        items = country.get("items", [])
        
        for ch in items:
            title = ch.get("title", "No Title")
            # Clean color tags
            clean_title = re.sub(r'\[.*?\]', '', title).strip()
            thumb = ch.get("thumbnail")
            myresolve = ch.get("myresolve", "")
            
            # Check if this is an MPD channel (has amstaff@@ prefix)
            if myresolve and "@@" in myresolve:
                # Make it a FOLDER that opens a submenu (like Mandrakodi)
                add_directory_item(
                    f"[COLOR cyan]{clean_title}[/COLOR]",
                    {"action": "show_mpd_play", "resolve_data": myresolve, "channel_name": clean_title},
                    is_folder=True,  # Changed to True - opens submenu
                    is_playable=False,
                    icon=thumb
                )
    except Exception as e:
        xbmcgui.Dialog().notification("MPD Canali", f"Errore: {str(e)}", xbmcgui.NOTIFICATION_ERROR)
    
    xbmcplugin.endOfDirectory(HANDLE)

def show_mpd_play(resolve_data, channel_name):
    """Show 'PLAY STREAM' option for the selected channel (Mandrakodi-style)"""
    xbmcplugin.setContent(HANDLE, 'videos')
    
    try:
        # Extract payload after @@
        payload = resolve_data.split("@@")[1]
        
        # Check if payload is a direct URL or Base64-encoded
        if payload.startswith("http://") or payload.startswith("https://"):
            # Direct URL format (e.g., RAI Sport)
            # Format: https://example.com/stream.mpd|0000 or |KID:KEY
            parts = payload.split("|")
            stream_url = parts[0]
            license_data = parts[1] if len(parts) > 1 else ""
        else:
            # Base64-encoded format (most channels)
            # Add padding if needed
            missing_padding = len(payload) % 4
            if missing_padding:
                payload += '=' * (4 - missing_padding)
            
            # Decode Base64
            decoded = base64.b64decode(payload).decode('utf-8')
            parts = decoded.split("|")
            stream_url = parts[0]
            license_data = parts[1] if len(parts) > 1 else ""
        
        # Create ListItem with path already set (like Mandrakodi)
        list_item = xbmcgui.ListItem(label="[COLOR lime]PLAY STREAM[/COLOR]", path=stream_url, offscreen=True)
        list_item.setInfo('video', {'title': channel_name})
        list_item.setProperty('IsPlayable', 'true')
        list_item.setContentLookup(False)
        
        # Set inputstream.adaptive
        list_item.setProperty('inputstream', 'inputstream.adaptive')
        
        # Set MIME type for MPD
        if ".mpd" in stream_url:
            list_item.setMimeType("application/dash+xml")
        
        # Set Clearkey DRM using drm_legacy (like Mandrakodi does!)
        # Note: license_data="0000" means no DRM (unencrypted stream)
        if license_data and ":" in license_data and license_data != "0000":
            drm_type = "org.w3.clearkey"
            # Format: org.w3.clearkey|KID:KEY
            list_item.setProperty('inputstream.adaptive.drm_legacy', f"{drm_type}|{license_data}")
        
        # Add as directory item
        xbmcplugin.addDirectoryItem(
            handle=HANDLE,
            url=stream_url,
            listitem=list_item,
            isFolder=False
        )
        
    except Exception as e:
        xbmcgui.Dialog().notification("MPD Play", f"Errore: {str(e)}", xbmcgui.NOTIFICATION_ERROR)
    
    xbmcplugin.endOfDirectory(HANDLE)

def play_mpd(resolve_data):
    """Decode and play MPD stream with Clearkey DRM"""
    try:
        # Extract payload after @@
        payload = resolve_data.split("@@")[1]
        
        # Check if payload is a direct URL or Base64-encoded
        if payload.startswith("http://") or payload.startswith("https://"):
            # Direct URL format (e.g., RAI Sport)
            parts = payload.split("|")
            stream_url = parts[0]
            license_data = parts[1] if len(parts) > 1 else ""
        else:
            # Base64-encoded format (most channels)
            # Add padding if needed
            missing_padding = len(payload) % 4
            if missing_padding:
                payload += '=' * (4 - missing_padding)
            
            # Decode Base64
            decoded = base64.b64decode(payload).decode('utf-8')
            
            # Parse URL|KID:KEY format
            parts = decoded.split("|")
            stream_url = parts[0]
            license_data = parts[1] if len(parts) > 1 else ""
        
        # Create ListItem for playback
        list_item = xbmcgui.ListItem(path=stream_url)
        
        # Set inputstream.adaptive for MPD playback
        list_item.setProperty('inputstream', 'inputstream.adaptive')
        list_item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
        
        # Set Clearkey DRM if license key is provided
        # Note: license_data="0000" means no DRM (unencrypted stream)
        if license_data and ":" in license_data and license_data != "0000":
            # Split KID:KEY
            kid_key = license_data.split(":")
            kid = kid_key[0]
            key = kid_key[1]
            
            # Clearkey format for inputstream.adaptive
            # Some versions want JSON, others accept KID:KEY directly
            # Try the simple format first
            list_item.setProperty('inputstream.adaptive.license_type', 'clearkey')
            list_item.setProperty('inputstream.adaptive.license_key', license_data)
            
            # Alternative: Try JSON format (commented out for now)
            # clearkey_json = json.dumps({
            #     "keys": [{
            #         "kty": "oct",
            #         "kid": kid,
            #         "k": key
            #     }]
            # })
            # list_item.setProperty('inputstream.adaptive.license_key', clearkey_json)
        
        xbmcplugin.setResolvedUrl(HANDLE, True, list_item)
        
    except Exception as e:
        xbmcgui.Dialog().notification("Play MPD", f"Errore: {str(e)}", xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())

def list_eagle_genres(eb_type):
    """Elenca le categorie o i canali di Eagle Black secondo la struttura ESATTA richiesta"""
    xbmcplugin.setContent(HANDLE, 'videos')
    from resources.lib.eagle_stalker import clean_text
    client = EagleStalkerClient()
    
    if eb_type == "sky_tv":
        # Canali Intrattenimento: Sostituito con Fonte Premium Stabile
        list_premium_live("A1A260")
            
    elif eb_type == "dazn_only":
        # DAZN: Mostriamo i canali DIRETTAMENTE
        channels = client.get_dazn_channels()
        for ch in channels:
            title = f"{ch['name']} [COLOR orange](EB)[/COLOR]"
            add_directory_item(title, {"action": "play_eagle_stalker", "cmd": ch['cmd']}, is_folder=False, is_playable=True)
            
            
    elif eb_type == "sky_sport":
        # Sky Sport: Mostriamo i canali DIRETTAMENTE
        channels = client.get_sky_sport_channels()
        for ch in channels:
            title = f"{ch['name']} [COLOR cyan](EB)[/COLOR]"
            add_directory_item(title, {"action": "play_eagle_stalker", "cmd": ch['cmd']}, is_folder=False, is_playable=True)
        
    xbmcplugin.endOfDirectory(HANDLE)


def list_eagle_stalker(genre_id):
    """Elenca i canali di una specifica categoria Eagle Black (Lista de-emoticonizzata)"""
    xbmcplugin.setContent(HANDLE, 'videos')
    from resources.lib.eagle_stalker import clean_text
    client = EagleStalkerClient()
    
    # Carichiamo i canali (1-10 pagine per sicurezza se necessario, limitato a 3)
    all_ch = []
    for p in range(1, 4):
        res = client.get_channels_by_genre(genre_id, p)
        if res and 'data' in res and res['data']:
            all_ch.extend(res['data'])
        else:
            break
        
    for ch in all_ch:
        name = clean_text(ch.get('name', 'Unknown'))
        title = f"{name} [COLOR lightblue](EB)[/COLOR]"
        add_directory_item(title, {"action": "play_eagle_stalker", "cmd": ch['cmd']}, is_folder=False, is_playable=True)
        
    xbmcplugin.endOfDirectory(HANDLE)

class EaglePlayer(xbmc.Player):
    def __init__(self, client, mac, cmd):
        super().__init__()
        self.client = client
        self.mac = mac
        self.cmd = cmd
        self.active = True
        self.av_started = False
        self.start_time = time.time()
        xbmc.log(f"[CBTV] EaglePlayer monitor avviato per MAC {mac}", xbmc.LOGINFO)

    def onAVStarted(self):
        self.av_started = True
        self.start_time = time.time()
        xbmc.log("[CBTV] EaglePlayer AV Started OK", xbmc.LOGINFO)
        # Avvia il loop di heartbeat in un thread separato
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

    def _heartbeat_loop(self):
        """Invia un segnale ogni 15 secondi per mantenere viva la sessione API (fondamentale per DAZN)"""
        while self.active and not xbmc.Monitor().abortRequested():
            if self.isPlaying():
                success = self.client.send_heartbeat(self.mac, self.cmd)
                xbmc.log(f"[CBTV] Eagle Heartbeat (MAC {self.mac}): {'OK' if success else 'FAIL'}", xbmc.LOGDEBUG)
            else:
                break
            # Dorme 5-15 secondi (intervallo più aggressivo)
            for _ in range(15):
                if not self.active or xbmc.Monitor().abortRequested(): break
                time.sleep(1)

    def onPlayBackStopped(self):
        self.active = False
        xbmc.log("[CBTV] EaglePlayer Playback Stopped", xbmc.LOGINFO)

    def onPlayBackEnded(self):
        self.active = False

def play_eagle_stalker(cmd):
    """Riproduce Eagle Stalker con rotazione MAC aggressiva e scarto dei falliti index"""
    client = EagleStalkerClient()
    
    # Creiamo una copia del pool e la mescoliamo per distribuire il carico tra gli utenti
    working_pool = list(client._MAC_POOL)
    random.shuffle(working_pool)
    
    attempts = 0
    max_attempts = len(working_pool) # Proviamo tutti i MAC disponibili se necessario
    
    while working_pool and attempts < 3: # Limitiamo a 3 tentativi totali per non tediare l'utente
        attempts += 1
        current_mac = working_pool.pop(0) # Prendi il primo MAC e rimuovilo dal pool attuale
        
        xbmc.log(f"[CBTV] Play EB Tentativo {attempts} con MAC: {current_mac}", xbmc.LOGINFO)
        client.update_mac_headers(current_mac)
        
        # 1. Ottieni stream per questo specifico MAC
        res = client._call("create_link", {'cmd': cmd, 'forced_storage': '0', 'download': '0'})
        url = res.get('cmd', '')
        
        if not url:
            xbmc.log(f"[CBTV] MAC {current_mac} rifiutato dal server (handshake/link fail)", xbmc.LOGWARNING)
            continue

        stream_url = url.split(" ")[1] if " " in url else url
        
        # Segnale di START visione (indispensabile)
        try:
            ch_id = "0"
            if "ch/" in cmd: ch_id = cmd.split("ch/")[1].split("_")[0]
            client._call("log", {
                'type': 'stb', 
                'action': 'log',
                'real_action': 'play', 
                'param': stream_url,
                'content_id': ch_id
            })
        except: pass

        # 2. Configura l'URL con gli headers MAG completi (X-STB inclusi)
        sn = client.serial
        ua = client.headers.get('User-Agent', '')
        xua = client.headers.get('X-User-Agent', '')
        did = client.device_id
        
        # Aggiungiamo SN, X-STB-Serial e X-STB-ID anche al player video
        final_url = f"{stream_url}|User-Agent={quote(ua)}&X-User-Agent={quote(xua)}&SN={quote(sn)}&X-STB-Serial={quote(sn)}&X-STB-ID={quote(did)}"
        
        list_item = xbmcgui.ListItem(path=final_url)
        list_item.setArt({'fanart': FANART})

        
        # Disattiviamo adaptive per i flussi TS nativi (molto più stabili)
        if ".m3u8" in final_url and "extension=ts" not in final_url:
            list_item.setMimeType('application/x-mpegURL')
            list_item.setProperty('inputstream', 'inputstream.adaptive')
            list_item.setProperty('inputstream.adaptive.manifest_type', 'hls')

        
        # 3. Avvia il Player Monitor
        player = EaglePlayer(client, current_mac, cmd)
        xbmcplugin.setResolvedUrl(HANDLE, True, list_item)
        
        # 4. Monitoraggio critico (primi 20 secondi)
        success_threshold = 20 
        time.sleep(3) # Tempo di buffering
        
        stable = True
        while time.time() - player.start_time < success_threshold:
            if xbmc.Monitor().abortRequested(): return
            if not player.isPlaying() and time.time() - player.start_time > 8:
                xbmc.log(f"[CBTV] MAC {current_mac} instabile (chiuso dopo {int(time.time()-player.start_time)}s). Provo il prossimo...", xbmc.LOGWARNING)
                player.active = False
                stable = False
                break
            time.sleep(1)
        
        if stable:
            xbmc.log(f"[CBTV] Sessione stabilizzata con MAC {current_mac}", xbmc.LOGINFO)
            return

    xbmcgui.Dialog().notification("Play EB", "Tutti i tentativi falliti. Server saturo.", xbmcgui.NOTIFICATION_ERROR)
    xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())




def list_premium_live(num_test):
    """Carica lista canali da fonte premium remota (Compatibile con formati piatti e sezioni)"""
    xbmcplugin.setContent(HANDLE, 'videos')
    try:
        r = requests.get(f"{_P_URL}?numTest={num_test}", headers={"User-Agent": _P_UA}, timeout=10)
        data = r.json()
        
        # Gestione flessibile della struttura JSON
        sections = data.get("channels", [])
        if not sections and "items" in data:
            # Caso lista PATTA: creiamo una sezione "General" fittizia
            sections = [{"items": data["items"]}]
            
        for section in sections:
            items = section.get("items", [])
            for it in items:
                title = it.get("title", "")
                clean_title = re.sub(r'\[.*?\]', '', title).strip()
                
                if clean_title.upper().endswith("FHD") or " FHD " in clean_title.upper():
                    continue
                
                resolve_val = it.get("myresolve", "")
                if "sky@@" in resolve_val:
                    ch_id = resolve_val.split("@@")[1]
                    display_title = f"{clean_title} [COLOR lightblue](Premium)[/COLOR]"
                    add_directory_item(
                        display_title,
                        {"action": "play_premium", "ch_id": ch_id, "title": clean_title},
                        is_folder=False,
                        icon=it.get("thumbnail"),
                        is_playable=True
                    )
    except Exception as e:
        xbmc.log(f"[CBTV] Errore Lista Premium: {e}", xbmc.LOGERROR)
    xbmcplugin.endOfDirectory(HANDLE)

def play_premium(ch_id, title):
    """Risolve e riproduce canale premium con ClearKey DRM"""
    try:
        # 1. Chiamata al risolutore remoto
        api_url = f"{_P_URL}?numTest=A1A159&id={ch_id}"
        r = requests.get(api_url, headers={"User-Agent": _P_UA}, timeout=10)
        res = r.json()
        
        # 2. Decriptazione dati XOR
        encrypted_data = res.get("data", "")
        decrypted_str = _sc_decode(encrypted_data, _P_KEY)
        if not decrypted_str: raise Exception("Decodifica fallita")
        
        data = json.loads(decrypted_str)
        manifest = data.get("manifest")
        kid = data.get("kid")
        key = data.get("key")
        
        if not manifest or not kid or not key: raise Exception("Dati streaming incompleti")
        
        # 3. Configurazione Player DASH + ClearKey
        list_item = xbmcgui.ListItem(path=manifest)
        list_item.setInfo('video', {'title': title})
        list_item.setProperty('inputstream', 'inputstream.adaptive')
        list_item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
        list_item.setMimeType('application/dash+xml')
        list_item.setContentLookup(False)
        
        # Formato license_data per ClearKey: org.w3.clearkey|KID:KEY
        license_data = f"org.w3.clearkey|{kid}:{key}"
        list_item.setProperty('inputstream.adaptive.drm_legacy', license_data)
        
        # Header necessari (NowTV style)
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
        host = "https://www.nowtv.it"
        heads = f"User-Agent={quote(ua)}&Referer={quote(host)}/&Origin={quote(host)}&verifypeer=false"
        list_item.setProperty('inputstream.adaptive.stream_headers', heads)
        list_item.setProperty('inputstream.adaptive.manifest_headers', heads)
        
        xbmcplugin.setResolvedUrl(HANDLE, True, list_item)
        
    except Exception as e:
        xbmc.log(f"[CBTV] Errore Play Premium: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("CBTv", "Canale non disponibile al momento", xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())

def list_sky_now_on_air():
    """Mostra Guida TV Sky (Ora in onda) interrogando l'EPG per i canali Eagle Stalker"""
    xbmcplugin.setContent(HANDLE, 'videos')
    p_dialog = xbmcgui.DialogProgress()
    p_dialog.create('CBTV', 'Associazioni EPG in corso...')
    
    eb_client = EagleStalkerClient()
    # Recupera i canali Sky da Eagle (Cinema, Serie, Intrattenimento)
    channels = eb_client.get_sky_tv_channels()
    
    epg = EPGClient()
    epg.get_data() # Scarica se necessario
    
    for ch in channels:
        name = ch['name']
        
        # Filtro EPG: Escludiamo le varianti FHD per mostrare una guida più snella e canali più stabili
        if "FHD" in name.upper():
            continue
            
        epg_info = epg.get_program(name)
        
        if epg_info:
            # Formatto etichetta: [08:30 - 10:00] Sky Cinema Uno | Titolo Film
            label = f"[COLOR white][B][{epg_info['start']} - {epg_info['stop']}][/B][/COLOR] [COLOR yellow][B]{name}[/B][/COLOR] | {epg_info['title']}"
            plot = f"In onda ora: {epg_info['title']}\nProssimamente su questo canale."
        else:
            label = f"{name} [COLOR gray](Nessuna info EPG)[/COLOR]"
            plot = "Dati palinsesto non disponibili per questo canale."
            
        list_item = xbmcgui.ListItem(label=label)
        list_item.setInfo('video', {'title': name, 'plot': plot})
        list_item.setProperty('IsPlayable', 'true')
        
        url = build_url({"action": "play_eagle_stalker", "cmd": ch['cmd']})
        xbmcplugin.addDirectoryItem(handle=HANDLE, url=url, listitem=list_item, isFolder=False)
        
    p_dialog.close()
    xbmcplugin.endOfDirectory(HANDLE)




if __name__ == '__main__':
    params = dict(parse_qsl(sys.argv[2][1:]))
    action = params.get('action')
    
    if not action:
        main_menu()
    elif action == 'search_channels':
        search_live_channels(params.get('query'))
    elif action == 'list_sky_now_on_air':
        list_sky_now_on_air()

    elif action == 'list_agenda':
        list_agenda()
    elif action == 'list_sources_agenda':
        list_sources_agenda()
    elif action == 'play_daddy_direct':
        play_daddy_direct()
    elif action == 'list_sport':
        list_sport()

    elif action == 'list_mpd_nazioni':
        list_mpd_nazioni()
    elif action == 'list_mpd_channels':
        list_mpd_channels(params.get('country_data'))
    elif action == 'show_mpd_play':
        show_mpd_play(params.get('resolve_data'), params.get('channel_name'))
    elif action == 'play_mpd':
        play_mpd(params.get('resolve_data'))
    elif action == 'list_international_sport':
        list_international_sport()
    elif action == 'list_freeshot_v3':
        list_freeshot_v3()
    elif action == 'play_freeshot_v3':
        play_freeshot_v3(params.get('code'), params.get('title'))
    elif action == 'list_international_fs':
        list_international_fs()
    elif action == 'list_international_fs_country':
        list_international_fs_country(params.get('country'))
    elif action == 'play_internal':
        play_internal(params.get('url'), params.get('title'))
    elif action == 'list_eagle_genres':
        list_eagle_genres(params.get('eb_type'))
    elif action == 'list_eagle_stalker':
        list_eagle_stalker(params.get('genre_id'))
    elif action == 'play_eagle_stalker':
        play_eagle_stalker(params.get('cmd'))
    elif action == 'list_premium_sport':
        list_premium_live("A1A165")
    elif action == 'play_premium':
        play_premium(params.get('ch_id'), params.get('title'))
    elif action == 'sc_search':
        search_type = params.get('search_type')
        prompt = "Cerca Film" if search_type == 'movie' else "Cerca Serie TV"
        query = xbmcgui.Dialog().input(prompt, type=xbmcgui.INPUT_ALPHANUM)
        if query:
            results = sc_search(query, search_type)
            for res in results:
                li = xbmcgui.ListItem(label=res['title'])
                li.setArt({'thumb': res['thumb'], 'icon': res['thumb'], 'fanart': FANART})
                u = f"{BASE_URL}?action=sc_list_seasons&sc_id={res['id']}&slug={res['slug']}&title={quote(res['title'])}" if res['type'] == 'tvshow' else f"{BASE_URL}?action=play_sc&sc_id={res['id']}"
                if res['type'] == 'movie': li.setProperty('IsPlayable', 'true')
                
                # Context Menu for Library
                cm = []
                cm.append(("Salva in Libreria", f"RunPlugin({BASE_URL}?action=sc_save_library&title={quote(res['title'])}&type={res['type']}&sc_id={res['id']}&slug={res['slug']}&thumb={quote(res['thumb'])})"))
                li.addContextMenuItems(cm)
                
                xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=(res['type'] == 'tvshow'))
            xbmcplugin.endOfDirectory(HANDLE)
    elif action == 'sc_list_seasons':
        sc_id, slug, title = params.get('sc_id'), params.get('slug'), params.get('title')
        seasons = sc_get_seasons_episodes(sc_id, slug)
        for s in seasons:
            li = xbmcgui.ListItem(label=f"Stagione {s['number']}")
            li.setArt({'fanart': FANART})
            u = f"{BASE_URL}?action=sc_list_episodes&sc_id={sc_id}&slug={slug}&s_num={s['number']}"
            xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=True)
        xbmcplugin.endOfDirectory(HANDLE)
    elif action == 'sc_list_episodes':
        sc_id, slug, s_num = params.get('sc_id'), params.get('slug'), params.get('s_num')
        seasons = sc_get_seasons_episodes(sc_id, slug)
        for s in seasons:
            if str(s['number']) == s_num:
                for e in s['episodes']:
                    label = f"E{str(e['number']).zfill(2)} - {e['title']}"
                    li = xbmcgui.ListItem(label=label)
                    li.setArt({'thumb': e['thumb'], 'fanart': FANART})
                    try: ep_num = int(e['number'])
                    except: ep_num = 0
                    li.setInfo('video', {'plot': e.get('plot', ''), 'season': int(s_num), 'episode': ep_num})
                    li.setProperty('IsPlayable', 'true')
                    
                    # Context Menu for Episode Library
                    cm = []
                    cm.append(("Salva in Libreria (Serie)", f"RunPlugin({BASE_URL}?action=sc_save_library&title={quote(params.get('title','Serie'))}&type=tvshow&sc_id={sc_id}&slug={slug})"))
                    li.addContextMenuItems(cm)
                    
                    u = f"{BASE_URL}?action=play_sc&sc_id={sc_id}&ep_id={e['id']}"
                    xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=False)
        xbmcplugin.endOfDirectory(HANDLE)
    elif action == 'play_sc':
        sc_id, ep_id = params.get('sc_id'), params.get('ep_id')
        res = sc_resolve(sc_id, ep_id)
        if res:
            p_url, iframe_url = res
            li = xbmcgui.ListItem(path=p_url)
            li.setMimeType('application/x-mpegURL')
            li.setProperty('inputstream', 'inputstream.adaptive')
            li.setProperty('inputstream.adaptive.manifest_type', 'hls')
            headers = {
                'User-Agent': HEADERS["User-Agent"],
                'Referer': iframe_url,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'it-IT,it;q=0.8,en-US;q=0.5,en;q=0.3'
            }
            headers_encoded = urlencode(headers)
            li.setProperty('inputstream.adaptive.stream_headers', headers_encoded)
            li.setProperty('inputstream.adaptive.manifest_headers', headers_encoded)
            li.setProperty('inputstream.adaptive.license_key', f"|{headers_encoded}|")
            xbmcplugin.setResolvedUrl(HANDLE, True, listitem=li)
        else:
            xbmcgui.Dialog().notification("Errore", "Impossibile risolvere il link", xbmcgui.NOTIFICATION_ERROR)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())

    elif action == 'sc_save_library':
        sc_save_library(params.get('title'), params.get('type'), params.get('sc_id'), params.get('slug'), params.get('thumb'))

