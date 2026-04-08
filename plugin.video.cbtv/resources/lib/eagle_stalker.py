import requests
import re
import xbmc
import os
import json
import time
import random
import xbmcaddon
import xbmcvfs
import concurrent.futures
import hashlib
from urllib.parse import quote

# --- CONFIGURAZIONE SORGENTE EB ---
_EB_CONFIG_URL = "http://blacktruck.atspace.cc/api.blvck.xml"
_FALLBACK_PORTAL = "http://majestic-ott.com:80/c/"
_FALLBACK_MAC = "00:1A:79:25:61:1e"

def _fetch_eb_config():
    """Scarica la config dinamica dal server Eagle Blvck"""
    try:
        r = requests.get(_EB_CONFIG_URL, timeout=8)
        if r.status_code == 200:
            text = r.text
            portal_m = re.search(r'portal"(http[^"]+)"', text)
            macs = re.findall(r'(00:1[Aa]:79:[0-9A-Fa-f:]{8})', text)
            if portal_m and macs:
                portal = portal_m.group(1)
                if not portal.endswith('/c/'):
                    portal = portal.rstrip('/') + '/c/'
                mac = random.choice(macs)
                return portal, mac
    except: pass
    return _FALLBACK_PORTAL, _FALLBACK_MAC

PORTAL_URL, MAC_ADDRESS = _fetch_eb_config()
ADDON_ID = 'plugin.video.cbtv'

def clean_text(text):
    if not text: return ""
    cleaned = "".join(c for c in text if ord(c) < 128 or c in "àèìòùÀÈÌÒÙ")
    cleaned = re.sub(r'^[A-Z]{2,3}\s*[\-\|]\s*', '', cleaned)
    cleaned = re.sub(r'^[A-Z]{2,2}\s+(?=[A-Z])', '', cleaned)
    cleaned = cleaned.replace("  ", " ").strip()
    return cleaned

class EagleStalkerClient:
    # User-Agent specifico MAG250 (il più compatibile in assoluto con Majestic)
    _UA = 'Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3'
    _TIMEZONE = 'Europe%2FBerlin'
    _MAX_RETRIES = 2
    
    _MAC_POOL = [
        MAC_ADDRESS,
        "00:1A:79:47:75:A1",
        "00:1A:79:41:A2:9A",
        "00:1A:79:33:04:0A",
        "00:1A:79:2C:22:11",
        "00:1A:79:47:73:C1",
        "00:1A:79:4B:92:2C"
    ]

    def __init__(self, portal=PORTAL_URL, mac=None):
        self.portal = portal
        self.mac = mac or self._MAC_POOL[0]
        self._token = None
        self.session = requests.Session()
        
        self.headers = {
            'User-Agent': self._UA,
            'X-User-Agent': 'Model: MAG250; Link: WiFi',
            'Referer': self.portal,
            'Accept': '*/*',
            'Connection': 'Keep-Alive'
        }
        self.update_mac_headers(self.mac)
        
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        if not os.path.exists(profile): os.makedirs(profile)
        self.cache_dir = profile

    def update_mac_headers(self, mac):
        self.mac = mac
        self.session = requests.Session()
        
        # Generazione IP verosimile (Range Italiani comuni)
        it_ranges = [
            (2, 32, 2, 254),     # Telecom/Tim
            (5, 88, 0, 254),     # Vodafone
            (79, 0, 0, 254),     # Fastweb
            (151, 0, 0, 254),    # WindTre
            (185, 210, 0, 254)   # Sky WiFi
        ]
        r = random.choice(it_ranges)
        random_ip = f"{r[0]}.{r[1]}.{random.randint(0,254)}.{random.randint(r[2],r[3])}"
        
        self.headers['Cookie'] = f'mac={mac}; stb_lang=en; timezone={self._TIMEZONE}'
        self.headers['X-Forwarded-For'] = random_ip
        # Identità MAG per parametri API
        self.serial = hashlib.md5(f"{ADDON_ID}_{mac}_sn".encode()).hexdigest()[:13].upper()
        self.device_id = hashlib.md5(f"{ADDON_ID}_{mac}_did".encode()).hexdigest().upper()

    def _handshake(self):
        params = {'type': 'stb', 'action': 'handshake', 'JsHttpRequest': '1-xml', 'token': ''}
        try:
            r = self.session.get(f"{self.portal}portal.php", params=params, headers=self.headers, timeout=10)
            res = r.json().get('js', {})
            token = res.get('token')
            if token:
                self._token = token
                return token
            xbmc.log(f"[CBTV] EB Handshake Fallito. Res: {res}", xbmc.LOGERROR)
        except Exception as e:
            xbmc.log(f"[CBTV] EB Handshake Errore: {e}", xbmc.LOGERROR)
        return None

    def _get_token(self, force_refresh=False):
        if not force_refresh and self._token: return self._token
        return self._handshake()

    def _get_cache(self, key):
        cache_file = os.path.join(self.cache_dir, f"eb_cache_{key}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if time.time() - data.get('timestamp', 0) < 43200:
                        return data.get('content')
            except: pass
        return None

    def _set_cache(self, key, content):
        cache_file = os.path.join(self.cache_dir, f"eb_cache_{key}.json")
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({'timestamp': time.time(), 'content': content}, f)
        except: pass

    def _call(self, action, params=None, mac=None):
        if params is None: params = {}
        if mac and mac != self.mac: self.update_mac_headers(mac)
        
        if not self._token: self._handshake()
        
        final_params = {
            'type': 'itv', 
            'action': action, 
            'JsHttpRequest': '1-xml',
            'token': self._token
        }
        final_params.update(params)
        
        try:
            r = self.session.get(f"{self.portal}portal.php", headers=self.headers, params=final_params, timeout=12)
            res = r.json().get('js', {})
            if 'Authorization failed' in str(res):
                self._token = self._handshake()
                if self._token:
                    final_params['token'] = self._token
                    r = self.session.get(f"{self.portal}portal.php", headers=self.headers, params=final_params, timeout=12)
                    return r.json().get('js', {})
            return res
        except: return {}

    def get_stream_with_rotation(self, cmd):
        mac_attempts = list(self._MAC_POOL)
        random.shuffle(mac_attempts)
        
        ch_id = "0"
        if "ch/" in cmd: ch_id = cmd.split("ch/")[1].split("_")[0]

        for current_mac in mac_attempts[:5]:
            self.update_mac_headers(current_mac)
            
            # Parametri completi Majestic per simulare decoder vero
            link_params = {
                'cmd': cmd,
                'series': '0',
                'forced_storage': '0',
                'disable_atrac': '0',
                'download': '0',
                'force_ch_link_check': '0'
            }
            
            res = self._call("create_link", link_params)
            url = res.get('cmd', '')
            if url:
                stream_url = url.split(" ")[1] if " " in url else url
                # Segnale log con ID reale del canale (fondamentale per stabilità)
                self._call("log", {
                    'type': 'stb', 'action': 'log', 'real_action': 'play', 
                    'param': stream_url, 'content_id': ch_id
                })
                return stream_url, current_mac
        return None, None

    def send_heartbeat(self, mac, cmd=None):
        """Invia un segnale di log 'play' continuo per mantenere vivo il tunnel dello stream"""
        try:
            if cmd:
                ch_id = "0"
                if "ch/" in cmd: ch_id = cmd.split("ch/")[1].split("_")[0]
                # Log di riproduzione (Cruciale per non far cadere lo stream dopo 20s)
                self._call("log", {
                    'type': 'stb', 'action': 'log', 'real_action': 'play', 
                    'content_id': ch_id
                }, mac=mac)
            else:
                self._call("get_genres", mac=mac)
            return True
        except: return False

    def generate_stream_link(self, cmd):
        """Metodo legacy per compatibilità, usa get_stream_with_rotation per stabilità"""
        url, mac = self.get_stream_with_rotation(cmd)
        return url

    def get_categories(self, force_refresh=False):
        if not force_refresh:
            cached = self._get_cache("categories")
            if cached: return cached
        res = self._call("get_genres")
        if res: self._set_cache("categories", res)
        return res

    def get_channels_by_genre(self, genre_id, page=1):
        params = {'action': 'get_ordered_list', 'genre': genre_id, 'p': str(page)}
        return self._call("get_ordered_list", params)

    def get_sky_tv_channels(self, force_refresh=False):
        cache_key = "sky_tv_v13"
        if not force_refresh:
            cached = self._get_cache(cache_key)
            if cached: return cached
        keywords = ["SKY ", "ATLANTIC", "SERIE", "LIFE", "COMEDY", "ACTION", "DRAMA", "FAMILY", "ROMANCE", "SUSPENSE", "COLLECTION", "CINEMA", "UNO", "NATURE", "DOCUMENTARI", "INVESTIGATION", "ARTE"]
        def fetch_page(page):
            res = self.get_channels_by_genre(5, page)
            return res.get('data', []) if res else []
        found = []
        seen_cmds = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_page, p) for p in range(1, 21)]
            for future in concurrent.futures.as_completed(futures):
                data = future.result()
                for ch in data:
                    cmd = ch.get('cmd')
                    if cmd in seen_cmds: continue
                    name_raw = ch.get('name', '')
                    name_up = name_raw.upper()
                    
                    # Regola ferrea: Se non c'è "SKY" nel nome, scartiamo il canale 
                    # (questo elimina i Cinema e gli Intrattenimento generici non Sky)
                    if "SKY" not in name_up:
                        continue
                        
                    is_sky_tv = any(k in name_up for k in keywords)
                    is_sport_dazn = any(x in name_up for x in ["SPORT", "DAZN", "CALCIO", "EUROSPORT", "ZONA"])
                    is_national = any(x in name_up for x in ["RAI", "ITALIA 1", "RETE 4", "CANALE 5", "LA7", "TV8", "NOVE", "FOX"])
                    
                    if is_sky_tv and not is_sport_dazn and not is_national:
                        found.append({'name': clean_text(name_raw), 'cmd': cmd, 'category': 'Sky TV'})
                        seen_cmds.add(cmd)
        found.sort(key=lambda x: x['name'])
        self._set_cache(cache_key, found)
        return found

    def get_sky_sport_channels(self, force_refresh=False):
        cache_key = "sky_sport_v10"
        if not force_refresh:
            cached = self._get_cache(cache_key)
            if cached: return cached
        keywords = ["SKY SPORT", "EUROSPORT", "ZONA DAZN"]
        def fetch_page(page):
            res = self.get_channels_by_genre(5, page)
            return res.get('data', []) if res else []
        found = []
        seen_cmds = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_page, p) for p in range(1, 21)]
            for future in concurrent.futures.as_completed(futures):
                data = future.result()
                for ch in data:
                    cmd = ch.get('cmd')
                    if cmd in seen_cmds: continue
                    name_raw = ch.get('name', '')
                    name_up = name_raw.upper()
                    if any(k in name_up for k in keywords):
                        found.append({'name': clean_text(name_raw), 'cmd': cmd, 'category': 'Sky Sport'})
                        seen_cmds.add(cmd)
        found.sort(key=lambda x: x['name'])
        self._set_cache(cache_key, found)
        return found

    def get_dazn_channels(self, force_refresh=False):
        cache_key = "dazn_v5"
        if not force_refresh:
            cached = self._get_cache(cache_key)
            if cached: return cached
        def fetch_page(page):
            res = self.get_channels_by_genre(5, page)
            return res.get('data', []) if res else []
        found = []
        seen_cmds = set()
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_page, p) for p in range(1, 21)]
            for future in concurrent.futures.as_completed(futures):
                data = future.result()
                for ch in data:
                    cmd = ch.get('cmd')
                    if cmd in seen_cmds: continue
                    name_raw = ch.get('name', '')
                    name_up = name_raw.upper()
                    if "DAZN" in name_up:
                        found.append({'name': clean_text(name_raw), 'cmd': cmd, 'category': 'DAZN'})
                        seen_cmds.add(cmd)
        found.sort(key=lambda x: x['name'])
        self._set_cache(cache_key, found)
        return found

