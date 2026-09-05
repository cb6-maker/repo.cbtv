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

# ---------- utilità ----------
def clean_text(text):
    """Rimuove tag [COLOR], simboli box-drawing e prefissi paese da nomi canale."""
    text = re.sub(r'\[COLOR[^\]]*\]', '', text)
    text = re.sub(r'\[/COLOR\]', '', text)
    # Rimuovi box-drawing chars (─ │ etc.)
    text = re.sub(r'[\u2500-\u259F]', '', text)
    # Rimuovi prefissi tipo "IT|" o "IT:" o "IT |" o "IT :"
    text = re.sub(r'^[A-Z]{2}\s*[:|]\s*', '', text)
    return text.strip()


class HubliveStalkerClient:
    """Client Stalker con supporto multi-server e fallback automatico tra Server 28 e Server 11."""

    # Server 28 / Server 31 (Primario)
    PORTAL_1_URL = "http://pro.most8knew.com:80"
    PORTAL_1_MACS = [
        "A0:BB:3E:00:08:9F", "A0:BB:3E:00:0A:CD", "A0:BB:3E:00:0A:CB", "00:1A:79:7B:20:DE",
        "00:1A:79:36:33:37", "00:1A:79:B6:E1:AD", "00:1A:79:B6:CB:B8", "00:1A:79:B6:E6:77",
        "A0:BB:3E:00:06:EE", "00:1A:79:B5:B6:D5", "00:1A:79:81:F3:59", "A0:BB:3E:00:0A:B5"
    ]

    # Server 29 / Server 50 (Fallback)
    PORTAL_2_URL = "http://line.watchtivo-8k.com:80"
    PORTAL_2_MACS = [
        "00:1A:79:97:29:31", "00:1A:79:17:04:D7", "00:1A:79:00:00:00", "00:1A:79:00:22:D5",
        "00:1A:79:BB:F6:57", "00:1A:79:C8:7B:30", "00:1A:79:C7:10:76", "00:1A:79:BF:D9:75",
        "00:1A:79:CD:F2:84", "00:1A:79:7E:71:A1", "00:1A:79:A8:B7:16", "00:1A:79:84:EB:56",
        "00:1A:79:AD:0E:30", "00:1A:79:F1:F1:CA", "00:1A:79:17:2E:14", "00:1A:79:17:1B:15",
        "00:1A:79:0C:42:DE", "00:1A:79:B6:26:F7", "00:1A:79:09:1C:05", "00:1A:79:18:1A:57",
        "00:1A:79:B5:0D:A0", "00:1A:79:C7:CB:94", "00:1A:79:9D:4A:60", "00:1A:79:5D:AB:3B",
        "00:1A:79:C6:F6:F6", "00:1A:79:B6:42:BD", "00:1A:79:74:AB:3F", "00:1A:79:18:12:E8",
        "00:1A:79:69:38:2E", "00:1A:79:85:5C:A4", "00:1A:79:F5:3F:55", "00:1A:79:7E:24:C3",
        "00:1A:79:0B:B9:9B", "00:1A:79:A9:1C:50", "00:1A:79:39:DA:D6", "00:1A:79:A0:E8:37",
        "00:1A:79:C6:1B:54", "00:1A:79:B1:58:AB", "00:1A:79:DC:88:87", "00:1A:79:8B:56:DA",
        "00:1A:79:C3:2F:08", "00:1A:79:C6:DA:B6", "00:1A:79:90:19:6E", "00:1A:79:16:C3:C7",
        "00:1A:79:B6:5E:6C", "00:1A:79:DB:8E:FE", "00:1A:79:BF:E0:1A", "00:1A:79:BF:B5:5B",
        "00:1A:79:1C:10:51", "00:1A:79:0B:C1:2A", "00:1A:79:B6:23:16", "00:1A:79:F1:B3:3D"
    ]

    REMOTE_HUB_URL = "https://raw.githubusercontent.com/staycanuca/hub/main/servers.json"

    UA = ("Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
          "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3")

    # ---- inizializzazione ----
    def __init__(self, server_id="s28"):
        self.server_id = server_id
        if server_id == "s50":
            self.portal_url = self.PORTAL_2_URL
            self.mac_pool = list(self.PORTAL_2_MACS)
        else:
            self.portal_url = self.PORTAL_1_URL
            self.mac_pool = list(self.PORTAL_1_MACS)

        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        self.cache_dir = os.path.join(profile, "hublive")
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

        # Applica subito i server/MAC dalla cache su disco se presenti (<1ms)
        self._apply_cached_servers()

        # Sincronizzazione remota in background per non bloccare mai la UI di Kodi
        import threading
        threading.Thread(target=self._sync_remote_servers, kwargs={"force": False}, daemon=True).start()

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
        """Aggiorna il pool di MAC e URL del server in base ai dati scaricati."""
        if not servers_data or not isinstance(servers_data, list):
            return

        target_server = None
        for s in servers_data:
            if not isinstance(s, dict):
                continue
            name = s.get("name", "")
            portal = (s.get("portal_url") or s.get("portal") or s.get("url") or "").lower()

            if self.server_id == "s50":
                if name in ["Server 29", "Server 50"] or "watchtivo" in portal or "tvdsz" in portal:
                    if s.get("macs") or s.get("mac_pool"):
                        target_server = s
                        break
            else:
                if name in ["Server 28", "Server 31"] or "most8k" in portal or "light-ott" in portal:
                    if s.get("macs") or s.get("mac_pool"):
                        target_server = s
                        break

        if target_server:
            remote_macs = target_server.get("macs") or target_server.get("mac_pool") or []
            remote_portal = target_server.get("portal_url") or target_server.get("portal") or target_server.get("url")
            if remote_macs:
                self.mac_pool = list(remote_macs)
            if remote_portal:
                self.portal_url = remote_portal
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

    # ---- headers / cookies come Hublive originale ----
    def _headers(self, mac=None):
        h = {
            "User-Agent": self.UA,
            "X-User-Agent": "Model: MAG250; Link: WiFi",
            "Referer": f"{self.portal_url}/stalker_portal/c/index.html",
        }
        return h

    def _cookies(self, mac, token=None):
        c = {"mac": mac}
        if token:
            c["token"] = token
        return c

    # ---- handshake ----
    def _handshake(self, mac, timeout=5):
        """Esegue l'handshake Stalker e restituisce il token (o None)."""
        session = requests.Session()
        session.cookies.clear()
        url = f"{self.portal_url}/portal.php"
        params = {"type": "stb", "action": "handshake", "token": "", "JsHttpRequest": "1-xml"}
        try:
            r = session.get(url, params=params,
                            headers=self._headers(),
                            cookies=self._cookies(mac),
                            timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                js = data.get("js", {})
                if isinstance(js, dict):
                    return js.get("token")
            return None
        except Exception as e:
            xbmc.log(f"[CBTV-HB] Handshake fallito per MAC {mac}: {e}", xbmc.LOGWARNING)
            return None

    # ---- chiamata API generica ----
    def _api_call(self, mac, token, action, extra_params=None, timeout=12):
        """Chiamata a portal.php — restituisce il campo 'js' della risposta."""
        session = requests.Session()
        url = f"{self.portal_url}/portal.php"
        params = {
            "type": "itv",
            "action": action,
            "JsHttpRequest": "1-xml",
        }
        if extra_params:
            params.update(extra_params)

        headers = self._headers()
        cookies = self._cookies(mac, token)

        try:
            r = session.get(url, params=params, headers=headers, cookies=cookies, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                return data.get("js", {})
            return {}
        except Exception as e:
            xbmc.log(f"[CBTV-HB] API call '{action}' fallita: {e}", xbmc.LOGWARNING)
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

    def resolve_stream(self, cmd, exclude_macs=None):
        """
        Prova i MAC disponibili (escludendo quelli già falliti) per ottenere un URL di stream.
        Prioritizza la lista dinamica dei Top MAC (quelli che partono subito) e la aggiorna costantemente.
        Restituisce (final_url, mac_usato) o (None, None).
        """
        if exclude_macs is None:
            exclude_macs = set()

        pool = list(self.mac_pool)
        
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

        # 2. Inserisci il Last Working MAC in cima al pool (priorità assoluta)
        last_working = self._get_last_working_mac()
        if last_working and last_working in pool:
            pool.remove(last_working)
            pool.insert(0, last_working)

        # Prova fino a 5 MAC per chiamata
        pool = pool[:5]
        
        if not pool:
            xbmc.log(f"[CBTV-HB] Tutti i MAC sono stati esauriti per {self.server_id}", xbmc.LOGWARNING)
            return None, None

        first_fallback_url = None
        first_fallback_mac = None

        for attempt, mac in enumerate(pool, 1):
            is_top = mac in top_verified or mac == last_working
            xbmc.log(f"[CBTV-HB] Tentativo {attempt}/{len(pool)} con MAC: {mac} (Top: {is_top})", xbmc.LOGINFO)

            # 1. Handshake (timeout realistico per connessioni Wi-Fi)
            token = self._handshake(mac, timeout=3.0)
            if not token:
                xbmc.log(f"[CBTV-HB] Handshake fallito per MAC {mac}", xbmc.LOGWARNING)
                if is_top:
                    self.remove_top_verified_mac(mac)
                exclude_macs.add(mac)
                continue

            # 2. create_link
            url_or_token, stream_id_out = self.create_link(mac, token, cmd, timeout=3.5)
            if not url_or_token:
                xbmc.log(f"[CBTV-HB] create_link fallito per MAC {mac}", xbmc.LOGWARNING)
                if is_top:
                    self.remove_top_verified_mac(mac)
                exclude_macs.add(mac)
                continue

            # 3. Costruisci URL finale assicurando il dominio attivo corretto
            if stream_id_out is None and url_or_token.startswith("http"):
                final_url = re.sub(r"http[s]?://[^/]+", self.portal_url, url_or_token)
            else:
                final_url = (f"{self.portal_url}/play/live.php"
                             f"?mac={mac}&stream={stream_id_out}&extension=ts&play_token={url_or_token}")

            # Salva il primo come fallback nel caso in cui tutti falliscano il probe live
            if not first_fallback_url:
                first_fallback_url = f"{final_url}|User-Agent={quote_plus(self.UA)}"
                first_fallback_mac = mac

            # 4. Verifica se lo stream è realmente attivo (evita blocchi/black.ts con gestione ReadTimeout live)
            try:
                v_session = requests.Session()
                v_session.trust_env = False
                with v_session.get(final_url, headers={"User-Agent": self.UA}, timeout=(2.5, 3.5), stream=True, allow_redirects=True) as r_play:
                    if r_play.status_code >= 400:
                        xbmc.log(f"[CBTV-HB] MAC {mac} HTTP error {r_play.status_code}", xbmc.LOGWARNING)
                        if is_top and r_play.status_code in [401, 403, 404]:
                            self.remove_top_verified_mac(mac)
                        exclude_macs.add(mac)
                        continue

                    final_dest = str(r_play.url).lower()
                    content_type = (r_play.headers.get("Content-Type") or "").lower()

                    if "black.ts" in final_dest or "85.18.95.155" in final_dest or "text/html" in content_type:
                        xbmc.log(f"[CBTV-HB] MAC {mac} bloccato o black.ts ({final_dest[:60]})", xbmc.LOGWARNING)
                        if is_top:
                            self.remove_top_verified_mac(mac)
                        exclude_macs.add(mac)
                        continue

                    head = r_play.raw.read(188)
                    if not head:
                        xbmc.log(f"[CBTV-HB] MAC {mac} stream vuoto (0 bytes)", xbmc.LOGWARNING)
                        if is_top:
                            self.remove_top_verified_mac(mac)
                        exclude_macs.add(mac)
                        continue
                    if head.startswith(b'\x1f\x8b\x08'):
                        xbmc.log(f"[CBTV-HB] MAC {mac} non autorizzato (stream GZIP vuoto)", xbmc.LOGWARNING)
                        if is_top:
                            self.remove_top_verified_mac(mac)
                        exclude_macs.add(mac)
                        continue
                    if b"Sito Illegale" in head or b"AGCOM" in head or b"html" in head:
                        xbmc.log(f"[CBTV-HB] MAC {mac} pagina blocco AGCOM o HTML", xbmc.LOGWARNING)
                        if is_top:
                            self.remove_top_verified_mac(mac)
                        exclude_macs.add(mac)
                        continue
            except requests.exceptions.ReadTimeout:
                # Il flusso live TS sta trasmettendo pacchetti continui: successo!
                xbmc.log(f"[CBTV-HB] MAC {mac} stream live verificato (ReadTimeout live)", xbmc.LOGINFO)
            except Exception as e:
                xbmc.log(f"[CBTV-HB] MAC {mac} errore verifica stream: {e}", xbmc.LOGWARNING)
                exclude_macs.add(mac)
                continue

            # 5. Aggiungi User-Agent per Kodi
            final_url_with_ua = f"{final_url}|User-Agent={quote_plus(self.UA)}"
            xbmc.log(f"[CBTV-HB] Stream risolto con successo usando MAC {mac}", xbmc.LOGINFO)
            
            # Salva come Last Working MAC e registra/promuovi nei Top MAC (aggiornamento costante)
            self._set_last_working_mac(mac)
            self.record_top_verified_mac(mac)
            
            return final_url_with_ua, mac

        # Se nessun MAC ha completato il probe live ma un create_link ha avuto successo, usa il fallback
        if first_fallback_url:
            xbmc.log(f"[CBTV-HB] Nessun MAC ha passato il probe live rapido. Uso il primo stream autorizzato: {first_fallback_mac}", xbmc.LOGINFO)
            return first_fallback_url, first_fallback_mac

        return None, None

    # ---- cache ----
    CACHE_VERSION = "3.3.4"  # Incrementare ad ogni cambio nella logica di fetch/filtro canali

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

        # Fallback integrato delle categorie note reali per evitare blocchi
        if self.server_id == "s50":
            fallback_genres = [
                {"id": "2721", "title": "┃IT┃ GENERALE"},
                {"id": "2723", "title": "┃IT┃ FILM E SERIE"},
                {"id": "388", "title": "┃IT┃ SPORT"},
                {"id": "2728", "title": "┃IT┃ SKY SPORT"},
                {"id": "2729", "title": "┃IT┃ SKY CALCIO"},
                {"id": "3331", "title": "┃IT┃ ZONA DAZN"},
                {"id": "2731", "title": "┃IT┃ DAZN SERIE A"},
                {"id": "2730", "title": "┃IT┃ DAZN"},
                {"id": "3333", "title": "┃IT┃ DAZN SERIE B"}
            ]
        else:
            fallback_genres = [
                {"id": "11", "title": "IT| PRIME ᴿᴬᵂ ⁶⁰ᶠᵖˢ"},
                {"id": "12", "title": "IT| PLATINUM TV UHD/4K"},
                {"id": "13", "title": "IT| GENERALE"},
                {"id": "14", "title": "IT| CINEMA"},
                {"id": "15", "title": "IT| SPORT"},
                {"id": "16", "title": "IT| GOLD TV HEVC"}
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
        """Canali Sky Intrattenimento e Cinema (nessun canale sport). Caricamento istantaneo con ricarica opzionale."""
        if not force_refresh:
            cached = self._get_cache("sky_tv")
            if cached and len(cached) > 5:
                return cached
            # Apertura istantanea da file locale pre-integrato (51 canali)
            fallback = self._load_fallback("sky_tv_fallback.json")
            if fallback:
                self._set_cache("sky_tv", fallback)
                return fallback

        target_titles = [
            "IT| GENERALE", "IT| GENERALE HD/4K", "IT| CINEMA", "IT| CINEMA HD/4K", "IT| CINEMA VIP HD/4K",
            "IT| REGIONALI", "IT| REGIONALI HD/4K", "IT| PRIME ᴿᴬᵂ ⁶⁰ᶠᵖˢ", "IT| 24/7 MOVIES & SERIES",
            "IT| 24/7 MOVIES & SERIES HD/4K", "IT| ITALY FHD/HEVC", "IT| ITALY UHD/4K", "IT| PLATINUM TV UHD/4K",
            "IT| GOLD TV HEVC", "IT| AMAZON PRIME",
            "┃IT┃ ITALIA HD | RIGIOCARE ⏺", "┃IT┃ GENERALE", "┃IT┃ INTRATTENIMENTO",
            "┃IT┃ FILM E SERIE", "┃IT┃ CINEMA", "┃IT┃ 24/7 MOVIES & SERIES", "┃IT┃ DOCUMENTARIO"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        channels = self._fetch_channels_for_genres(gids, "sky_tv",
            keywords=["SKY"],
            negatives=["SPORT", "DAZN", "CALCIO", "F1", "MOTOGP", "PRIMAFILA"],
            force=force_refresh)
            
        if self.server_id == "s28" and not channels:
            xbmc.log("[CBTV-HB] get_sky_tv_channels su s28 fallito/vuoto, provo s50 fallback", xbmc.LOGWARNING)
            client_s50 = HubliveStalkerClient("s50")
            channels = client_s50.get_sky_tv_channels(force_refresh=force_refresh)

        if not channels:
            channels = self._load_fallback("sky_tv_fallback.json")
            if channels:
                self._set_cache("sky_tv", channels)
            
        return channels

    def get_sky_sport_channels(self, force_refresh=False):
        """Canali Sky Sport (83 canali sportivi). Caricamento istantaneo con ricarica opzionale."""
        if not force_refresh:
            cached = self._get_cache("sky_sport")
            if cached and len(cached) > 10:
                return cached
            # Apertura istantanea da file locale pre-integrato (83 canali)
            channels = self._load_fallback("sky_sport_fallback.json")
            if channels:
                self._set_cache("sky_sport", channels)
                return channels

        target_titles = [
            "IT| SPORT", "IT| SPORT HD/4K", "IT| FORMULA 1 / MOTOGP", "IT| SERIE A/B/C",
            "IT| ITALY FHD/HEVC", "IT| ITALY UHD/4K", "IT| PLATINUM TV UHD/4K", "IT| GOLD TV HEVC", "IT| LNP PASS PPV",
            "┃IT┃ SPORT", "┃IT┃ SKY SPORT", "┃IT┃ SKY CALCIO", "┃IT┃ DAZN SERIE A", "┃IT┃ ZONA DAZN",
            "┃IT┃ DAZN SERIE B", "┃IT┃ SERIE A | B | C", "┃IT┃ BASKET", "┃IT┃ AMAZON PRIME SPORT", "┃IT┃ MY SPORTS"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        channels = self._fetch_channels_for_genres(gids, "sky_sport", 
            keywords=["SKY SPORT", "SKY CALCIO", "EUROSPORT"],
            negatives=["SERIE C", "SERIE D", "LEGA PRO", "DAZN BAR", "DAZN CHANNEL", "VETRINA DAZN"],
            force=force_refresh)
            
        if self.server_id == "s28" and not channels:
            xbmc.log("[CBTV-HB] get_sky_sport_channels su s28 vuoto, provo s50 fallback", xbmc.LOGWARNING)
            client_s50 = HubliveStalkerClient("s50")
            channels = client_s50.get_sky_sport_channels(force_refresh=force_refresh)

        if not channels:
            channels = self._load_fallback("sky_sport_fallback.json")

        def sky_sport_sort_key(ch):
            name = ch.get('name', '').upper().strip()
            if "SKY SPORT" in name:
                group = 0
                if "SKY SPORT 24" in name:
                    subgroup = 0
                elif "SKY SPORT UNO" in name:
                    subgroup = 1
                else:
                    subgroup = 2
            elif "SKY CALCIO" in name:
                group = 1
                subgroup = 0
            elif "EUROSPORT" in name:
                group = 2
                subgroup = 0
            else:
                group = 3
                subgroup = 0
            import re
            parts = [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', name)]
            return (group, subgroup, parts)

        channels.sort(key=sky_sport_sort_key)
        self._set_cache("sky_sport", channels)
        return channels

    def get_dazn_channels(self, force_refresh=False):
        """Canali DAZN completi (56 canali con Zona DAZN 1-4 in testa). Caricamento istantaneo con ricarica opzionale."""
        if not force_refresh:
            cached = self._get_cache("dazn")
            if cached and any("ZONA DAZN" in ch.get('name', '').upper() for ch in cached):
                return cached
            # Apertura istantanea da file locale pre-integrato (56 canali)
            fallback = self._load_fallback("dazn_fallback.json")
            if fallback:
                import re
                def dazn_sort_key(ch):
                    name = ch.get('name', '').upper()
                    if "ZONA DAZN" in name:
                        group = 1
                    elif "DAZN" in name and "EVENT" not in name and "SERIE" not in name:
                        group = 2
                    elif "SERIE A" in name:
                        group = 3
                    elif "SERIE B" in name:
                        group = 4
                    elif "EVENT" in name:
                        group = 5
                    else:
                        group = 6
                    num_match = re.search(r'\d+', name)
                    num = int(num_match.group()) if num_match else 1
                    res_val = 4
                    if "HEVC" in name or "4K" in name:
                        res_val = 1
                    elif "FHD" in name:
                        res_val = 2
                    elif "HD" in name:
                        res_val = 3
                    return (group, num, res_val, name)

                fallback.sort(key=dazn_sort_key)
                self._set_cache("dazn", fallback)
                return fallback

        target_titles = [
            "IT| SERIE A/B/C", "IT| DAZN VIP HD/4K", "IT| DAZN PPV", "IT| DAZN",
            "┃IT┃ ZONA DAZN", "┃IT┃ DAZN", "┃IT┃ DAZN SERIE A", "┃IT┃ DAZN SERIE B"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids and self.server_id == "s50":
            # ID reali certificati per Server 50
            gids = ["3331", "2730", "2731", "3333"]

        channels = self._fetch_channels_for_genres(gids, "dazn",
            keywords=None,
            negatives=["WOMEN", "SKY SPORT", "SKY CALCIO", "EUROSPORT", "PALLAVOLO", "PALLAMANO", "PALLANUOTO"],
            force=force_refresh)
            
        if self.server_id == "s28" and (not channels or not any("ZONA DAZN" in ch.get('name', '').upper() for ch in channels)):
            xbmc.log("[CBTV-HB] get_dazn_channels su s28 vuoto o senza Zona DAZN, carico s50", xbmc.LOGINFO)
            client_s50 = HubliveStalkerClient("s50")
            channels = client_s50.get_dazn_channels(force_refresh=force_refresh)

        # Se il fetch remoto è incompleto (manca Zona DAZN) o fallito (502 Bad Gateway), usa il fallback integrato completo
        if not channels or not any("ZONA DAZN" in ch.get('name', '').upper() for ch in channels):
            xbmc.log("[CBTV-HB] Fetch remoto DAZN incompleto, carico dazn_fallback.json integrato (56 canali)", xbmc.LOGINFO)
            channels = self._load_fallback("dazn_fallback.json")

        if channels:
            import re
            def dazn_sort_key(ch):
                name = ch.get('name', '').upper()
                # Gruppo 1: Zona DAZN (canali lineari principali)
                if "ZONA DAZN" in name:
                    group = 1
                # Gruppo 2: DAZN standard (DAZN 1, DAZN 2, ecc. senza la parola EVENT o SERIE)
                elif "DAZN" in name and "EVENT" not in name and "SERIE" not in name:
                    group = 2
                # Gruppo 3: DAZN Serie A (canali dedicati)
                elif "SERIE A" in name:
                    group = 3
                # Gruppo 4: DAZN Serie B (calcio Serie B)
                elif "SERIE B" in name:
                    group = 4
                # Gruppo 5: DAZN Event (i canali web/evento)
                elif "EVENT" in name:
                    group = 5
                else:
                    group = 6
                
                # Numero del canale (se non specificato, è il canale 1)
                num_match = re.search(r'\d+', name)
                num = int(num_match.group()) if num_match else 1
                
                # Qualità della sorgente (preferisci HEVC/4K -> FHD -> HD -> SD)
                res_val = 4
                if "HEVC" in name or "4K" in name:
                    res_val = 1
                elif "FHD" in name:
                    res_val = 2
                elif "HD" in name:
                    res_val = 3
                return (group, num, res_val, name)
                
            channels.sort(key=dazn_sort_key)
            self._set_cache("dazn", channels)
            
        return channels

    def get_primafila_channels(self):
        target_titles = [
            "IT| CINEMA", "IT| CINEMA VIP HD/4K", "IT| CINEMA HD/4K", "IT| SPORT", "IT| SPORT HD/4K",
            "IT| ITALY FHD/HEVC", "IT| PLATINUM TV UHD/4K", "IT| ITALY UHD/4K",
            "┃IT┃ OD SKY PRIMAFILA ESCLUSIVO", "┃IT┃ OD SKY PRIMAFILA", "┃IT┃ OD PRIMAFILA", "┃IT┃ OD PRIMA", "┃IT┃ OD MESCOLA"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        channels = self._fetch_channels_for_genres(gids, "primafila", keywords=["PRIMAFILA"])
        
        if self.server_id == "s28" and not channels:
            xbmc.log("[CBTV-HB] get_primafila_channels su s28 vuoto, provo s50 fallback", xbmc.LOGWARNING)
            client_s50 = HubliveStalkerClient("s50")
            channels = client_s50.get_primafila_channels()
        
        def primafila_sort_key(ch):
            name = ch.get('name', '').upper().strip()
            norm = name.replace(" ", "")
            is_vetrina = 0 if "VETRINA" in norm else 1
            if "PRIMAFILA" in norm:
                group = 0
            elif "CINEPLAY" in norm:
                group = 1
            else:
                group = 2
            num_match = re.search(r'\d+', norm)
            num = int(num_match.group()) if num_match else 999999
            return (is_vetrina, group, num, name)
            
        channels.sort(key=primafila_sort_key)
        return channels

    def get_foreign_sport_channels(self, group):
        target_titles = []
        filter_keywords = []
        
        if group == "COSMOTE / GR SPORT":
            target_titles = ["GR| ΑΘΛΗΤΙΚΆ/SPORTS", "GR| ΑΘΛΗΤΙΚΑ/SPORTS", "GR| ΑΘΛΗΤΙΚΑ/SPORTS VIP", "┃GR┃ COSMOTE SPORTS", "┃GR┃ SPORTS | ΑΘΛΗΤΙΚΑ"]
            filter_keywords = ["COSMOTE"]
        elif group == "MAX SPORT / BG SPORT":
            target_titles = ["BG| BULGARIA", "BG| BULGARIA ⱽᴵᴾ ᴿᴬᵂ", "BG| BULGARIA ᴴᴰ/ᴿᴬᵂ", "┃BG┃ BULGARIA", "┃BG┃ BULGARIA ⱽᴵᴾ ᴿᴬᵂ"]
            filter_keywords = ["DIEMA", "MAX SPORT"]
        elif group == "POLSAT / PL SPORT":
            target_titles = ["PL| SPORTOWE", "PL| CANAL+ ONLINE SPORT ᴿᴬᵂ", "PL| SPORTOWE ᴴᴰ/ᴿᴬᵂ", "PL| CANAL+ ONLINE SPORT ᴿᴬᵂ", "┃PL┃ CANAL+ SPORT", "┃PL┃ POLSAT SPORT", "┃PL┃ ELEVEN SPORTS"]
            filter_keywords = ["POLSAT", "ELEVEN", "CANAL+"]
        elif group == "TNT / UK SPORT":
            target_titles = [
                "UK| TNT SPORTS EVENT", "UK| TNT SPORT EVENT", "UK| TNT SPORT ᴴᴰ ⱽᴵᴾ", "UK| TNT SPORT ᴿᴬᵂ ⱽᴵᴾ ᴰᴼᴸᴮʸ ᴬᵁᴰᴵᴼ",
                "UK| SPORTS", "UK| SPORTS HEVC", "UK| SKY SPORT+ VIP",
                "┃UK┃ TNT SPORTS EVENT", "┃UK┃ TNT SPORTS RAW DOLBY", "┃UK┃ TNT SPORTS HEVC", "┃UK┃ TNT SPORTS FHD", "┃UK┃ TNT SPORTS HD"
            ]
            filter_keywords = ["TNT"]
        elif group == "ZIGGO / NL SPORT":
            target_titles = ["NL| SPORT", "NL| SPORT HD/4K", "NL| ZIGGO SPORTS ᴿᴬᵂ", "NL| ZIGGO ᴿᴬᵂ", "NL| VIAPLAY SPORT", "┃NL┃ SPORT TV+", "┃NL┃ ZIGGO ᴿᴬᵂ", "┃NL┃ ZIGGO SPORTS ᴿᴬᵂ"]
            filter_keywords = ["ZIGGO"]
        elif group == "S SPORT / TR SPORT":
            target_titles = [
                "TR| SPOR KANALI GOLD", "TR| SPOR KANALI VIP", "TR| SPOR KANALI LOCAL", "TR| SPOR KANALLARI", "TR| TABII SPORT",
                "┃TR┃ BEIN SPORTS HEVC", "┃TR┃ BEIN SPORTS FHD", "┃TR┃ BEIN SPORTS", "┃TR┃ EXXEN SPORTS", "┃TR┃ S SPORTS"
            ]
            filter_keywords = ["S SPORT"]
            
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids and group == "TNT / UK SPORT":
            genres = self.get_genres()
            gids = [g["id"] for g in genres if "TNT" in g.get("title", "").upper()]

        channels = []
        if gids:
            channels = self._load_and_filter_foreign_channels(gids, group, filter_keywords)
            
        if self.server_id == "s28" and not channels:
            xbmc.log(f"[CBTV-HB] {group} su s28 vuoto, provo s50 fallback", xbmc.LOGWARNING)
            client_s50 = HubliveStalkerClient("s50")
            return client_s50.get_foreign_sport_channels(group)
            
        return channels

    def _load_and_filter_foreign_channels(self, gids, group, filter_keywords):
        channels = []
        seen_cmds = set()
        ch_list = self._fetch_channels_for_genres(gids, f"foreign_{group.replace(' ', '_').replace('/', '_')}")
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
            # Fallback: cerca in tutte le cache s50 già caricate
            for fn in cache_files:
                if fn.startswith("hl_s50_") and fn.endswith(".json") and "genres" not in fn:
                    try:
                        with open(os.path.join(self.cache_dir, fn), 'r', encoding='utf-8') as fh:
                            d = json.load(fh)
                            for ch in d.get('data', []):
                                if self._normalize_channel_name(ch.get('name', '')) == norm_target:
                                    return ch.get('cmd')
                    except:
                        pass
            return None
            
        # 2. Cerca nella cache s50 specifica
        s50_fn = f"hl_s50_{category_key}.json"
        if s50_fn in cache_files:
            try:
                with open(os.path.join(self.cache_dir, s50_fn), 'r', encoding='utf-8') as fh:
                    d = json.load(fh)
                    for ch in d.get('data', []):
                        if self._normalize_channel_name(ch.get('name', '')) == norm_target:
                            return ch.get('cmd')
            except:
                pass
                
        # 3. Cache s50 non presente, caricala al volo
        xbmc.log(f"[CBTV-HB] Fallback cache s50 per {category_key} mancante, avvio fetch dinamico...", xbmc.LOGINFO)
        client_s50 = HubliveStalkerClient("s50")
        channels_s50 = []
        
        if category_key == "sky_tv":
            channels_s50 = client_s50.get_sky_tv_channels()
        elif category_key == "sky_sport":
            channels_s50 = client_s50.get_sky_sport_channels()
        elif category_key == "dazn":
            channels_s50 = client_s50.get_dazn_channels()
        elif category_key == "primafila":
            channels_s50 = client_s50.get_primafila_channels()
        elif category_key.startswith("foreign_"):
            group_name = category_key.replace("foreign_", "").replace("_", " ")
            channels_s50 = client_s50.get_foreign_sport_channels(group_name)
            
        for ch in channels_s50:
            if self._normalize_channel_name(ch.get('name', '')) == norm_target:
                return ch.get('cmd')
                
        return None
