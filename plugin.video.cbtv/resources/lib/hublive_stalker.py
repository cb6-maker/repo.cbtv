"""
HubliveStalkerClient - Client standalone per i Server di Hublive (con fallback automatico).
Nessuna dipendenza da eagle_stalker.
"""
import os
import json
import time
import random
import re
import requests
import xbmc
import xbmcaddon
import xbmcvfs
from urllib.parse import urlparse, quote_plus

try:
    from . import proxy_config
except ImportError:
    try:
        import proxy_config
    except ImportError:
        proxy_config = None

# ---------- utilità ----------
def clean_text(text):
    """Rimuove tag [COLOR], simboli box-drawing e prefissi paese da nomi canale."""
    text = re.sub(r'\[COLOR[^\]]*\]', '', text)
    text = re.sub(r'\[/COLOR\]', '', text)
    # Rimuovi box-drawing chars (─ │ etc.)
    text = re.sub(r'[\u2500-\u259F]', '', text)
    # Rimuovi prefissi tipo "IT|" o "IT:" o "IT |" o "IT :" o "┃IT┃" o "IT "
    text = re.sub(r'^(?:┃[A-Z\s]+┃|[A-Z]{2}\s*[:|]?)\s*', '', text)
    return text.strip()


class HubliveStalkerClient:
    """Client Stalker con supporto multi-server e fallback automatico."""

    # Server 18 (z1mag - Porta 8080 non soggetta a blocchi AGCOM / Piracy Shield)
    PORTAL_18_URL = "http://z1mag.xyz:8080"
    PORTAL_18_MACS = [
        "00:1A:79:00:3C:13", "00:1A:79:01:70:B5", "00:1A:79:07:BE:10", "00:1A:79:07:C0:F4",
        "00:1A:79:07:C1:00", "00:1A:79:07:C3:38", "00:1A:79:07:C5:88", "00:1A:79:08:4D:7E",
        "00:1A:79:08:50:D1", "00:1A:79:08:E8:AA", "00:1A:79:10:3F:FD", "00:1A:79:10:40:CB",
        "00:1A:79:10:DE:C7", "00:1A:79:10:DF:E2", "00:1A:79:10:E1:47", "00:1A:79:13:53:81",
        "00:1A:79:13:54:CF", "00:1A:79:13:57:47", "00:1A:79:13:58:D1", "00:1A:79:14:61:CE",
        "00:1A:79:14:62:20", "00:1A:79:14:64:52", "00:1A:79:14:64:A1", "00:1A:79:14:64:AD",
        "00:1A:79:14:6D:47", "00:1A:79:14:E0:99", "00:1A:79:14:E7:39", "00:1A:79:19:22:E6",
        "00:1A:79:1A:67:A3", "00:1A:79:1A:67:AE", "00:1A:79:1A:6C:C1", "00:1A:79:1F:0F:F3",
        "00:1A:79:1F:12:7F", "00:1A:79:1F:1C:7A", "00:1A:79:1F:1C:CF", "00:1A:79:21:10:70",
        "00:1A:79:23:00:D0", "00:1A:79:23:01:02", "00:1A:79:4D:05:F4", "00:1A:79:5E:48:E6",
        "00:1A:79:6E:29:0B", "00:1A:79:6E:2C:B6", "00:1A:79:6E:2E:F4", "00:1A:79:77:01:2E",
        "00:1A:79:77:02:4D", "00:1A:79:77:04:6D", "00:1A:79:7C:6B:BF", "00:1A:79:A0:E4:BF",
        "00:1A:79:A0:FD:66", "00:1A:79:A0:FD:9B", "00:1A:79:A1:9D:ED", "00:1A:79:A2:8B:54",
        "00:1A:79:AF:F8:81", "00:1A:79:C1:A1:DE", "00:1A:79:C4:06:6D", "00:1A:79:C8:4B:31",
        "00:1B:79:1C:7B:70"
    ]

    PORTAL_1_URL = PORTAL_18_URL
    PORTAL_1_MACS = PORTAL_18_MACS
    PORTAL_31_URL = PORTAL_18_URL
    PORTAL_31_MACS = PORTAL_18_MACS

    REMOTE_HUB_URL = "https://raw.githubusercontent.com/staycanuca/hub/main/servers.json"

    UA = ("Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
          "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3")

    # ---- inizializzazione ----
    def __init__(self, server_id="s18"):
        self.server_id = server_id
        self.portal_url = self.PORTAL_18_URL
        self.mac_pool = list(self.PORTAL_18_MACS)

        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        self.cache_dir = os.path.join(profile, "hublive")
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

        # Pulizia automatica cache obsoleta al cambio versione
        self._check_and_clean_cache_version()

        # Applica subito i server/MAC dalla cache su disco se presenti (<1ms)
        self._apply_cached_servers()

        # Sincronizzazione remota in background per non bloccare mai la UI di Kodi
        import threading
        threading.Thread(target=self._sync_remote_servers, kwargs={"force": False}, daemon=True).start()

    def _check_and_clean_cache_version(self):
        """Verifica la versione cache ed elimina abbinamenti MAC obsoleti o corrotti al cambio versione."""
        ver_file = os.path.join(self.cache_dir, "hl_cache_version.txt")
        current_ver = ""
        if os.path.exists(ver_file):
            try:
                with open(ver_file, 'r', encoding='utf-8') as f:
                    current_ver = f.read().strip()
            except Exception:
                pass
        if current_ver != self.CACHE_VERSION:
            xbmc.log(f"[CBTV-HB] Upgrade a v{self.CACHE_VERSION}: reset abbinamenti MAC e cache...", xbmc.LOGINFO)
            try:
                for fname in os.listdir(self.cache_dir):
                    if fname.startswith("hl_") and fname.endswith(".json") and "servers_remote" not in fname:
                        try:
                            os.remove(os.path.join(self.cache_dir, fname))
                        except Exception:
                            pass
                with open(ver_file, 'w', encoding='utf-8') as f:
                    f.write(self.CACHE_VERSION)
            except Exception as e:
                xbmc.log(f"[CBTV-HB] Errore reset cache: {e}", xbmc.LOGWARNING)

    def _apply_cached_servers(self):
        """Carica istantaneamente da disco i server/MAC memorizzati in precedenza."""
        cache_file = os.path.join(self.cache_dir, "hl_servers_remote.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as fh:
                    servers_data = json.load(fh)
                    self._update_pool_from_servers(servers_data)
            except Exception:
                pass

    def _sync_remote_servers(self, force=False):
        """Scarica e memorizza in cache i server e i MAC aggiornati da staycanuca/hub in background."""
        cache_file = os.path.join(self.cache_dir, "hl_servers_remote.json")
        servers_data = None

        if not force and os.path.exists(cache_file):
            try:
                mtime = os.path.getmtime(cache_file)
                # Cache valida per 6 ore (21600 secondi)
                if time.time() - mtime < 21600:
                    return
            except Exception:
                pass

        try:
            xbmc.log("[CBTV-HB] Background sync lista server e MAC da staycanuca/hub...", xbmc.LOGINFO)
            resp = requests.get(self.REMOTE_HUB_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                servers_data = data.get("servers", [])
                with open(cache_file, 'w', encoding='utf-8') as fh:
                    json.dump(servers_data, fh)
                self._update_pool_from_servers(servers_data)
        except Exception as e:
            xbmc.log(f"[CBTV-HB] Impossibile scaricare servers.json remoto: {e}", xbmc.LOGWARNING)

    def _update_pool_from_servers(self, servers_data):
        """Aggiorna il pool di MAC e URL del server unendo tutti i server e MAC corrispondenti."""
        if not servers_data or not isinstance(servers_data, list):
            return

        combined_macs = []
        target_portal = None

        for s in servers_data:
            if not isinstance(s, dict):
                continue
            name = s.get("name", "")
            portal = (s.get("portal_url") or s.get("portal") or s.get("url") or "").lower()
            macs = s.get("macs") or s.get("mac_pool") or []

            if "z1mag" in portal or "zeroone" in portal or "zerotv" in portal or name in ["Server 18", "Server 8", "Server 66"]:
                if not target_portal and "z1mag" in portal:
                    target_portal = s.get("portal_url") or s.get("portal") or s.get("url")
                for m in macs:
                    if m and m not in combined_macs:
                        combined_macs.append(m)

        if combined_macs:
            # Assicura che i MAC statici verificati siano sempre presenti
            for m in self.PORTAL_18_MACS:
                if m not in combined_macs:
                    combined_macs.append(m)
            self.mac_pool = combined_macs
            if target_portal:
                self.portal_url = target_portal
            xbmc.log(f"[CBTV-HB] Sincronizzati {len(self.mac_pool)} MAC per {self.server_id} da {self.portal_url}", xbmc.LOGINFO)

    def _get_last_working_mac(self):
        f = os.path.join(self.cache_dir, f"hl_last_mac_{self.server_id}.json")
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    return json.load(fh).get("mac")
            except:
                pass
        return None

    def _set_last_working_mac(self, mac):
        f = os.path.join(self.cache_dir, f"hl_last_mac_{self.server_id}.json")
        try:
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump({"mac": mac}, fh)
        except:
            pass

    def get_top_verified_macs(self):
        """Restituisce la lista dinamica dei Top MAC verificati e funzionanti per questo server."""
        f = os.path.join(self.cache_dir, f"hl_top_macs_{self.server_id}.json")
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                    if isinstance(data, dict):
                        macs = data.get("top_macs", [])
                    elif isinstance(data, list):
                        macs = data
                    else:
                        macs = []
                    return [m for m in macs if m in self.mac_pool]
            except Exception:
                pass
        return []

    def record_top_verified_mac(self, mac):
        """
        Promuove un MAC in cima alla lista dei Top MAC verificati (aggiornamento costante).
        I MAC che partono subito e trasmettono con successo salgono in prima posizione.
        """
        if not mac:
            return
        top_macs = self.get_top_verified_macs()
        if mac in top_macs:
            top_macs.remove(mac)
        top_macs.insert(0, mac)
        top_macs = top_macs[:20]
        f = os.path.join(self.cache_dir, f"hl_top_macs_{self.server_id}.json")
        try:
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump({"top_macs": top_macs, "updated": time.time()}, fh)
            xbmc.log(f"[CBTV-HB] MAC {mac} promosso nei Top MAC di {self.server_id} (Totale Top MAC: {len(top_macs)})", xbmc.LOGINFO)
        except Exception as e:
            xbmc.log(f"[CBTV-HB] Errore salvataggio Top MAC: {e}", xbmc.LOGWARNING)

    def remove_top_verified_mac(self, mac):
        """Rimuove un MAC dalla lista Top MAC quando fallisce o cade la trasmissione."""
        if not mac:
            return
        top_macs = self.get_top_verified_macs()
        if mac in top_macs:
            top_macs.remove(mac)
            f = os.path.join(self.cache_dir, f"hl_top_macs_{self.server_id}.json")
            try:
                with open(f, 'w', encoding='utf-8') as fh:
                    json.dump({"top_macs": top_macs, "updated": time.time()}, fh)
                xbmc.log(f"[CBTV-HB] MAC {mac} rimosso dai Top MAC di {self.server_id} in seguito a fallimento", xbmc.LOGINFO)
            except Exception:
                pass

    def get_channel_working_mac(self, channel_name):
        """Restituisce il MAC memorizzato e associato a questo canale specifico."""
        if not channel_name:
            return None
        safe_key = re.sub(r'[^a-zA-Z0-9_]', '_', channel_name).lower()
        f = os.path.join(self.cache_dir, f"hl_ch_mac_{self.server_id}_{safe_key}.json")
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                    mac = data.get("mac")
                    if mac and mac in self.mac_pool:
                        return mac
            except Exception:
                pass
        return None

    def record_channel_working_mac(self, channel_name, mac):
        """Memorizza l'abbinamento canale -> MAC che lo ha avviato con successo."""
        if not channel_name or not mac:
            return
        safe_key = re.sub(r'[^a-zA-Z0-9_]', '_', channel_name).lower()
        f = os.path.join(self.cache_dir, f"hl_ch_mac_{self.server_id}_{safe_key}.json")
        try:
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump({"mac": mac, "updated": time.time()}, fh)
            xbmc.log(f"[CBTV-HB] Abbinato canale '{channel_name}' -> MAC {mac}", xbmc.LOGINFO)
        except Exception as e:
            xbmc.log(f"[CBTV-HB] Errore salvataggio abbinamento canale-MAC: {e}", xbmc.LOGWARNING)

    def remove_channel_working_mac(self, channel_name):
        """Rimuove l'abbinamento canale -> MAC se il MAC fallisce."""
        if not channel_name:
            return
        safe_key = re.sub(r'[^a-zA-Z0-9_]', '_', channel_name).lower()
        f = os.path.join(self.cache_dir, f"hl_ch_mac_{self.server_id}_{safe_key}.json")
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    def get_busy_macs(self):
        """Restituisce il set di MAC attualmente in quarantena (occupati negli ultimi 10 minuti)."""
        f = os.path.join(self.cache_dir, f"hl_busy_macs_{self.server_id}.json")
        now = time.time()
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return set(m for m, exp in data.items() if exp > now)
            except Exception:
                pass
        return set()

    def record_busy_mac(self, mac, duration_sec=600):
        """Mette un MAC in quarantena temporanea (default 10 minuti)."""
        if not mac:
            return
        f = os.path.join(self.cache_dir, f"hl_busy_macs_{self.server_id}.json")
        now = time.time()
        data = {}
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    raw = json.load(fh)
                    if isinstance(raw, dict):
                        data = {m: exp for m, exp in raw.items() if exp > now}
            except Exception:
                data = {}
        data[mac] = now + duration_sec
        try:
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump(data, fh)
            xbmc.log(f"[CBTV-HB] MAC {mac} in quarantena per {duration_sec}s (totale: {len(data)})", xbmc.LOGINFO)
        except Exception as e:
            xbmc.log(f"[CBTV-HB] Errore salvataggio busy MAC: {e}", xbmc.LOGWARNING)

    def remove_busy_mac(self, mac):
        """Rimuove un MAC dalla quarantena."""
        if not mac:
            return
        f = os.path.join(self.cache_dir, f"hl_busy_macs_{self.server_id}.json")
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                if mac in data:
                    del data[mac]
                    with open(f, 'w', encoding='utf-8') as fh:
                        json.dump(data, fh)
            except Exception:
                pass

    def clear_busy_macs(self):
        """Azzera la lista di quarantena (reset di emergenza)."""
        f = os.path.join(self.cache_dir, f"hl_busy_macs_{self.server_id}.json")
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    # ---- headers / cookies come Hublive originale ----
    def _headers(self, mac=None, token=None):
        h = {
            "User-Agent": self.UA,
            "X-User-Agent": "Model: MAG250; Link: WiFi",
            "Referer": f"{self.portal_url}/stalker_portal/c/index.html",
        }
        if token:
            h["Authorization"] = f"Bearer {token}"
        return h

    def _cookies(self, mac, token=None):
        c = {"mac": mac}
        if token:
            c["token"] = token
        return c

    def _get_session(self, use_proxy=True):
        """Restituisce una sessione HTTP preconfigurata, usando il pool Webshare per bypassare i blocchi AGCOM."""
        if use_proxy and proxy_config:
            try:
                return proxy_config.get_proxy_session()
            except Exception:
                pass
        s = requests.Session()
        s.trust_env = False
        return s

    # ---- handshake ----
    def _handshake(self, mac, timeout=5):
        """Esegue l'handshake Stalker e restituisce il token (o None)."""
        url = f"{self.portal_url}/portal.php"
        params = {"type": "stb", "action": "handshake", "token": "", "JsHttpRequest": "1-xml"}
        headers = self._headers()
        cookies = self._cookies(mac)

        s = requests.Session()
        s.trust_env = False
        try:
            s.cookies.clear()
            r = s.get(url, params=params, headers=headers, cookies=cookies, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    js = data.get("js", {})
                    if isinstance(js, dict) and js.get("token"):
                        return js.get("token")
        except Exception:
            pass

        xbmc.log(f"[CBTV-HB] Handshake fallito per MAC {mac}", xbmc.LOGWARNING)
        return None

    # ---- chiamata API generica ----
    def _api_call(self, mac, token, action, extra_params=None, timeout=12):
        """Chiamata a portal.php — restituisce il campo 'js' della risposta."""
        url = f"{self.portal_url}/portal.php"
        params = {
            "type": "itv",
            "action": action,
            "JsHttpRequest": "1-xml",
        }
        if extra_params:
            params.update(extra_params)

        headers = self._headers(mac, token)
        cookies = self._cookies(mac, token)

        s = requests.Session()
        s.trust_env = False
        try:
            r = s.get(url, params=params, headers=headers, cookies=cookies, timeout=timeout)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, dict):
                    return data.get("js", {})
        except Exception:
            pass

        xbmc.log(f"[CBTV-HB] API call '{action}' fallita", xbmc.LOGWARNING)
        return {}

    # ---- create_link ----
    def create_link(self, mac, token, cmd, timeout=12):
        """Chiama create_link e restituisce (play_token, stream_id) o (None, None)."""
        sid_match = re.search(r'stream=(\d+)', cmd)
        if not sid_match:
            # Fallback: prova formato /ch/XXXXX
            m2 = re.search(r'/ch/(\d+)', cmd)
            if m2:
                stream_id = m2.group(1)
            else:
                xbmc.log(f"[CBTV-HB] Impossibile estrarre stream_id dal cmd: {cmd[:80]}", xbmc.LOGWARNING)
                return None, None
        else:
            stream_id = sid_match.group(1)

        clean_cmd = f"ffmpeg http://localhost/ch/{stream_id}_"
        res = self._api_call(mac, token, "create_link", {"cmd": clean_cmd, "forced_storage": "0", "download": "0"}, timeout=timeout)
        if not isinstance(res, dict):
            return None, None

        returned_cmd = res.get("cmd", "")
        if not returned_cmd:
            return None, None

        url_match = re.search(r"http[^\s]+", returned_cmd)
        if url_match and "live.php" in url_match.group(0):
            return url_match.group(0), None

        play_token_match = re.search(r"play_token=([a-zA-Z0-9]+)", returned_cmd)
        if not play_token_match:
            return None, None

        return play_token_match.group(1), stream_id

    def resolve_stream(self, cmd, exclude_macs=None, channel_name=None, max_tries=1):
        """
        Prova i MAC disponibili (escludendo quelli già falliti e quelli in quarantena) per ottenere un URL di stream.
        Prioritizza l'abbinamento canale-MAC memorizzato, i MAC Full Package e la lista dinamica dei Top MAC.
        Restituisce (final_url, mac_usato) o (None, None).
        """
        if exclude_macs is None:
            exclude_macs = set()

        pool = list(self.mac_pool)

        # 0. Quarantena: escludi MAC occupati/bloccati negli ultimi 10 minuti
        busy_macs = self.get_busy_macs()
        if busy_macs:
            available = [m for m in pool if m not in busy_macs]
            if not available:
                xbmc.log(f"[CBTV-HB] Tutti i MAC del pool erano in quarantena per {self.server_id}! Reset emergenza.", xbmc.LOGWARNING)
                self.clear_busy_macs()
            else:
                xbmc.log(f"[CBTV-HB] Esclusi {len(busy_macs)} MAC in quarantena temporanea (occupati)", xbmc.LOGINFO)
                pool = available
        
        # Escludi MAC già falliti in questa sessione
        if exclude_macs:
            pool = [m for m in pool if m not in exclude_macs]
        
        # Mescola casualmente per ruotare ed esplorare nuovi MAC
        random.shuffle(pool)

        # 1. Prioritizza i Top MAC verificati (quelli che sono partiti subito nelle sessioni recenti)
        top_verified = [m for m in self.get_top_verified_macs() if m in pool]
        for v_mac in reversed(top_verified):
            pool.remove(v_mac)
            pool.insert(0, v_mac)

        # 2. Inserisci il Last Working MAC del server (se libero)
        last_working = self._get_last_working_mac()
        if last_working and last_working in pool:
            pool.remove(last_working)
            pool.insert(0, last_working)

        # 3. PRIORITÀ ASSOLUTA: MAC memorizzato specificamente per questo canale (se libero)
        ch_mac = self.get_channel_working_mac(channel_name) if channel_name else None
        if ch_mac and ch_mac in pool:
            pool.remove(ch_mac)
            pool.insert(0, ch_mac)
            xbmc.log(f"[CBTV-HB] Canale '{channel_name}': prioritizzato MAC memorizzato {ch_mac}", xbmc.LOGINFO)

        # Limita i tentativi al numero specificato (default 1 per rispetto del server e pause umane controllate)
        if max_tries:
            pool = pool[:max_tries]
        
        if not pool:
            xbmc.log(f"[CBTV-HB] Tutti i MAC disponibili sono stati esauriti per {self.server_id}", xbmc.LOGWARNING)
            return None, None

        for attempt, mac in enumerate(pool, 1):
            is_top = mac in top_verified or mac == last_working or (ch_mac and mac == ch_mac)
            xbmc.log(f"[CBTV-HB] Tentativo {attempt}/{len(pool)} con MAC: {mac} (Top: {is_top})", xbmc.LOGINFO)

            # 1. Handshake con timeout di sicurezza (3.0s per stabilità su mobile/Wi-Fi)
            token = self._handshake(mac, timeout=3.0)
            if not token:
                xbmc.log(f"[CBTV-HB] Handshake fallito per MAC {mac}", xbmc.LOGWARNING)
                exclude_macs.add(mac)
                self.record_busy_mac(mac, duration_sec=300)
                continue

            # 2. create_link con timeout di sicurezza (3.5s)
            url_or_token, stream_id_out = self.create_link(mac, token, cmd, timeout=3.5)
            if not url_or_token:
                xbmc.log(f"[CBTV-HB] create_link fallito per MAC {mac}", xbmc.LOGWARNING)
                exclude_macs.add(mac)
                self.record_busy_mac(mac, duration_sec=300)
                continue

            # 3. Costruisci URL finale
            if stream_id_out is None and url_or_token.startswith("http"):
                final_url = re.sub(r"http[s]?://[^/]+", self.portal_url, url_or_token)
            else:
                final_url = (f"{self.portal_url}/play/live.php"
                             f"?mac={mac}&stream={stream_id_out}&extension=ts&play_token={url_or_token}")

            # 4. Verifica stream ed estrazione rapida redirect CDN
            try:
                v_session = requests.Session()
                v_session.trust_env = False
                with v_session.get(final_url, headers={"User-Agent": self.UA}, cookies={"mac": mac}, timeout=(3.0, 3.5), stream=True, allow_redirects=True) as r_play:
                    if r_play.status_code >= 400:
                        xbmc.log(f"[CBTV-HB] MAC {mac} HTTP error {r_play.status_code} (linea occupata/vietata)", xbmc.LOGWARNING)
                        exclude_macs.add(mac)
                        self.record_busy_mac(mac, duration_sec=600)  # Quarantena 10 min
                        self.remove_top_verified_mac(mac)
                        if ch_mac and mac == ch_mac:
                            self.remove_channel_working_mac(channel_name)
                        continue

                    final_dest = str(r_play.url)
                    final_dest_lower = final_dest.lower()
                    content_type = (r_play.headers.get("Content-Type") or "").lower()

                    if "black.ts" in final_dest_lower or "85.18.95.155" in final_dest_lower or "text/html" in content_type:
                        xbmc.log(f"[CBTV-HB] MAC {mac} bloccato o black.ts ({final_dest[:60]})", xbmc.LOGWARNING)
                        exclude_macs.add(mac)
                        self.record_busy_mac(mac, duration_sec=600)
                        continue

                    head = r_play.raw.read(188)
                    if not head or head.startswith(b'\x1f\x8b\x08') or b"Sito Illegale" in head or b"AGCOM" in head:
                        xbmc.log(f"[CBTV-HB] MAC {mac} non valido o vuoto", xbmc.LOGWARNING)
                        exclude_macs.add(mac)
                        self.record_busy_mac(mac, duration_sec=300)
                        continue

                # 5. Linea verificata e funzionante al 100%!
                dest_url = final_dest or final_url
                if dest_url.startswith("http") and "black.ts" not in dest_url.lower():
                    # Assicura estensione .ts per corretta inizializzazione del demuxer su Android
                    if "?" not in dest_url and not dest_url.lower().endswith(".ts"):
                        dest_url = f"{dest_url}.ts"
                    final_url_with_ua = f"{dest_url}|User-Agent={quote_plus(self.UA)}"
                else:
                    final_url_with_ua = f"{final_url}|User-Agent={quote_plus(self.UA)}"
                xbmc.log(f"[CBTV-HB] Stream risolto con successo usando MAC {mac} -> {dest_url[:80]}", xbmc.LOGINFO)
                
                # Salva come Last Working MAC e promuovi nei Top MAC
                self.remove_busy_mac(mac)
                self._set_last_working_mac(mac)
                self.record_top_verified_mac(mac)
                if channel_name:
                    self.record_channel_working_mac(channel_name, mac)
                
                return final_url_with_ua, mac
            except requests.exceptions.ReadTimeout:
                xbmc.log(f"[CBTV-HB] MAC {mac} ReadTimeout (linea occupata o nessun pacchetto video ricevuto)", xbmc.LOGWARNING)
                if ch_mac and mac == ch_mac:
                    self.remove_channel_working_mac(channel_name)
                exclude_macs.add(mac)
                self.record_busy_mac(mac, duration_sec=300)
                continue
            except Exception as e:
                xbmc.log(f"[CBTV-HB] MAC {mac} timeout/errore verifica: {e}", xbmc.LOGWARNING)
                if ch_mac and mac == ch_mac:
                    self.remove_channel_working_mac(channel_name)
                exclude_macs.add(mac)
                self.record_busy_mac(mac, duration_sec=300)
                continue

        # Se tutti i MAC di questo batch erano occupati o non validi, restituisci None
        return None, None

    # ---- cache ----
    CACHE_VERSION = "3.3.30"  # Incrementare ad ogni cambio nella logica di fetch/filtro canali

    def _load_fallback(self, filename):
        """Carica la lista canali pre-integrata nel pacchetto addon per apertura istantanea (<0.05s)."""
        fallback_path = os.path.join(os.path.dirname(__file__), filename)
        if os.path.exists(fallback_path):
            try:
                with open(fallback_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                xbmc.log(f"[CBTV-HB] Errore lettura fallback {filename}: {e}", xbmc.LOGWARNING)
        return []

    def _get_cache(self, key):
        f = os.path.join(self.cache_dir, f"hl_{self.server_id}_{key}.json")
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    d = json.load(fh)
                    if d.get('v') != self.CACHE_VERSION:
                        return None
                    if time.time() - d.get('ts', 0) < 43200:
                        return d.get('data')
            except: pass
        return None

    def _set_cache(self, key, data):
        f = os.path.join(self.cache_dir, f"hl_{self.server_id}_{key}.json")
        try:
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump({'ts': time.time(), 'v': self.CACHE_VERSION, 'data': data}, fh)
        except: pass

    # ---- get_genres / lookup ----
    def _get_working_token_and_mac(self):
        """Ruota i MAC finché non ne trova uno che esegue l'handshake con successo, prioritizzando Top MAC e Last Working MAC."""
        pool = list(self.mac_pool)
        random.shuffle(pool)
        
        top_verified = [m for m in self.get_top_verified_macs() if m in pool]
        for v_mac in reversed(top_verified):
            pool.remove(v_mac)
            pool.insert(0, v_mac)

        last_working = self._get_last_working_mac()
        if last_working and last_working in pool:
            pool.remove(last_working)
            pool.insert(0, last_working)

        for mac in pool:
            token = self._handshake(mac, timeout=2.5)
            if token:
                self._set_last_working_mac(mac)
                return token, mac
        return None, None

    def get_genres(self):
        """Scarica e memorizza in cache le categorie (genres) del portale."""
        cached = self._get_cache("genres")
        if cached:
            return cached

        token, mac = self._get_working_token_and_mac()
        if not token:
            xbmc.log(f"[CBTV-HB] Impossibile trovare un MAC funzionante per get_genres ({self.server_id})", xbmc.LOGWARNING)
            return []

        res = self._api_call(mac, token, "get_genres", timeout=6)
        if isinstance(res, list) and len(res) > 0:
            self._set_cache("genres", res)
            return res

        fallback_genres = [
            {"id": "923", "title": "IT ✨ SPORT"},
            {"id": "1233", "title": "IT ✨ DAZN"},
            {"id": "924", "title": "IT ✨ CINEMA"},
            {"id": "922", "title": "IT ✨ ITALIA"},
            {"id": "925", "title": "IT ✨ CULTURA"},
            {"id": "1332", "title": "IT ✨ HEVC"}
        ]
        self._set_cache("genres", fallback_genres)
        return fallback_genres

    def _find_genre_ids_by_titles(self, target_titles):
        """Trova gli ID dei generi in base ai titoli cercati."""
        genres = self.get_genres()
        return [g["id"] for g in genres if (g.get("title") or g.get("name") or "").strip() in target_titles]

    # ---- scaricamento lista canali per genere ----
    def _fetch_channels_for_genres(self, genre_ids, cache_key, keywords=None, negatives=None, force=False):
        if not genre_ids:
            return []
            
        if not force:
            cached = self._get_cache(cache_key)
            if cached:
                return cached

        token, mac = self._get_working_token_and_mac()
        if not token:
            xbmc.log(f"[CBTV-HB] Impossibile trovare un MAC funzionante per listing canali ({self.server_id})", xbmc.LOGWARNING)
            return []

        found = []

        def fetch_genre(gid):
            genre_found = []
            for page in range(1, 30):
                res = self._api_call(mac, token, "get_ordered_list",
                                     {"genre": str(gid), "force_ch_link_check": "0", "p": str(page)}, timeout=6.0)

                if isinstance(res, dict) and 'data' in res:
                    ch_list = res['data']
                elif isinstance(res, list):
                    ch_list = res
                else:
                    # Prova get_ordered_channels se get_ordered_list non ha restituito dati
                    if page == 1:
                        res_alt = self._api_call(mac, token, "get_ordered_channels", {"genre": str(gid)}, timeout=6.0)
                        if isinstance(res_alt, dict) and 'data' in res_alt:
                            ch_list = res_alt['data']
                        elif isinstance(res_alt, list):
                            ch_list = res_alt
                        else:
                            break
                    else:
                        break

                if not ch_list:
                    break

                for ch in ch_list:
                    if not isinstance(ch, dict):
                        continue
                    cmd = ch.get('cmd')
                    if not cmd:
                        continue
                    name_raw = ch.get('name', '')
                    name_up = name_raw.upper()

                    if keywords and not any(k in name_up for k in keywords):
                        continue
                    if negatives and any(nk in name_up for nk in negatives):
                        continue

                    genre_found.append({'name': clean_text(name_raw), 'cmd': cmd})

                # Se la pagina ha meno di 14 canali (dimensione pagina Stalker standard), non ci sono altre pagine
                if len(ch_list) < 14:
                    break
            return genre_found

        # Scaricamento sequenziale per evitare disconnessioni/502 Bad Gateway del server Stalker
        for gid in genre_ids:
            try:
                g_chans = fetch_genre(gid)
                if g_chans:
                    found.extend(g_chans)
            except Exception as e:
                xbmc.log(f"[CBTV-HB] Errore scaricamento canali per genere {gid}: {e}", xbmc.LOGWARNING)

        # Deduplica e ordina
        unique = list({v['cmd']: v for v in found}.values())
        
        import re
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
            
        unique.sort(key=lambda x: natural_sort_key(x['name']))

        if unique:
            self._set_cache(cache_key, unique)
        return unique

    # ---- API pubblica con logica Fallback ----
    def get_sky_tv_channels(self, force_refresh=False):
        """Canali Intrattenimento, Serie TV e Documentari. Caricamento istantaneo con ricarica opzionale."""
        if not force_refresh:
            cached = self._get_cache("sky_tv")
            if cached and len(cached) > 5:
                return cached
            fallback = self._load_fallback("sky_tv_fallback.json")
            if fallback:
                self._set_cache("sky_tv", fallback)
                return fallback

        target_titles = [
            "IT ✨ ITALIA", "IT ✨ CULTURA", "IT ✨ HEVC",
            "┃IT┃ FILM E SERIE", "┃IT┃ DOCUMENTARIO", "┃IT┃ ITALIA HD | RIGIOCARE ⏺",
            "IT| INTRATTENIMENTO", "IT| DOCUMENTARIO", "IT| GENERALE"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids:
            gids = ["922", "925", "1332"]
        channels = self._fetch_channels_for_genres(gids, "sky_tv",
            keywords=["SKY UNO", "SKY ATLANTIC", "SKY DOCUMENTARIES", "SKY NATURE", "SKY ARTE", "SKY INVESTIGATION", "SKY CRIME", "SKY SERIE", "HISTORY", "DISCOVERY CHANNEL", "DISCOVERY TURBO", "GAMBERO ROSSO", "SKY TG24"],
            negatives=["SPORT", "DAZN", "CALCIO", "F1", "MOTOGP", "PRIMAFILA", "CINEMA", "SERIE A", "SERIE B", "BASKET", "BAR"],
            force=force_refresh)
            
        if not channels:
            xbmc.log("[CBTV-HB] get_sky_tv_channels vuoto/timeout, carico sky_tv_fallback.json integrato", xbmc.LOGWARNING)
            channels = self._load_fallback("sky_tv_fallback.json")
            if channels:
                self._set_cache("sky_tv", channels)
            
        return channels

    def get_sky_cinema_channels(self, force_refresh=False):
        """Canali Sky Cinema. Caricamento istantaneo con ricarica opzionale."""
        if not force_refresh:
            cached = self._get_cache("sky_cinema")
            if cached and len(cached) > 5:
                return cached
            fallback = self._load_fallback("sky_cinema_fallback.json")
            if fallback:
                self._set_cache("sky_cinema", fallback)
                return fallback

        target_titles = [
            "IT ✨ CINEMA", "┃IT┃ FILM E SERIE", "IT| CINEMA"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids:
            gids = ["924"]
        channels = self._fetch_channels_for_genres(gids, "sky_cinema",
            keywords=["CINEMA"],
            negatives=["SPORT", "DAZN", "CALCIO", "PRIMAFILA"],
            force=force_refresh)
            
        if not channels:
            xbmc.log("[CBTV-HB] get_sky_cinema_channels vuoto/timeout, carico sky_cinema_fallback.json integrato", xbmc.LOGWARNING)
            channels = self._load_fallback("sky_cinema_fallback.json")

        def cinema_sort_key(c):
            n = c.get('name', '').upper()
            if 'CINEMA UNO +' in n: order = 2
            elif 'CINEMA UNO' in n: order = 1
            elif 'CINEMA DUE +' in n: order = 4
            elif 'CINEMA DUE' in n: order = 3
            elif 'ACTION' in n: order = 5
            elif 'COLLECTION' in n: order = 6
            elif 'COMEDY' in n: order = 7
            elif 'FAMILY' in n: order = 8
            elif 'SUSPENSE' in n or 'SUSPENCE' in n: order = 9
            elif 'ROMANCE' in n: order = 10
            elif 'DRAMA' in n: order = 11
            else: order = 12
            return (order, n)

        channels.sort(key=cinema_sort_key)
        self._set_cache("sky_cinema", channels)
        return channels

    def get_sky_sport_channels(self, force_refresh=False):
        """Canali Sky Sport. Caricamento istantaneo con ricarica opzionale."""
        if not force_refresh:
            cached = self._get_cache("sky_sport")
            if cached and len(cached) > 10:
                return cached
            channels = self._load_fallback("sky_sport_fallback.json")
            if channels:
                self._set_cache("sky_sport", channels)
                return channels

        target_titles = [
            "IT ✨ SPORT", "┃IT┃ SKY SPORT", "┃IT┃ SKY CALCIO", "┃IT┃ SPORT",
            "IT| SPORT", "IT| FORMULA 1 / MOTOGP", "IT| SERIE A/B/C"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids:
            gids = ["923"]
        channels = self._fetch_channels_for_genres(gids, "sky_sport", 
            keywords=["SKY SPORT", "SKY CALCIO", "EUROSPORT", "SUPERTENNIS"],
            negatives=["SERIE C", "SERIE D", "LEGA PRO", "BAR", "DAZN BAR", "DAZN CHANNEL", "VETRINA DAZN", "WOMEN"],
            force=force_refresh)
            
        if not channels:
            xbmc.log("[CBTV-HB] get_sky_sport_channels vuoto/timeout, carico sky_sport_fallback.json integrato", xbmc.LOGWARNING)
            channels = self._load_fallback("sky_sport_fallback.json")

        def sky_sport_sort_key(ch):
            n = ch.get('name', '').upper().strip()
            if "24" in n: return (1, n)
            if "UNO" in n: return (2, n)
            if "CALCIO FHD" in n or "CALCIO HEVC" in n: return (3, n)
            if "F1" in n: return (4, n)
            if "MOTOGP" in n or "MOTO GP" in n: return (5, n)
            if "TENNIS" in n: return (6, n)
            if "ARENA" in n: return (7, n)
            if "GOLF" in n: return (8, n)
            if "MAX" in n: return (9, n)
            if "NBA" in n: return (10, n)
            if "CALCIO 251" in n: return (11, n)
            if "CALCIO 252" in n: return (12, n)
            if "CALCIO 253" in n: return (13, n)
            if "CALCIO 254" in n: return (14, n)
            if "CALCIO 255" in n: return (15, n)
            if "CALCIO 256" in n: return (16, n)
            if "CALCIO 257" in n: return (17, n)
            if "EUROSPORT 1" in n: return (18, n)
            if "EUROSPORT 2" in n: return (19, n)
            return (20, n)

        channels.sort(key=sky_sport_sort_key)
        self._set_cache("sky_sport", channels)
        return channels

    def get_dazn_channels(self, force_refresh=False):
        """Canali DAZN essenziali. Caricamento istantaneo con ricarica opzionale."""
        if not force_refresh:
            cached = self._get_cache("dazn")
            if cached and len(cached) > 5:
                return cached
            fallback = self._load_fallback("dazn_fallback.json")
            if fallback:
                self._set_cache("dazn", fallback)
                return fallback

        target_titles = [
            "IT ✨ DAZN", "IT| SERIE A/B/C", "IT| DAZN VIP HD/4K", "IT| DAZN PPV", "IT| DAZN",
            "┃IT┃ ZONA DAZN", "┃IT┃ DAZN", "┃IT┃ DAZN SERIE A"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids:
            gids = ["1233"]

        channels = self._fetch_channels_for_genres(gids, "dazn",
            keywords=None,
            negatives=["WOMEN", "PALLAVOLO", "PALLAMANO", "PALLANUOTO"],
            force=force_refresh)
            
        if not channels:
            xbmc.log("[CBTV-HB] get_dazn_channels vuoto o incompleto, carico dazn_fallback.json integrato", xbmc.LOGINFO)
            channels = self._load_fallback("dazn_fallback.json")

        if channels:
            import re
            filtered = [ch for ch in channels if not any(k in ch.get('name', '').upper() for k in ["PALLAVOLO", "PALLAMANO", "PALLANUOTO"])]

            def dazn_sort_key(ch):
                name = ch.get('name', '').upper()
                if "DAZN 1" in name or "ZONA DAZN" in name:
                    group = 1
                elif "DAZN 2" in name:
                    group = 2
                elif "DAZN" in name and any(f"DAZN {i}" in name for i in range(3, 15)):
                    group = 3
                elif "SERIE A" in name:
                    group = 4
                elif "SERIE B" in name:
                    group = 5
                elif "EVENT" in name:
                    group = 6
                else:
                    group = 7
                
                num_match = re.search(r'\d+', name)
                num = int(num_match.group()) if num_match else 1
                return (group, num, name)
                
            filtered.sort(key=dazn_sort_key)
            channels = filtered
            self._set_cache("dazn", channels)
            
        return channels

    def get_primafila_channels(self):
        """Retrocompatibilità: reindirizza istantaneamente ai canali Cinema evitando timeout"""
        return self.get_sky_cinema_channels()

    def get_foreign_sport_channels(self, group, force_refresh=False):
        """Ottiene i canali per il gruppo sportivo estero selezionato da Server 31 con fallback istantaneo."""
        cache_key = f"foreign_{group.replace(' ', '_').replace('/', '_')}"
        if not force_refresh:
            cached = self._get_cache(cache_key)
            if cached and len(cached) > 0:
                return cached
            # Apertura istantanea da file locale pre-integrato (582 canali)
            fallback_dict = self._load_fallback("foreign_sports_fallback.json")
            if isinstance(fallback_dict, dict) and group in fallback_dict:
                fallback_ch = fallback_dict[group]
                if fallback_ch:
                    self._set_cache(cache_key, fallback_ch)
                    return fallback_ch

        target_titles = []
        filter_keywords = []
        
        if group == "TNT / UK SPORT":
            target_titles = [
                "┃UK┃ TNT SPORTS FHD", "┃UK┃ TNT SPORTS HEVC", "┃UK┃ TNT SPORTS RAW DOLBY",
                "┃UK┃ TNT SPORTS EVENT", "┃UK┃ SKY SPORTS FHD", "┃UK┃ SKY SPORTS RAW DOLBY",
                "┃UK┃ SKY SPORTS HEVC", "┃UK┃ PREMIER SPORTS"
            ]
            filter_keywords = ["TNT", "SKY", "PREMIER"]
        elif group == "POLSAT / PL SPORT":
            target_titles = ["┃PL┃ CANAL+ SPORT", "┃PL┃ POLSAT SPORT", "┃PL┃ ELEVEN SPORTS"]
            filter_keywords = ["POLSAT", "ELEVEN", "CANAL+"]
        elif group == "ZIGGO / NL SPORT":
            target_titles = ["┃NL┃ ZIGGO KABEL", "┃NL┃ VIAPLAY SPORT", "┃NL┃ ESPN WATCH", "┃NL┃ SPORT TV+"]
            filter_keywords = ["ZIGGO", "VIAPLAY", "ESPN", "SPORT"]
        elif group == "S SPORT / TR SPORT":
            target_titles = [
                "┃TR┃ S SPORTS", "┃TR┃ BEIN SPORTS RAW", "┃TR┃ BEIN SPORTS FHD",
                "┃TR┃ EXXEN SPORTS", "┃TR┃ BEIN CONNECT", "┃TR┃ BEIN PLATFORM"
            ]
            filter_keywords = ["S SPORT", "EXXEN", "BEIN", "SPOR"]
        elif group == "COSMOTE / GR SPORT":
            target_titles = ["┃GR┃ NOVA SPORTS", "┃GR┃ MAGENTA SPORTS", "┃GR┃ SPORTS | ΑΘΛΗΤΙΚΑ"]
            filter_keywords = ["COSMOTE", "NOVA", "ANT1", "MAGENTA", "SPORT"]
        elif group == "MAX SPORT / BG SPORT":
            target_titles = ["┃BG┃ BULGARIA"]
            filter_keywords = ["DIEMA", "MAX SPORT", "MAX", "RING", "SPORT"]
        elif group == "DAZN / ES SPORT":
            target_titles = ["┃ES┃ DAZN LA LIGA", "┃ES┃ DAZN ESPAÑA", "┃ES┃DAZN MUNDIAL 2026"]
            filter_keywords = ["DAZN", "LALIGA", "SPORT"]
        elif group == "CANAL+ / FR SPORT":
            target_titles = ["┃FR┃ MY CANAL+ SPORT", "┃FR┃ RMC SPORT", "┃FR┃ BEIN SPORTS", "┃FR┃ CANAL+ LIVE"]
            filter_keywords = ["CANAL", "RMC", "BEIN", "SPORT"]
            
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids:
            genres = self.get_genres()
            gids = [g["id"] for g in genres if any(t in g.get("title", "") for t in target_titles)]

        channels = []
        if gids:
            channels = self._load_and_filter_foreign_channels(gids, cache_key, filter_keywords, force=force_refresh)
            
        if not channels:
            fallback_dict = self._load_fallback("foreign_sports_fallback.json")
            if isinstance(fallback_dict, dict) and group in fallback_dict:
                channels = fallback_dict[group]
                if channels:
                    self._set_cache(cache_key, channels)

        return channels

    def _load_and_filter_foreign_channels(self, gids, cache_key, filter_keywords, force=False):
        channels = []
        seen_cmds = set()
        ch_list = self._fetch_channels_for_genres(gids, cache_key, force=force)
        for ch in ch_list:
            name = ch.get("name", "")
            cmd = ch.get("cmd", "")
            if not cmd:
                continue
            if not filter_keywords or any(kw in name.upper() for kw in filter_keywords):
                if cmd not in seen_cmds:
                    seen_cmds.add(cmd)
                    channels.append({
                        "name": clean_text(name),
                        "cmd": cmd
                    })
        import re
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
        channels.sort(key=lambda x: natural_sort_key(x["name"]))
        return channels

    def _normalize_channel_name(self, name):
        if not name:
            return ""
        name = name.upper()
        # Rimuove tag colore e box drawing
        name = re.sub(r'\[COLOR[^\]]*\]', '', name)
        name = re.sub(r'\[/COLOR\]', '', name)
        name = re.sub(r'[\u2500-\u259F]', '', name)
        
        # Rimuove prefissi paese comuni (IT, ITA, ecc.) seguiti da spazi, due punti o pipe
        name = re.sub(r'^(IT|ITA|ITALIA|ITALY)\s*[:| ]\s*', '', name)
        
        # Rimuove suffissi di qualità/formato alla fine del nome o come parole isolate
        name = re.sub(r'\b(4K|2K|HD|FHD|UHD|SD|HEVC|H265|RAW|50FPS|60FPS|VIP|BACKUP|NEW|PORTUGAL|SPAIN)\b', '', name)
        
        # Rimuove tutti i caratteri non alfanumerici e gli spazi
        name = re.sub(r'[^A-Z0-9]', '', name)
        return name.strip()

    # ---- Ricerca fallback canale per nome ----
    def find_channel_cmd_by_name(self, name):
        """Cerca un canale per nome su Server 50, caricando le cache se necessario."""
        if not name:
            return None
        norm_target = self._normalize_channel_name(name)
        if not norm_target:
            return None
            
        # 1. Trova a quale categoria s28 apparteneva questo canale analizzando le cache esistenti
        category_key = None
        cache_files = []
        try:
            cache_files = os.listdir(self.cache_dir)
        except:
            pass
            
        for fn in cache_files:
            if fn.startswith("hl_s28_") and fn.endswith(".json") and "genres" not in fn:
                try:
                    with open(os.path.join(self.cache_dir, fn), 'r', encoding='utf-8') as fh:
                        d = json.load(fh)
                        for ch in d.get('data', []):
                            if self._normalize_channel_name(ch.get('name', '')) == norm_target:
                                category_key = fn.replace("hl_s28_", "").replace(".json", "")
                                break
                except:
                    pass
                if category_key:
                    break
                    
        if not category_key:
            # Fallback: cerca nelle cache s31 già caricate
            for fn in cache_files:
                if fn.startswith("hl_s31_") and fn.endswith(".json") and "genres" not in fn:
                    try:
                        with open(os.path.join(self.cache_dir, fn), 'r', encoding='utf-8') as fh:
                            d = json.load(fh)
                            for ch in d.get('data', []):
                                if self._normalize_channel_name(ch.get('name', '')) == norm_target:
                                    return ch.get('cmd')
                    except:
                        pass
            return None
            
        # 2. Cerca nella cache s31 specifica se presente
        s31_fn = f"hl_s31_{category_key}.json"
        if s31_fn in cache_files:
            try:
                with open(os.path.join(self.cache_dir, s31_fn), 'r', encoding='utf-8') as fh:
                    d = json.load(fh)
                    for ch in d.get('data', []):
                        if self._normalize_channel_name(ch.get('name', '')) == norm_target:
                            return ch.get('cmd')
            except:
                pass
                
        return None
