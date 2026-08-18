import sys
import os
import shutil

# ─── PULIZIA COMPLETA: Previene il bug "versione fantasma" su Fire Stick ───
# Problema 1: __pycache__ con .pyc vecchi che Python carica al posto dei nuovi .py
# Problema 2: Kodi tiene in cache le directory listing e i vecchi ZIP in packages/
# Soluzione: ad ogni avvio puliamo __pycache__, e al cambio versione forziamo
#            Kodi a invalidare tutte le sue cache interne per l'addon.
_ADDON_ROOT = os.path.dirname(os.path.abspath(__file__))

# 1. Cancella sempre tutti i __pycache__
for _dirpath, _dirnames, _ in os.walk(_ADDON_ROOT):
    for _d in list(_dirnames):
        if _d == '__pycache__':
            _cache_path = os.path.join(_dirpath, _d)
            try:
                shutil.rmtree(_cache_path)
            except Exception:
                pass

# 2. Rileva cambio versione e purga cache Kodi
try:
    import xml.etree.ElementTree as _ET
    _addon_xml = os.path.join(_ADDON_ROOT, 'addon.xml')
    _current_ver = _ET.parse(_addon_xml).getroot().attrib.get('version', '0')

    # File marker nella cartella dell'addon (NON in profile, che potrebbe essere cached)
    _ver_marker = os.path.join(_ADDON_ROOT, '.last_version')
    _old_ver = ''
    if os.path.exists(_ver_marker):
        try:
            with open(_ver_marker, 'r') as _f:
                _old_ver = _f.read().strip()
        except Exception:
            pass

    if _old_ver != _current_ver:
        # Versione cambiata! Purga aggressiva di tutte le cache Kodi
        import xbmcvfs as _xvfs

        # a) Cancella vecchi ZIP dalla cartella packages/ di Kodi
        try:
            _packages_dir = _xvfs.translatePath('special://home/addons/packages/')
            if os.path.isdir(_packages_dir):
                for _fname in os.listdir(_packages_dir):
                    if _fname.startswith('plugin.video.cbtv-') and _fname.endswith('.zip'):
                        _pkg_path = os.path.join(_packages_dir, _fname)
                        try:
                            os.remove(_pkg_path)
                        except Exception:
                            pass
        except Exception:
            pass

        # b) Cancella la cache delle directory listing di Kodi per il nostro addon
        try:
            _temp_dir = _xvfs.translatePath('special://temp/')
            if os.path.isdir(_temp_dir):
                for _fname in os.listdir(_temp_dir):
                    if 'plugin.video.cbtv' in _fname:
                        _tmp_path = os.path.join(_temp_dir, _fname)
                        try:
                            if os.path.isdir(_tmp_path):
                                shutil.rmtree(_tmp_path)
                            else:
                                os.remove(_tmp_path)
                        except Exception:
                            pass
        except Exception:
            pass

        # c) Cancella la cache del profilo addon (dati di listing HB vecchi, ecc.)
        try:
            _profile_dir = _xvfs.translatePath('special://profile/addon_data/plugin.video.cbtv/')
            if os.path.isdir(_profile_dir):
                # Cancella solo file di cache, NON le impostazioni dell'utente
                for _sub in os.listdir(_profile_dir):
                    _sub_path = os.path.join(_profile_dir, _sub)
                    # Cancella la cartella hublive (cache canali) e file temporanei
                    if _sub in ('hublive', 'cache') or _sub.endswith('.json'):
                        try:
                            if os.path.isdir(_sub_path):
                                shutil.rmtree(_sub_path)
                            else:
                                os.remove(_sub_path)
                        except Exception:
                            pass
        except Exception:
            pass

        # d) Forza Kodi a riscansionare gli addon locali
        try:
            import xbmc as _xbmc
            _xbmc.executebuiltin('UpdateLocalAddons()')
        except Exception:
            pass

        # Scrivi il marker della nuova versione
        try:
            with open(_ver_marker, 'w') as _f:
                _f.write(_current_ver)
        except Exception:
            pass
except Exception:
    pass

del _ADDON_ROOT
# ─── FINE PULIZIA ───
from urllib.parse import parse_qsl, urlencode
import xbmcgui
import xbmcplugin
import json
import re
import xbmc
import base64
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
# pyrefly: ignore [missing-import]
import xbmcvfs
import gzip
# from resources.lib.scraper import get_oasport_events # Rimosso in favore di EPG reale
from resources.lib.epg_client import EPGClient
# eagle_stalker rimosso — tutto gestito da hublive_stalker
from resources.lib.hublive_stalker import HubliveStalkerClient
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

def get_sc_domain():
    default_domain = "streamingcommunityz.organic"
    try:
        try:
            s4me_path = xbmcvfs.translatePath("special://home/addons/plugin.video.s4me/channels.json")
        except AttributeError:
            s4me_path = xbmc.translatePath("special://home/addons/plugin.video.s4me/channels.json")
            
        if xbmcvfs.exists(s4me_path):
            with xbmcvfs.File(s4me_path) as f:
                content = f.read()
                if isinstance(content, bytes):
                    content = content.decode('utf-8')
                data = json.loads(content)
                domain = data.get("direct", {}).get("streamingcommunity", "")
                if domain:
                    from urllib.parse import urlparse
                    parsed = urlparse(domain)
                    if parsed.netloc:
                        return parsed.netloc
    except Exception as e:
        xbmc.log(f"[CBTV] Errore lettura dominio locale da stream4me: {e}", xbmc.LOGWARNING)
        
    try:
        import requests
        r = requests.get("https://raw.githubusercontent.com/stream4me/addon/master/channels.json", timeout=5)
        if r.status_code == 200:
            data = r.json()
            domain = data.get("direct", {}).get("streamingcommunity", "")
            if domain:
                from urllib.parse import urlparse
                parsed = urlparse(domain)
                if parsed.netloc:
                    return parsed.netloc
    except Exception as e:
        xbmc.log(f"[CBTV] Errore lettura dominio remoto di stream4me: {e}", xbmc.LOGWARNING)

    try:
        remote_cfg = get_remote_config()
        if remote_cfg and "sc_domain" in remote_cfg:
            return remote_cfg["sc_domain"]
    except Exception as e:
        pass

    return default_domain
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
    url = f"https://{get_sc_domain()}/it/search?q={quote(query)}"
    try:
        r = scraper.get(url, timeout=10)
        data = extract_data_page(r.text)
        if not data: return []
        titles = data.get('props', {}).get('titles', [])
        results = []
        for i in titles:
            thumb = ''
            fanart = ''
            if i.get('images'):
                poster_obj = next((img for img in i['images'] if img.get('type') == 'poster'), None)
                cover_obj = next((img for img in i['images'] if img.get('type') == 'cover'), None)
                if not poster_obj: poster_obj = i['images'][0]
                if poster_obj and poster_obj.get('filename'):
                    thumb = f"https://cdn.{get_sc_domain()}/images/{poster_obj['filename']}"
                if cover_obj and cover_obj.get('filename'):
                    fanart = f"https://cdn.{get_sc_domain()}/images/{cover_obj['filename']}"
            
            type_val = "tvshow" if "tv" in i.get('type','').lower() else "movie"
            if filter_type and type_val != filter_type: continue
            
            # Metadati extra (come stream4me)
            lang = 'Sub-ITA' if i.get('sub_ita', 0) == 1 else 'ITA'
            
            # Plot, anno e runtime sono dentro 'translations', non nei campi root
            translations = {tr['key']: tr['value'] for tr in i.get('translations', []) if tr.get('key')}
            plot = translations.get('plot', '') or i.get('plot', '')
            
            year = ''
            date_str = translations.get('last_air_date', '') or i.get('release_date', '') or i.get('last_air_date', '')
            if date_str and '-' in str(date_str):
                year = str(date_str).split('-')[0]
            
            runtime = translations.get('runtime', '')
            
            results.append({
                "id": i.get('id'),
                "title": translations.get('name', '') or i.get('name') or i.get('title'),
                "slug": i.get('slug'),
                "type": type_val,
                "thumb": thumb,
                "fanart": fanart or thumb,
                "lang": lang,
                "year": year,
                "plot": plot,
                "score": i.get('score', ''),
                "seasons_count": i.get('seasons_count', 0),
                "runtime": runtime,
            })
        return results
    except Exception as e:
        xbmc.log(f"[CBTV] SC_SEARCH Error: {e}", xbmc.LOGERROR)
        return []

def sc_get_seasons_episodes(sc_id, slug):
    scraper = get_scraper()
    if not scraper: return []
    url = f"https://{get_sc_domain()}/it/titles/{sc_id}-{slug}"
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
                            thumb = f"https://cdn.{get_sc_domain()}/images/{img_obj['filename']}"
                    
                    parsed_eps.append({"number": e['number'], "title": e.get('name', f"Ep {e['number']}"), "id": e['id'], "plot": e.get('plot', ''), "thumb": thumb})
                
                all_s.append({"number": s_num, "episodes": parsed_eps})
        return all_s
    except: return []

def sc_resolve(sc_id, ep_id=None):
    import html
    scraper = get_scraper()
    if not scraper: return None
    iframe_url = f"https://{get_sc_domain()}/it/iframe/{sc_id}"
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
    "version": 101,
    "sky_it_api_base": "https://apid.sky.it/gtv/v1/events",
    "freeshot_v3": {
        "player_base_url": "https://lovetier.bz/player/",
        "stream_base_url": "https://beautifulpeople.lovetier.bz/",
        "stream_path": "/tracks-v1a1/mono.m3u8",
        "referer": "https://lovetier.bz/",
        "token_regex": "currentToken: \"([^\"]+)\"",
        "channels": [
            {"name": "Sky Sport 24", "code": "SkySport24IT", "sky_id": 9094},
            {"name": "Sky Sport Uno", "code": "SkySportUnoIT", "sky_id": 9097},
            {"name": "Sky Sport Calcio", "code": "SkySportCalcioIT", "sky_id": 9113},
            {"name": "Sky Sport Arena", "code": "SkySportArenaIT", "sky_id": 9093},
            {"name": "Sky Sport Max", "code": "SkySportMaxIT", "sky_id": 9103},
            {"name": "Sky Sport Tennis", "code": "SkySportTennisIT", "sky_id": 11237},
            {"name": "Sky Sport F1", "code": "SkySportF1IT", "sky_id": 9096},
            {"name": "Sky Sport MotoGP", "code": "SkySportMotoGPIT", "sky_id": 9102},
            {"name": "Sky Sport Basket", "code": "SkySportBasketIT", "sky_id": 9116},
            {"name": "Sky Sport Golf", "code": "SkySportGolfIT", "sky_id": 10254},
            {"name": "Sky Sport Mix", "code": "SkySportMixIT", "sky_id": 12345},
            {"name": "DAZN 1", "code": "ZonaDAZN", "sky_id": 11402}
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
    
    add_directory_item("[COLOR lime][B]Agenda Sportiva (Eventi di Oggi)[/B][/COLOR]", {"action": "list_agenda", "reload": reload_salt})
    add_directory_item("[COLOR gold][B]Canali Sport[/B][/COLOR]", {"action": "list_sport", "reload": reload_salt})
    
    # NOVITÀ: Canali Intrattenimento (Fonte Premium Stabile)
    add_directory_item("[COLOR lightblue][B]Canali Intrattenimento[/B][/COLOR]", {"action": "list_eagle_genres", "eb_type": "sky_tv", "reload": reload_salt})
    
    # Nuova cartella Primafila in Home (sotto Intrattenimento)
    add_directory_item("[COLOR pink][B]Primafila[/B][/COLOR]", {"action": "list_primafila", "reload": reload_salt})
    
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

    # 4. Canali da Hublive (HB)
    try:
        from resources.lib.hublive_stalker import HubliveStalkerClient
        hl_client = HubliveStalkerClient()
        # Sky TV/Cinema
        for ch in hl_client.get_sky_tv_channels():
            if q in ch['name'].lower():
                results.append((f"{ch['name']} [COLOR lightblue](HB Cinema)[/COLOR]", {"action": "play_hublive_stalker", "cmd": ch['cmd'], "title": ch['name']}, None, False))
        # DAZN
        for ch in hl_client.get_dazn_channels():
            if q in ch['name'].lower():
                results.append((f"{ch['name']} [COLOR orange](HB Dazn)[/COLOR]", {"action": "play_hublive_stalker", "cmd": ch['cmd'], "title": ch['name']}, None, False))
        # Sky Sport
        for ch in hl_client.get_sky_sport_channels():
            if q in ch['name'].lower():
                results.append((f"{ch['name']} [COLOR cyan](HB Sport)[/COLOR]", {"action": "play_hublive_stalker", "cmd": ch['cmd'], "title": ch['name']}, None, False))
    except Exception as e:
        xbmc.log(f"[CBTV] HB Search Error: {e}", xbmc.LOGERROR)

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
    
    import time
    reload_salt = str(int(time.time()))

    add_directory_item("[COLOR cyan][B]Sky Sport (HB)[/B][/COLOR]", {"action": "list_eagle_genres", "eb_type": "sky_sport", "reload": reload_salt})
    add_directory_item("[COLOR orange][B]Dazn (HB)[/B][/COLOR]", {"action": "list_eagle_genres", "eb_type": "dazn_only", "reload": reload_salt})
    
    add_directory_item("[COLOR violet][B]Canali Internazionali[/B][/COLOR]", {"action": "list_international_sport", "reload": reload_salt})
    
    xbmcplugin.endOfDirectory(HANDLE)

def list_international_sport():
    """Menu principale Canali Internazionali"""
    xbmcplugin.setContent(HANDLE, 'videos')
    add_directory_item("[COLOR yellow][B]Canali Esteri (Lista 1 HB)[/B][/COLOR]", {"action": "list_hb_esteri_nazioni"})
    add_directory_item("[COLOR gold][B]Canali Esteri (Lista 2 MPD)[/B][/COLOR]", {"action": "list_mpd_nazioni"})
    
    xbmcplugin.endOfDirectory(HANDLE)


def list_dazn_mh():
    """Lista canali Dazn da fonte MediaHosting"""
    xbmcplugin.setContent(HANDLE, 'videos')
    
    # Canali forniti dall'utente
    channels = [
        {"name": "DAZN 1 (MH 1)", "url": "https://1nyaler.streamhostingcdn.top/stream/5/index.m3u8?token=aN7QrmHIoz60HOhI"},
        {"name": "DAZN 1 (MH 2)", "url": "https://1nyaler.streamhostingcdn.top/stream/136/index.m3u8?token=aN7QrmHIoz60HOhI"}
    ]
    
    for ch in channels:
        add_directory_item(
            f"[COLOR orange]{ch['name']}[/COLOR]",
            {"action": "play_dazn_mh", "url": ch["url"], "title": ch["name"]},
            is_folder=False,
            is_playable=True
        )
    
    xbmcplugin.endOfDirectory(HANDLE)

def play_dazn_mh(url, title):
    """Riproduce stream MH con gli header necessari"""
    try:
        li = xbmcgui.ListItem(path=url)
        li.setInfo('video', {'title': title})
        
        # Headers necessari per questa fonte
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Origin': 'https://mediahosting.space',
            'Referer': 'https://mediahosting.space/'
        }
        
        # Costruiamo la stringa degli header per Kodi
        header_str = "|".join([f"{k}={quote(v)}" for k, v in headers.items()])
        full_url = f"{url}|{header_str}"
        
        li.setPath(full_url)
        li.setProperty('inputstream', 'inputstream.adaptive')
        li.setProperty('inputstream.adaptive.manifest_type', 'hls')
        li.setMimeType('application/x-mpegURL')
        li.setContentLookup(False)
        
        xbmcplugin.setResolvedUrl(HANDLE, True, listitem=li)
    except Exception as e:
        xbmc.log(f"[CBTV] Error play_dazn_mh: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Errore Play", str(e), xbmcgui.NOTIFICATION_ERROR)


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
    from resources.lib.oasport_scraper import get_oasport_schedule
    from resources.lib.tennisexplorer_scraper import get_tennisexplorer_schedule
    
    events = []
    try:
        # Recupero in parallelo per velocità
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            se_future = executor.submit(get_sporteventz_schedule)
            oa_future = executor.submit(get_oasport_schedule)
            te_future = executor.submit(get_tennisexplorer_schedule)
            
            se_events = se_future.result() or []
            oa_events = oa_future.result() or []
            te_events = te_future.result() or []
    except Exception as e:
        xbmc.log(f"[CBTV] Errore caricamento agenda: {e}", xbmc.LOGERROR)
        se_events = []
        oa_events = []
        te_events = []
    
    # Parole chiave per evidenziare eventi Top (Sincronizzate con WebApp)
    W_TOP = [
        # Calcio - Tornei elite (sempre top)
        "WORLD CUP", "MONDIALI", "MONDIALE", "CHAMPIONS LEAGUE", "EUROPA LEAGUE", "CONFERENCE", "COPPA ITALIA",
        # Calcio - Solo squadre top italiane + Cagliari
        "JUVE", "INTER", "MILAN", "NAPOLI", "ROMA", "LAZIO", "FIORENTINA", "ATALANTA",
        "BOLOGNA", "CAGLIARI", "ITALIA", "ITALY",
        # Calcio - Top club esteri
        "REAL MADRID", "BARCELONA", "CITY", "LIVERPOOL", "ARSENAL", "BAYERN", "PSG",
        # Tennis - Italiani
        "SINNER", "PAOLINI", "MUSETTI", "BERRETTINI", "ARNALDI", "COBOLLI", "ALCARAZ",
        # Motorsport
        "MOTOGP", "F1", "FORMULA 1", "FERRARI", "BAGNAIA", "LECLERC",
        # Volley - Italiane + CEV
        "CEV", "CIVITANOVA", "PERUGIA", "TRENTO", "CONEGLIANO", "MILANO", "MONZA", "MODENA",
        "SCANDICCI", "NOVARA", "BUSTO",
    ]
    
    p_dialog.update(70, "Deduplicazione eventi...")
    
    combined = []
    seen_keys = set()
    
    # 1. Priorità a SportEventz (metadati più ricchi)
    for ev in se_events:
        key = (ev["time"], ev["title"].lower().strip()[:15], ev["sport"].lower().strip())
        if key not in seen_keys:
            combined.append(ev)
            seen_keys.add(key)
            
    # 2. Aggiungi TennisExplorer
    for ev in te_events:
        key = (ev["time"], ev["title"].lower().strip()[:15], ev["sport"].lower().strip())
        if key not in seen_keys:
            combined.append(ev)
            seen_keys.add(key)
            
    # 3. Aggiungi OA Sport
    for ev in oa_events:
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


# --- CANALI ESTERI HUBLIVE (LISTA 1 HB) ---

def list_hb_esteri_nazioni():
    """Elenca i gruppi/nazioni disponibili per i canali sportivi esteri HB."""
    xbmcplugin.setContent(HANDLE, 'videos')
    
    groups = [
        ("COSMOTE / GR SPORT", "[COLOR cyan]COSMOTE (Grecia)[/COLOR]"),
        ("MAX SPORT / BG SPORT", "[COLOR cyan]MAX SPORT / DIEMA (Bulgaria)[/COLOR]"),
        ("POLSAT / PL SPORT", "[COLOR cyan]POLSAT / CANAL+ (Polonia)[/COLOR]"),
        ("S SPORT / TR SPORT", "[COLOR cyan]S SPORT (Turchia)[/COLOR]"),
        ("TNT / UK SPORT", "[COLOR cyan]TNT SPORTS (UK)[/COLOR]"),
        ("ZIGGO / NL SPORT", "[COLOR cyan]ZIGGO (Olanda)[/COLOR]"),
    ]
    
    for group_id, label in groups:
        add_directory_item(
            label,
            {"action": "list_hb_esteri_channels", "group": group_id},
            is_folder=True
        )
    
    xbmcplugin.endOfDirectory(HANDLE)

def list_hb_esteri_channels(group):
    """Elenca i canali per il gruppo selezionato di Lista 1 HB in modo dinamico"""
    xbmcplugin.setContent(HANDLE, 'videos')
    
    from resources.lib.hublive_stalker import HubliveStalkerClient
    client = HubliveStalkerClient()
    
    p_dialog = xbmcgui.DialogProgress()
    p_dialog.create("CBTV", "Caricamento canali...")
    
    channels = client.get_foreign_sport_channels(group)
    
    p_dialog.close()
    
    for ch in channels:
        title = f"{ch['name']} [COLOR yellow](HB)[/COLOR]"
        add_directory_item(
            title,
            {"action": "play_hublive_stalker", "cmd": ch['cmd'], "name": ch['name']},
            is_folder=False,
            is_playable=True
        )
        
    xbmcplugin.endOfDirectory(HANDLE)

# --- MPD NAZIONI (MANDRAKODI SPORT SOURCE) ---

MPD_NAZIONI_URL = "https://test34344.herokuapp.com/filter.php?numTest=A1A134A"
MPD_UA = "MandraKodi2@@1.2.78@@MandraKodi3@@S63TDC"

WORKING_MPD_CHANNELS = {
    "ITALY": [
        "EuroSport 6 (ITA)", "EuroSport 1 (ITA)", "EuroSport 4K (ITA)", "EuroSport 4 (ITA)",
        "EuroSport 3 (ITA)", "EuroSport 2 (ITA)", "EuroSport 5 (ITA)", "MILAN TV (ITA)", "INTER TV (ITA)"
    ],
    "CECHIA": [
        "SPORT 1 (CZ)", "SPORT 2 (CZ)"
    ],
    "AUSTRIA": [
        "Sky Sports 1 (AT)"
    ],
    "CROATIA": [
        "ARENA SPORT 1 (HRV)", "ARENA SPORT 2 (HRV)", "ARENA SPORT 4 (HRV)", "ARENA SPORT 3 (HRV)",
        "ARENA SPORT 5 (HRV)", "ARENA SPORT 8 (HRV)", "ARENA SPORT 7 (HRV)", "SPORT KLUB 1 (HRV)",
        "ARENA SPORT 6 (HRV)", "SPORT KLUB 4 (HRV)", "SPORT KLUB 2 (HRV)", "SPORT KLUB 3 (HRV)",
        "SPORT KLUB 5 (HRV)", "SPORT KLUB 6 (HRV)"
    ],
    "GERMANY": [
        "Bundesliga 3 (GER)", "Bundesliga 5 (GER)", "Bundesliga 6 (GER)", "Bundesliga 4 (GER)",
        "Bundesliga 7 (GER)", "Bundesliga 1 (GER)", "Bundesliga 2 (GER)", "Sky Sports F1 (GER)",
        "MAGENTA 1 (GER)", "MAGENTA 5 (GER)", "MAGENTA 8 (GER)"
    ],
    "LITUANIA": [
        "GO3 Sport 2 (LT)", "GO3 Sport Open (LT)", "GO3 Sport 1 (LT)"
    ],
    "POLAND": [
        "Eleven Sport 1 4K (PL)", "Eleven Sport 2 (PL)", "Eleven Sport 4 (PL)",
        "Eleven Sport 1 (PL)", "Eleven Sport 3 (PL)"
    ],
    "SWEDEN": [
        "TV4 Sport Live 2 (SWE)", "TV4 Sport Live 1 (SWE)", "TV4 Sport Live 4 (SWE)", "TV4 Sport Live 3 (SWE)"
    ],
    "UNITED KINDOM": [
        "TNT Sport 2 (ENG)", "TNT Sport 1 (ENG)", "TNT Sport 3 (ENG)", "TNT Sport 4 (ENG)", "EuroSport (ENG)"
    ],
    "SOUTH COREA": [
        "SPOTV 2 (ENG)", "SPOTV (ENG)"
    ],
    "UKRAINA": [
        "Setanta Sport 1 (UA)", "Setanta Sport 2 (UA)"
    ],
    "USA": [
        "CBS SPORT (ENG)", "NBC KTVB (ENG/SPA)", "FUBOTV 1 (ENG)", "SCRIPPS NEWS (ENG)",
        "FUBOTV 2 (ENG)", "NBC UNIVERSO (ENG/SPA)", "NBC (ENG)"
    ]
}

def list_mpd_nazioni():
    """Show list of countries from MPD Nazioni containing working channels"""
    import requests
    xbmcplugin.setContent(HANDLE, 'videos')
    
    try:
        headers = {"User-Agent": MPD_UA}
        r = requests.get(MPD_NAZIONI_URL, headers=headers, timeout=10)
        data = r.json()
        countries = data.get("channels", [])
        
        for country in countries:
            name = country.get("name", "Unknown")
            clean_name = re.sub(r'\[.*?\]', '', name).strip()
            
            # Show only countries with known working channels
            if clean_name.upper() in WORKING_MPD_CHANNELS:
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
    """Show working channels for selected country"""
    xbmcplugin.setContent(HANDLE, 'videos')
    
    try:
        country = json.loads(country_data)
        country_name = re.sub(r'\[.*?\]', '', country.get("name", "Unknown")).strip().upper()
        
        if country_name not in WORKING_MPD_CHANNELS:
            xbmcplugin.endOfDirectory(HANDLE)
            return
            
        allowed_channels = WORKING_MPD_CHANNELS[country_name]
        items = country.get("items", [])
        
        matched_channels = []
        for ch in items:
            title = ch.get("title", "No Title")
            clean_title = re.sub(r'\[.*?\]', '', title).strip()
            
            # Check if this clean title matches any of the working channel names (case-insensitive)
            if any(clean_title.lower() == ac.lower() for ac in allowed_channels):
                thumb = ch.get("thumbnail")
                myresolve = ch.get("myresolve", "")
                
                if myresolve and "@@" in myresolve:
                    matched_channels.append({
                        "clean_title": clean_title,
                        "myresolve": myresolve,
                        "thumb": thumb
                    })
                    
        # Natural sort by clean_title
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
            
        matched_channels.sort(key=lambda x: natural_sort_key(x["clean_title"]))
        
        for ch in matched_channels:
            add_directory_item(
                f"[COLOR cyan]{ch['clean_title']}[/COLOR]",
                {"action": "show_mpd_play", "resolve_data": ch['myresolve'], "channel_name": ch['clean_title']},
                is_folder=True,
                is_playable=False,
                icon=ch['thumb']
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
    """Elenca le categorie o i canali di Hublive"""
    xbmcplugin.setContent(HANDLE, 'videos')
    from resources.lib.hublive_stalker import HubliveStalkerClient
    hl_client = HubliveStalkerClient()
    
    if eb_type == "sky_tv":
        # Rimossi i canali provenienti da Mandrakodi per questa sezione
        # Aggiunta Canali Intrattenimento e Cinema da Hublive
        hl_channels = hl_client.get_sky_tv_channels()
        for ch in hl_channels:
            title = f"{ch['name']} [COLOR yellow](HB)[/COLOR]"
            add_directory_item(title, {"action": "play_hublive_stalker", "cmd": ch['cmd'], "name": ch['name']}, is_folder=False, is_playable=True)
            
    elif eb_type == "dazn_only":
        # DAZN Hublive
        hl_channels = hl_client.get_dazn_channels()
        for ch in hl_channels:
            title = f"{ch['name']} [COLOR orange](HB)[/COLOR]"
            add_directory_item(title, {"action": "play_hublive_stalker", "cmd": ch['cmd'], "name": ch['name']}, is_folder=False, is_playable=True)
            
    elif eb_type == "sky_sport":
        # Sky Sport Hublive
        hl_channels = hl_client.get_sky_sport_channels()
        for ch in hl_channels:
            title = f"{ch['name']} [COLOR cyan](HB)[/COLOR]"
            add_directory_item(title, {"action": "play_hublive_stalker", "cmd": ch['cmd'], "name": ch['name']}, is_folder=False, is_playable=True)
        
    xbmcplugin.endOfDirectory(HANDLE)


def list_primafila():
    """Elenca i canali Primafila e Cineplay da Hublive"""
    xbmcplugin.setContent(HANDLE, 'videos')
    from resources.lib.hublive_stalker import HubliveStalkerClient
    hl_client = HubliveStalkerClient()
    
    try:
        channels = hl_client.get_primafila_channels()
        for ch in channels:
            title = f"{ch['name']} [COLOR pink](HB)[/COLOR]"
            add_directory_item(title, {"action": "play_hublive_stalker", "cmd": ch['cmd'], "name": ch['name']}, is_folder=False, is_playable=True)
    except Exception as e:
        xbmc.log(f"[CBTV] Errore caricamento Primafila: {e}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification("Errore", "Impossibile caricare canali Primafila", xbmcgui.NOTIFICATION_ERROR)
        
    xbmcplugin.endOfDirectory(HANDLE)






class HBPlayer(xbmc.Player):
    """Player con callback per distinguere stop manuale da caduta stream."""
    def __init__(self):
        super().__init__()
        self.stopped_by_user = False  # True se l'utente preme stop
        self.playback_error = False   # True se errore stream
        self.playback_ended = False   # True se stream finisce
        self.av_started = False       # True quando il video parte davvero

    def onAVStarted(self):
        self.av_started = True

    def onPlayBackStopped(self):
        # L'utente ha premuto stop/back
        self.stopped_by_user = True

    def onPlayBackError(self):
        # Errore nello stream (MAC bloccato, server down)
        self.playback_error = True

    def onPlayBackEnded(self):
        # Stream terminato (spesso = caduta per MAC esaurito)
        self.playback_ended = True


def play_hublive_stalker(cmd, name=None):
    """Riproduce un canale Hublive con auto-riconnessione, rotazione MAC completa e fallback su Server 29."""
    # Determiniamo il server iniziale in base al cmd
    if "line.watchtivo-8k.com" in cmd:
        server_id = "s50"
    else:
        server_id = "s28"

    xbmc.log(f"[CBTV-HB] Avvio play per '{name}' con server iniziale {server_id}", xbmc.LOGINFO)
    
    client = HubliveStalkerClient(server_id)
    failed_macs = set()       # MAC che hanno fallito (handshake, play o stream caduto)
    max_attempts = min(12, len(client.mac_pool))  # Prova al massimo 12 MAC per non fare attendere troppo l'utente in caso di errore
    reconnect_delay = 2
    first_attempt = True      # Per gestire setResolvedUrl vs Player.play()
    
    for attempt in range(max_attempts):
        if not first_attempt:
            xbmc.log(f"[CBTV-HB] Tentativo {attempt + 1}, MAC esclusi: {len(failed_macs)}/{max_attempts}", xbmc.LOGINFO)
            if attempt <= 3:  # Notifica solo i primi tentativi per non spammare
                xbmcgui.Dialog().notification("HB", f"Cambio canale... ({attempt + 1})", xbmcgui.NOTIFICATION_INFO, 1500)
            xbmc.sleep(reconnect_delay * 1000)
        
        final_url, mac = client.resolve_stream(cmd, exclude_macs=failed_macs)
        
        if not final_url:
            # Fallback automatico su Server 29
            if server_id == "s28" and name:
                xbmc.log(f"[CBTV-HB] Tutti i MAC di s28 hanno fallito. Tento fallback su Server 29 per '{name}'...", xbmc.LOGWARNING)
                xbmcgui.Dialog().notification("HB Fallback", "Tento server secondario...", xbmcgui.NOTIFICATION_WARNING, 2000)
                
                client_s50 = HubliveStalkerClient("s50")
                fallback_cmd = client_s50.find_channel_cmd_by_name(name)
                if fallback_cmd:
                    xbmc.log(f"[CBTV-HB] Trovato cmd alternativo su s29: {fallback_cmd[:80]}...", xbmc.LOGINFO)
                    server_id = "s50"
                    client = client_s50
                    cmd = fallback_cmd
                    failed_macs = set()
                    max_attempts = min(12, len(client.mac_pool))
                    first_attempt = True
                    continue
            
            if len(failed_macs) >= max_attempts:
                xbmc.log(f"[CBTV-HB] Tutti i {max_attempts} MAC di {server_id} hanno fallito.", xbmc.LOGWARNING)
                if first_attempt:
                    xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
                break
            else:
                xbmc.log(f"[CBTV-HB] Batch di MAC fallito su {server_id}, provo il prossimo batch... (esclusi: {len(failed_macs)}/{max_attempts})", xbmc.LOGINFO)
                continue
        
        # Crea player con tracking eventi
        hb_player = HBPlayer()
        list_item = xbmcgui.ListItem(path=final_url)
        list_item.setArt({'fanart': FANART})
        
        if first_attempt:
            xbmcplugin.setResolvedUrl(HANDLE, True, list_item)
            first_attempt = False
        else:
            hb_player.play(final_url, list_item)
        
        xbmc.log(f"[CBTV-HB] Stream avviato con MAC {mac}", xbmc.LOGINFO)
        
        monitor = xbmc.Monitor()
        
        # Fase 1: Attendi avvio (max 10 secondi)
        start_time = time.time()
        while time.time() - start_time < 10:
            if monitor.abortRequested():
                return
            if hb_player.av_started or hb_player.isPlaying():
                break
            if hb_player.playback_error or hb_player.stopped_by_user or hb_player.playback_ended:
                break
            xbmc.sleep(500)
        
        if not hb_player.isPlaying() and not hb_player.av_started:
            if hb_player.stopped_by_user or hb_player.playback_ended:
                xbmc.log("[CBTV-HB] Utente ha fermato prima dell'avvio", xbmc.LOGINFO)
                return
            # MAC non ha funzionato — escludilo e riprova
            xbmc.log(f"[CBTV-HB] Stream non partito con MAC {mac}, escludo e riprovo", xbmc.LOGWARNING)
            failed_macs.add(mac)
            continue
        
        # Fase 2: Monitora playback — distingui stop manuale da crash
        playback_start_time = time.time()
        while hb_player.isPlaying():
            if monitor.abortRequested():
                return
            xbmc.sleep(1000)
        
        # Aspetta 800ms per permettere a Kodi di processare e notificare i callback asincroni di stop
        xbmc.sleep(800)
        
        playback_duration = time.time() - playback_start_time - 0.8
        xbmc.log(f"[CBTV-HB] Playback interrotto dopo {playback_duration:.1f} secondi. stopped_by_user={hb_player.stopped_by_user}, playback_error={hb_player.playback_error}, playback_ended={hb_player.playback_ended}", xbmc.LOGINFO)
        
        # Riconnettiamo solo se lo stream è caduto subito (mac esaurito / kick nei primissimi secondi)
        # Su Android (es. Tablet Samsung), lo stop manuale invia onPlayBackEnded invece di onPlayBackStopped.
        user_stopped = hb_player.stopped_by_user or (hb_player.playback_ended and (playback_duration >= 1.5 or hb_player.av_started))
        is_early_kick = hb_player.av_started and (playback_duration < 45.0) and not user_stopped
        
        if user_stopped or (hb_player.av_started and not is_early_kick):
            xbmc.log(f"[CBTV-HB] Playback fermato (utente={user_stopped}, avviato={hb_player.av_started}, durata={playback_duration:.1f}s). Esco senza riconnettere.", xbmc.LOGINFO)
            return
            
        # In tutti gli altri casi (lo stream non è mai partito o è caduto per kick nei primi secondi) escludiamo il MAC e riproviamo
        xbmc.log(f"[CBTV-HB] Stream non avviato o caduto precocemente con MAC {mac} (durata={playback_duration:.1f}s), escludo e riprovo con altro MAC...", xbmc.LOGWARNING)
        failed_macs.add(mac)
        continue
    
    # Tutti i MAC esauriti
    xbmcgui.Dialog().notification("Play HB", "Tutti i MAC esauriti. Riprova più tardi.", xbmcgui.NOTIFICATION_ERROR)









def list_premium_live(num_test, end_dir=True):
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
            
        collected_items = []
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
                    collected_items.append({
                        "title": clean_title,
                        "ch_id": ch_id,
                        "icon": it.get("thumbnail")
                    })
                    
        # Natural sort by title
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
            
        collected_items.sort(key=lambda x: natural_sort_key(x["title"]))
        
        for item in collected_items:
            display_title = f"{item['title']} [COLOR lightblue](Premium)[/COLOR]"
            add_directory_item(
                display_title,
                {"action": "play_premium", "ch_id": item['ch_id'], "title": item['title']},
                is_folder=False,
                icon=item['icon'],
                is_playable=True
            )
    except Exception as e:
        xbmc.log(f"[CBTV] Errore Lista Premium: {e}", xbmc.LOGERROR)
    if end_dir:
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






if __name__ == '__main__':
    params = dict(parse_qsl(sys.argv[2][1:]))
    action = params.get('action')
    
    if not action:
        main_menu()
    elif action == 'search_channels':
        search_live_channels(params.get('query'))


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
    elif action == 'list_hb_esteri_nazioni':
        list_hb_esteri_nazioni()
    elif action == 'list_hb_esteri_channels':
        list_hb_esteri_channels(params.get('group'))
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
    elif action == 'list_primafila':
        list_primafila()
    elif action == 'play_hublive_stalker':
        play_hublive_stalker(params.get('cmd'), name=params.get('name') or params.get('title'))
    elif action == 'list_premium_sport':
        list_premium_live("A1A165")
    elif action == 'list_dazn_mh':
        list_dazn_mh()
    elif action == 'play_dazn_mh':
        play_dazn_mh(params.get('url'), params.get('title'))
    elif action == 'play_premium':
        play_premium(params.get('ch_id'), params.get('title'))
    elif action == 'sc_search':
        search_type = params.get('search_type')
        prompt = "Cerca Film" if search_type == 'movie' else "Cerca Serie TV"
        query = xbmcgui.Dialog().input(prompt, type=xbmcgui.INPUT_ALPHANUM)
        if query:
            results = sc_search(query, search_type)
            xbmcplugin.setContent(HANDLE, 'movies' if search_type == 'movie' else 'tvshows')
            for res in results:
                # Titolo formattato come stream4me: Nome [ITA] (2024)
                lang_tag = f"[COLOR dodgerblue][{res.get('lang', 'ITA')}][/COLOR]"
                year_tag = f"[COLOR gray]({res.get('year', '')})[/COLOR]" if res.get('year') else ""
                type_icon = "[COLOR orange]Serie[/COLOR]" if res['type'] == 'tvshow' else "[COLOR lime]Film[/COLOR]"
                label = f"[B]{res['title']}[/B] {lang_tag} {year_tag}"
                label2 = f"{type_icon}"
                if res.get('seasons_count') and res['type'] == 'tvshow':
                    label2 += f" - {res['seasons_count']} stagion{'e' if res['seasons_count'] == 1 else 'i'}"
                
                li = xbmcgui.ListItem(label=label, label2=label2)
                li.setArt({
                    'thumb': res['thumb'],
                    'poster': res['thumb'],
                    'icon': res['thumb'],
                    'fanart': res.get('fanart', FANART),
                    'banner': res.get('fanart', ''),
                })
                
                # Metadati video per la vista info di Kodi
                info = {'title': res['title'], 'mediatype': 'movie' if res['type'] == 'movie' else 'tvshow'}
                if res.get('plot'): info['plot'] = res['plot']
                if res.get('year'): info['year'] = int(res['year'])
                if res.get('score'): 
                    try: info['rating'] = float(res['score'])
                    except: pass
                if res.get('runtime'):
                    try: info['duration'] = int(res['runtime']) * 60  # minuti -> secondi
                    except: pass
                li.setInfo('video', info)
                
                u = f"{BASE_URL}?action=sc_list_seasons&sc_id={res['id']}&slug={res['slug']}&title={quote(res['title'])}" if res['type'] == 'tvshow' else f"{BASE_URL}?action=play_sc&sc_id={res['id']}"
                if res['type'] == 'movie': li.setProperty('IsPlayable', 'true')
                
                # Context Menu
                cm = []
                cm.append(("Salva in Libreria", f"RunPlugin({BASE_URL}?action=sc_save_library&title={quote(res['title'])}&type={res['type']}&sc_id={res['id']}&slug={res['slug']}&thumb={quote(res['thumb'])})"))
                li.addContextMenuItems(cm)
                
                xbmcplugin.addDirectoryItem(handle=HANDLE, url=u, listitem=li, isFolder=(res['type'] == 'tvshow'))
            
            # Imposta la vista 'WideList' o 'Wall' per un look premium
            xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_UNSORTED)
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

