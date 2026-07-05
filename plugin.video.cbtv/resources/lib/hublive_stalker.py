"""
HubliveStalkerClient - Client standalone per il Server 2 di Hublive.
Logica copiata fedelmente dall'addon originale plugin.video.hublive (v1.4.5).
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
    # Rimuovi prefissi tipo "IT|" o "IT |"
    text = re.sub(r'^[A-Z]{2}\s*\|\s*', '', text)
    return text.strip()


class HubliveStalkerClient:
    """Client Stalker aggiornato per Server 28 di Hublive (pro.most8knew.com) - Server 12 / Server 9 sono disattivati/bloccati."""

    PORTAL_URL = "http://pro.most8knew.com:80"   # NO trailing /c/
    UA = ("Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
          "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3")

    _MAC_POOL = [
        "00:1A:79:20:65:CB",
        "00:1A:79:23:3D:04", "00:1A:79:36:33:37", "00:1A:79:14:57:6A", "00:1A:79:14:04:DD",
        "00:1A:79:5E:34:36", "00:1A:79:00:14:D5", "00:1A:79:4B:73:63", "00:1A:79:4D:10:EA",
        "00:1A:79:4D:8C:76", "00:1A:79:7B:20:DE", "00:1A:79:6E:E5:9C", "00:1A:79:6A:39:61",
        "00:1A:79:7E:27:6C", "00:1A:79:7E:6F:9E", "00:1A:79:4C:CF:19", "00:1A:79:7F:A3:C4",
        "00:1A:79:84:CF:92", "00:1A:79:81:F3:59", "00:1A:79:80:89:90", "00:1A:79:82:BC:40",
        "00:1A:79:81:62:A4", "00:1A:79:82:D2:6F", "00:1A:79:85:7E:E6", "00:1A:79:82:F8:27",
        "00:1A:79:85:72:2E", "00:1A:79:B0:43:BC", "00:1A:79:B2:23:F8", "00:1A:79:B2:69:01",
        "00:1A:79:B5:B6:31", "00:1A:79:B5:B6:DC", "00:1A:79:B6:CB:B8", "00:1A:79:B6:E1:7F",
        "00:1A:79:B6:E3:F9", "00:1A:79:B6:E6:77", "00:1A:79:D6:71:FF", "00:1A:79:B9:E7:A7"
    ]

    # ---- inizializzazione ----
    def __init__(self):
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        self.cache_dir = os.path.join(profile, "hublive")
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    def _get_last_working_mac(self):
        f = os.path.join(self.cache_dir, "hl_last_mac.json")
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    return json.load(fh).get("mac")
            except:
                pass
        return None

    def _set_last_working_mac(self, mac):
        f = os.path.join(self.cache_dir, "hl_last_mac.json")
        try:
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump({"mac": mac}, fh)
        except:
            pass

    # ---- headers / cookies come Hublive originale ----
    @staticmethod
    def _headers(mac=None):
        h = {
            "User-Agent": HubliveStalkerClient.UA,
            "X-User-Agent": "Model: MAG250; Link: WiFi",
            "Referer": f"{HubliveStalkerClient.PORTAL_URL}/stalker_portal/c/index.html",
        }
        return h

    @staticmethod
    def _cookies(mac, token=None):
        c = {"mac": mac}
        if token:
            c["token"] = token
        return c

    # ---- handshake (copia esatta da Hublive) ----
    @staticmethod
    def _handshake(mac, timeout=5):
        """Esegue l'handshake Stalker e restituisce il token (o None)."""
        session = requests.Session()
        session.cookies.clear()
        url = f"{HubliveStalkerClient.PORTAL_URL}/portal.php"
        params = {"type": "stb", "action": "handshake", "token": "", "JsHttpRequest": "1-xml"}
        try:
            r = session.get(url, params=params,
                            headers=HubliveStalkerClient._headers(),
                            cookies=HubliveStalkerClient._cookies(mac),
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
    @staticmethod
    def _api_call(mac, token, action, extra_params=None, timeout=12):
        """Chiamata a portal.php — restituisce il campo 'js' della risposta."""
        session = requests.Session()
        url = f"{HubliveStalkerClient.PORTAL_URL}/portal.php"
        params = {
            "type": "itv",
            "action": action,
            "JsHttpRequest": "1-xml",
        }
        if extra_params:
            params.update(extra_params)

        headers = HubliveStalkerClient._headers()
        cookies = HubliveStalkerClient._cookies(mac, token)

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

    # ---- create_link (copia da Hublive play_channel_server1) ----
    def create_link(self, mac, token, cmd, timeout=12):
        """Chiama create_link e restituisce (play_token, stream_id) o (None, None)."""
        # Estrai lo stream_id dal cmd ORIGINALE (non dal returned_cmd!)
        # Formato cmd: ffmpeg http://…/play/live.php?mac=…&stream=177655&extension=ts&play_token=…
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

        # Server 12 restituisce GIÀ l'URL completo (es. ffmpeg http://204.52.191.254:80/play/live.php?...)
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
        Restituisce (final_url, mac_usato) o (None, None).
        """
        if exclude_macs is None:
            exclude_macs = set()

        pool = list(self._MAC_POOL)
        random.shuffle(pool)
        
        # Escludi MAC già falliti in tentativi precedenti
        if exclude_macs:
            pool = [m for m in pool if m not in exclude_macs]
        
        # Inserisci il Last Working MAC in cima al pool (priorità assoluta)
        last_working = self._get_last_working_mac()
        if last_working and last_working in pool:
            pool.remove(last_working)
            pool.insert(0, last_working)

        # Limita a massimo 6 MAC casuali per evitare timeout di Kodi durante la scansione
        pool = pool[:6]
        
        if not pool:
            xbmc.log("[CBTV-HB] Tutti i MAC sono stati esauriti", xbmc.LOGWARNING)
            return None, None

        for attempt, mac in enumerate(pool, 1):
            xbmc.log(f"[CBTV-HB] Tentativo {attempt}/{len(pool)} con MAC: {mac}", xbmc.LOGINFO)

            # 1. Handshake (con timeout ridotto a 2.0s per velocizzare)
            token = self._handshake(mac, timeout=2.0)
            if not token:
                xbmc.log(f"[CBTV-HB] Handshake fallito per MAC {mac}", xbmc.LOGWARNING)
                exclude_macs.add(mac)
                continue

            # 2. create_link (con timeout ridotto a 2.5s per velocizzare)
            url_or_token, stream_id_out = self.create_link(mac, token, cmd, timeout=2.5)
            if not url_or_token:
                xbmc.log(f"[CBTV-HB] create_link fallito per MAC {mac}", xbmc.LOGWARNING)
                exclude_macs.add(mac)
                continue

            # 3. Costruisci URL finale
            if stream_id_out is None and url_or_token.startswith("http"):
                # Formato Server 9 (URL già completo)
                final_url = url_or_token
            else:
                # Formato Server 2 (ricostruzione manuale)
                final_url = (f"{self.PORTAL_URL}/play/live.php"
                             f"?mac={mac}&stream={stream_id_out}&extension=ts&play_token={url_or_token}")

            # 4. Verifica se lo stream è realmente attivo (evita i black screen / GZIP vuoti)
            try:
                # Esegui una richiesta di test veloce con timeout corto
                r_play = requests.get(final_url, headers=self._headers(mac), cookies=self._cookies(mac, token), timeout=1.8, stream=True)
                
                # Controllo anti black.ts (video di segnaposto nero del server in caso di occupato/non autorizzato)
                if "black.ts" in r_play.url.lower():
                    xbmc.log(f"[CBTV-HB] MAC {mac} reindirizzato a video nero (black.ts)", xbmc.LOGWARNING)
                    r_play.close()
                    exclude_macs.add(mac)
                    continue

                if r_play.status_code == 200:
                    head = r_play.raw.read(100)
                    r_play.close()
                    if not head:
                        xbmc.log(f"[CBTV-HB] MAC {mac} ha restituito uno stream vuoto (0 bytes)", xbmc.LOGWARNING)
                        exclude_macs.add(mac)
                        continue
                    if head.startswith(b'\x1f\x8b\x08'):
                        xbmc.log(f"[CBTV-HB] MAC {mac} non autorizzato (stream GZIP vuoto)", xbmc.LOGWARNING)
                        exclude_macs.add(mac)
                        continue
                    if b"Sito Illegale" in head or b"AGCOM" in head or b"html" in head:
                        xbmc.log(f"[CBTV-HB] MAC {mac} reindirizzato a pagina di blocco AGCOM o HTML", xbmc.LOGWARNING)
                        exclude_macs.add(mac)
                        continue
                    # Se non è vuoto, GZIP, HTML o black.ts, lo stream è valido!
                else:
                    xbmc.log(f"[CBTV-HB] MAC {mac} ha restituito errore HTTP {r_play.status_code}", xbmc.LOGWARNING)
                    r_play.close()
                    exclude_macs.add(mac)
                    continue
            except Exception as e:
                xbmc.log(f"[CBTV-HB] Eccezione durante il test dello stream con MAC {mac}: {e}", xbmc.LOGWARNING)
                exclude_macs.add(mac)
                continue

            # 5. Aggiungi User-Agent per Kodi (come Hublive Server 2, riga 3775)
            final_url_with_ua = f"{final_url}|User-Agent={quote_plus(self.UA)}"
            xbmc.log(f"[CBTV-HB] Stream risolto con successo usando MAC {mac}", xbmc.LOGINFO)
            
            # Salva come Last Working MAC per gli avvii futuri
            self._set_last_working_mac(mac)
            
            return final_url_with_ua, mac

        return None, None

    # ---- cache ----
    CACHE_VERSION = "3.1.0"  # Incrementare ad ogni cambio nella logica di fetch/filtro canali

    def _get_cache(self, key):
        f = os.path.join(self.cache_dir, f"hl_{key}.json")
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    d = json.load(fh)
                    # Invalida se versione diversa o cache scaduta (12h)
                    if d.get('v') != self.CACHE_VERSION:
                        return None
                    if time.time() - d.get('ts', 0) < 43200:
                        return d.get('data')
            except: pass
        return None

    def _set_cache(self, key, data):
        f = os.path.join(self.cache_dir, f"hl_{key}.json")
        try:
            with open(f, 'w', encoding='utf-8') as fh:
                json.dump({'ts': time.time(), 'v': self.CACHE_VERSION, 'data': data}, fh)
        except: pass

    # ---- get_genres / lookup ----
    def _get_working_token_and_mac(self):
        """Ruota i MAC finché non ne trova uno che esegue l'handshake con successo, prioritizzando il Last Working MAC."""
        pool = list(self._MAC_POOL)
        random.shuffle(pool)
        
        last_working = self._get_last_working_mac()
        if last_working and last_working in pool:
            pool.remove(last_working)
            pool.insert(0, last_working)

        for mac in pool:
            token = self._handshake(mac)
            if token:
                return token, mac
        return None, None

    def get_genres(self):
        """Scarica e memorizza in cache le categorie (genres) del portale."""
        cached = self._get_cache("genres")
        if cached:
            return cached

        token, mac = self._get_working_token_and_mac()
        if not token:
            xbmc.log("[CBTV-HB] Impossibile trovare un MAC funzionante per get_genres", xbmc.LOGWARNING)
            return []

        res = self._api_call(mac, token, "get_genres")
        if isinstance(res, list) and len(res) > 0:
            self._set_cache("genres", res)
            return res
        return []

    def _find_genre_ids_by_titles(self, target_titles):
        """Trova gli ID dei generi in base ai titoli cercati."""
        genres = self.get_genres()
        return [g["id"] for g in genres if g.get("title") in target_titles]

    # ---- scaricamento lista canali per genere ----
    def _fetch_channels_for_genres(self, genre_ids, cache_key, keywords=None, negatives=None):
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        token, mac = self._get_working_token_and_mac()
        if not token:
            xbmc.log("[CBTV-HB] Impossibile trovare un MAC funzionante per listing canali", xbmc.LOGWARNING)
            return []

        found = []

        def fetch_genre(gid):
            genre_found = []
            for page in range(1, 35):
                res = self._api_call(mac, token, "get_ordered_list",
                                     {"genre": str(gid), "force_ch_link_check": "0", "p": str(page)})

                if isinstance(res, dict) and 'data' in res:
                    ch_list = res['data']
                elif isinstance(res, list):
                    ch_list = res
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
            return genre_found

        try:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            with ThreadPoolExecutor(max_workers=min(len(genre_ids), 8)) as executor:
                futures = {executor.submit(fetch_genre, gid): gid for gid in genre_ids}
                for future in as_completed(futures):
                    try:
                        found.extend(future.result())
                    except Exception as e:
                        xbmc.log(f"[CBTV-HB] Errore scaricamento canali per genere: {e}", xbmc.LOGWARNING)
        except ImportError:
            xbmc.log("[CBTV-HB] concurrent.futures non disponibile, scaricamento sequenziale", xbmc.LOGWARNING)
            for gid in genre_ids:
                found.extend(fetch_genre(gid))

        # Deduplica e ordina
        unique = list({v['cmd']: v for v in found}.values())
        
        import re
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
            
        unique.sort(key=lambda x: natural_sort_key(x['name']))

        if unique:
            self._set_cache(cache_key, unique)
        return unique

    # ---- API pubblica (Server 12) ----
    # ---- API pubblica dinamica ----
    def get_sky_tv_channels(self):
        target_titles = [
            "IT| GENERALE", "IT| GENERALE HD/4K", 
            "IT| CINEMA", "IT| CINEMA HD/4K", "IT| CINEMA VIP HD/4K",
            "IT| REGIONALI", "IT| REGIONALI HD/4K",
            "IT| PRIME ᴿᴬᵂ ⁶⁰ᶠᵖˢ", 
            "IT| 24/7 MOVIES & SERIES", "IT| 24/7 MOVIES & SERIES HD/4K",
            "IT| ITALY FHD/HEVC", "IT| ITALY UHD/4K",
            "IT| PLATINUM TV UHD/4K", "IT| GOLD TV HEVC"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        return self._fetch_channels_for_genres(gids, "sky_tv",
            keywords=["SKY"],
            negatives=["SPORT", "DAZN", "CALCIO", "F1", "MOTOGP", "PRIMAFILA"])

    def get_sky_sport_channels(self):
        target_titles = [
            "IT| SPORT", "IT| SPORT HD/4K",
            "IT| FORMULA 1 / MOTOGP", "IT| SERIE A/B/C",
            "IT| ITALY FHD/HEVC", "IT| ITALY UHD/4K",
            "IT| PLATINUM TV UHD/4K", "IT| GOLD TV HEVC"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        channels = self._fetch_channels_for_genres(gids, "sky_sport", 
            keywords=["SKY SPORT", "SKY CALCIO", "EUROSPORT"],
            negatives=["SERIE C", "SERIE D", "LEGA PRO", "DAZN BAR", "DAZN CHANNEL", "VETRINA DAZN"])

        def sky_sport_sort_key(ch):
            name = ch.get('name', '').upper().strip()
            # Gruppi di priorità:
            # 0: Sky Sport (es. Sky Sport Uno, Sky Sport Calcio, ecc.)
            # 1: Sky Calcio (es. Sky Calcio 1, Sky Calcio 2, ecc.)
            # 2: Eurosport / Sky Eurosport
            # 3: Altro
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
        return channels

    def get_dazn_channels(self):
        target_titles = [
            "IT| DAZN", "IT| DAZN VIP HD/4K", "IT| DAZN PPV",
            "IT| SPORT", "IT| SPORT HD/4K",
            "IT| ITALY FHD/HEVC", "IT| PLATINUM TV UHD/4K"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        return self._fetch_channels_for_genres(gids, "dazn",
            keywords=["SERIE A", "ZONA DAZN", "DAZN WEB", "DAZN BAR", "DAZN CHANNEL", "VETRINA DAZN"],
            negatives=["WOMEN", "SERIE B", "SKY SPORT", "SKY CALCIO", "EUROSPORT"])

    def get_primafila_channels(self):
        target_titles = [
            "IT| CINEMA", "IT| CINEMA VIP HD/4K", "IT| CINEMA HD/4K",
            "IT| SPORT", "IT| SPORT HD/4K",
            "IT| ITALY FHD/HEVC", "IT| PLATINUM TV UHD/4K"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        channels = self._fetch_channels_for_genres(gids, "primafila", keywords=["PRIMAFILA"])
        
        def primafila_sort_key(ch):
            name = ch.get('name', '').upper().strip()
            # Normalizza rimuovendo spazi per trovare "PRIMA FILA" come "PRIMAFILA"
            norm = name.replace(" ", "")
            # Metti VETRINA per prima
            is_vetrina = 0 if "VETRINA" in norm else 1
            # Raggruppa per tipo: prima PRIMAFILA, poi CINEPLAY, poi altro
            if "PRIMAFILA" in norm:
                group = 0
            elif "CINEPLAY" in norm:
                group = 1
            else:
                group = 2
            # Estrai il numero per l'ordinamento numerico
            num_match = re.search(r'\d+', norm)
            num = int(num_match.group()) if num_match else 999999
            return (is_vetrina, group, num, name)
            
        channels.sort(key=primafila_sort_key)
        return channels

    def get_foreign_sport_channels(self, group):
        """Ritorna la lista dei canali sportivi esteri in base al gruppo (COSMOTE, ZIGGO, POLSAT, TNT, MAX SPORT)"""
        target_titles = []
        filter_keywords = []
        
        if group == "COSMOTE / GR SPORT":
            target_titles = ["GR| ΑΘΛΗΤΙΚΆ/SPORTS", "GR| ΑΘΛΗΤΙΚΑ/SPORTS", "GR| ΑΘΛΗΤΙΚΑ/SPORTS VIP"]
            filter_keywords = ["COSMOTE"]
        elif group == "MAX SPORT / BG SPORT":
            target_titles = ["BG| BULGARIA", "BG| BULGARIA ⱽᴵᴾ ᴿᴬᵂ", "BG| BULGARIA ᴴᴰ/ᴿᴬᵂ"]
            filter_keywords = ["DIEMA", "MAX SPORT"]
        elif group == "POLSAT / PL SPORT":
            target_titles = ["PL| SPORTOWE", "PL| CANAL+ ONLINE SPORT ᴿᴬᵂ", "PL| SPORTOWE ᴴᴰ/ᴿᴬᵂ", "PL| CANAL+ ONLINE SPORT ᴿᴬᵂ"]
            filter_keywords = ["POLSAT", "ELEVEN", "CANAL+"]
        elif group == "TNT / UK SPORT":
            target_titles = ["UK| TNT SPORTS EVENT", "UK| TNT SPORT EVENT", "UK| TNT SPORT ᴴᴰ ⱽᴵᴾ", "UK| TNT SPORT ᴿᴬᵂ ⱽᴵᴾ ᴰᴼᴸᴮʸ ᴬᵁᴰᴵᴼ"]
            filter_keywords = ["TNT"]
        elif group == "ZIGGO / NL SPORT":
            target_titles = ["NL| SPORT", "NL| SPORT HD/4K", "NL| ZIGGO SPORTS ᴿᴬᵂ", "NL| ZIGGO ᴿᴬᵂ"]
            filter_keywords = ["ZIGGO"]
        elif group == "S SPORT / TR SPORT":
            target_titles = ["TR| SPOR KANALI GOLD", "TR| SPOR KANALI VIP", "TR| SPOR KANALI LOCAL"]
            filter_keywords = ["S SPORT"]
            
        # Trova gli ID delle categorie
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids and group == "TNT / UK SPORT":
            # Fallback se non trovato per titolo esatto
            genres = self.get_genres()
            gids = [g["id"] for g in genres if "TNT" in g.get("title", "").upper()]

        if not gids:
            xbmc.log(f"[CBTV-HB] Nessuna categoria trovata per il gruppo estero: {group}", xbmc.LOGWARNING)
            return []
            
        # Scarica i canali dalle categorie mappate
        channels = []
        seen_cmds = set()
        
        ch_list = self._fetch_channels_for_genres(gids, f"foreign_{group.replace(' ', '_').replace('/', '_')}")
        for ch in ch_list:
            name = ch.get("name", "")
            cmd = ch.get("cmd", "")
            if not cmd:
                continue
            
            # Filtra per le parole chiave corrispondenti
            if not filter_keywords or any(kw in name.upper() for kw in filter_keywords):
                if cmd not in seen_cmds:
                    seen_cmds.add(cmd)
                    channels.append({
                        "name": clean_text(name),
                        "cmd": cmd
                    })
                    
        # Ordina naturalmente per nome
        import re
        def natural_sort_key(s):
            return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]
            
        channels.sort(key=lambda x: natural_sort_key(x["name"]))
        return channels
