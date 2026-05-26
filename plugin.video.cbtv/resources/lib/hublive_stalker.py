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
        "00:1A:79:81:F3:59"
    ]

    # ---- inizializzazione ----
    def __init__(self):
        profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
        self.cache_dir = os.path.join(profile, "hublive")
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir)

    # ---- headers / cookies come Hublive originale ----
    @staticmethod
    def _headers(mac=None):
        parsed = urlparse(HubliveStalkerClient.PORTAL_URL)
        h = {
            "User-Agent": HubliveStalkerClient.UA,
            "X-User-Agent": "Model: MAG250; Link: WiFi",
            "Referer": f"{HubliveStalkerClient.PORTAL_URL}/stalker_portal/c/index.html",
            "Host": parsed.netloc,
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
    def _handshake(mac):
        """Esegue l'handshake Stalker e restituisce il token (o None)."""
        session = requests.Session()
        session.cookies.clear()
        url = f"{HubliveStalkerClient.PORTAL_URL}/portal.php"
        params = {"type": "stb", "action": "handshake", "token": "", "JsHttpRequest": "1-xml"}
        try:
            r = session.get(url, params=params,
                            headers=HubliveStalkerClient._headers(),
                            cookies=HubliveStalkerClient._cookies(mac),
                            timeout=5)
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
    def _api_call(mac, token, action, extra_params=None):
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
            r = session.get(url, params=params, headers=headers, cookies=cookies, timeout=12)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict):
                return data.get("js", {})
            return {}
        except Exception as e:
            xbmc.log(f"[CBTV-HB] API call '{action}' fallita: {e}", xbmc.LOGWARNING)
            return {}

    # ---- create_link (copia da Hublive play_channel_server1) ----
    def create_link(self, mac, token, cmd):
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
        res = self._api_call(mac, token, "create_link", {"cmd": clean_cmd, "forced_storage": "0", "download": "0"})
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

    # ---- risoluzione stream con rotazione MAC (come Hublive) ----
    def resolve_stream(self, cmd, exclude_macs=None):
        """
        Prova i MAC disponibili (escludendo quelli già falliti) per ottenere un URL di stream.
        Restituisce (final_url, mac_usato) o (None, None).
        """
        pool = list(self._MAC_POOL)
        random.shuffle(pool)
        
        # Escludi MAC già falliti in tentativi precedenti
        if exclude_macs:
            pool = [m for m in pool if m not in exclude_macs]
        
        if not pool:
            xbmc.log("[CBTV-HB] Tutti i MAC sono stati esauriti", xbmc.LOGWARNING)
            return None, None

        for attempt, mac in enumerate(pool, 1):
            xbmc.log(f"[CBTV-HB] Tentativo {attempt}/{len(pool)} con MAC: {mac}", xbmc.LOGINFO)

            # 1. Handshake
            token = self._handshake(mac)
            if not token:
                xbmc.log(f"[CBTV-HB] Handshake fallito per MAC {mac}", xbmc.LOGWARNING)
                continue

            # 2. create_link
            url_or_token, stream_id_out = self.create_link(mac, token, cmd)
            if not url_or_token:
                xbmc.log(f"[CBTV-HB] create_link fallito per MAC {mac}", xbmc.LOGWARNING)
                continue

            # 3. Costruisci URL finale
            if stream_id_out is None and url_or_token.startswith("http"):
                # Formato Server 9 (URL già completo)
                final_url = url_or_token
            else:
                # Formato Server 2 (ricostruzione manuale)
                final_url = (f"{self.PORTAL_URL}/play/live.php"
                             f"?mac={mac}&stream={stream_id_out}&extension=ts&play_token={url_or_token}")

            # 4. Aggiungi User-Agent per Kodi (come Hublive Server 2, riga 3775)
            final_url_with_ua = f"{final_url}|User-Agent={quote_plus(self.UA)}"

            # 5. Passa a Kodi senza probe
            xbmc.log(f"[CBTV-HB] Stream risolto con MAC {mac}", xbmc.LOGINFO)
            return final_url_with_ua, mac

        return None, None

    # ---- cache ----
    CACHE_VERSION = "2.9.7"  # Incrementare ad ogni cambio nella logica di fetch/filtro canali

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

    # ---- scaricamento lista canali per genere ----
    def _fetch_channels_for_genres(self, genre_ids, cache_key, keywords=None, negatives=None):
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # Usa un MAC qualsiasi per il listing
        mac = random.choice(self._MAC_POOL)
        token = self._handshake(mac)
        if not token:
            xbmc.log("[CBTV-HB] Handshake fallito per listing canali", xbmc.LOGWARNING)
            return []

        found = []
        for gid in genre_ids:
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

                    found.append({'name': clean_text(name_raw), 'cmd': cmd})

        # Deduplica e ordina
        unique = list({v['cmd']: v for v in found}.values())
        unique.sort(key=lambda x: x['name'])

        if unique:
            self._set_cache(cache_key, unique)
        return unique

    # ---- API pubblica (Server 12) ----
    def get_sky_tv_channels(self):
        # Generi Server 12: 18=Generale, 295=Cinema, 420=Cinema VIP, 417=Platinum TV, 419=Gold TV, 1775=24/7 Movies
        return self._fetch_channels_for_genres([18, 295, 420, 417, 419, 1775], "sky_tv",
            keywords=["SKY"],
            negatives=["SPORT", "DAZN", "CALCIO", "F1", "MOTOGP", "PRIMAFILA"])

    def get_sky_sport_channels(self):
        # Generi Server 12: 265=Sport, 467=Formula 1 / MotoGP
        return self._fetch_channels_for_genres([265, 467], "sky_sport", 
            keywords=["SKY SPORT", "SKY CALCIO", "EUROSPORT"],
            negatives=["SERIE C", "SERIE D", "LEGA PRO", "DAZN BAR", "DAZN CHANNEL", "VETRINA DAZN"])

    def get_dazn_channels(self):
        # Generi Server 12: 476=DAZN VIP, 2242=DAZN PP, 265=Sport
        return self._fetch_channels_for_genres([476, 2242, 265], "dazn",
            keywords=["SERIE A", "ZONA DAZN", "DAZN WEB", "DAZN BAR", "DAZN CHANNEL", "VETRINA DAZN"],
            negatives=["WOMEN", "SERIE B", "SKY SPORT", "SKY CALCIO", "EUROSPORT"])

    def get_primafila_channels(self):
        # Generi Server 12: I canali Primafila sono inclusi all'interno di Cinema VIP (420) e Cinema HD (295)
        channels = self._fetch_channels_for_genres([420, 295], "primafila", keywords=["PRIMAFILA"])
        
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
