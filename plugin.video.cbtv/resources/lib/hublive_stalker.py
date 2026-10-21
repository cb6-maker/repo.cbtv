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

    # MAC noti per essere saturi, trial (stacco a 30s) o con errori di connessione da escludere a priori
    BLACKLISTED_MACS = {
        "00:1A:79:00:3C:13", "00:1A:79:01:6A:89", "00:1A:79:01:6E:81", "00:1A:79:01:6E:D2",
        "00:1A:79:01:70:B5", "00:1A:79:07:BA:DF", "00:1A:79:07:BE:10", "00:1A:79:07:C0:F0",
        "00:1A:79:07:C0:F4", "00:1A:79:07:C1:00", "00:1A:79:07:C2:93", "00:1A:79:07:C3:38",
        "00:1A:79:07:C3:57", "00:1A:79:07:C3:69", "00:1A:79:07:C5:88", "00:1A:79:07:C5:B0",
        "00:1A:79:07:C6:4F", "00:1A:79:07:C7:5B", "00:1A:79:07:C7:A1", "00:1A:79:07:C8:98",
        "00:1A:79:08:4A:E6", "00:1A:79:08:4D:7E", "00:1A:79:08:50:D1", "00:1A:79:08:54:1D",
        "00:1A:79:08:E2:3E", "00:1A:79:08:E8:AA", "00:1A:79:08:E9:E0", "00:1A:79:08:EA:C8",
        "00:1A:79:08:EF:A5", "00:1A:79:0C:A6:60", "00:1A:79:0C:A8:EB", "00:1A:79:0E:37:CE",
        "00:1A:79:0E:3A:35", "00:1A:79:0F:48:6F", "00:1A:79:10:3D:59", "00:1A:79:10:3F:FD",
        "00:1A:79:10:40:CB", "00:1A:79:10:D4:54", "00:1A:79:10:DE:C7", "00:1A:79:10:DF:E2",
        "00:1A:79:10:E1:47", "00:1A:79:13:51:1A", "00:1A:79:13:53:81", "00:1A:79:13:54:CF",
        "00:1A:79:13:58:D1", "00:1A:79:14:62:20", "00:1A:79:14:6A:21", "00:1A:79:14:E0:78",
        "00:1A:79:14:E5:CD", "00:1A:79:19:22:E6", "00:1A:79:19:26:6C", "00:1A:79:1A:67:AE",
        "00:1A:79:1A:6A:9A", "00:1A:79:1A:6A:BF", "00:1A:79:1A:6A:C5", "00:1A:79:1A:6C:C1",
        "00:1A:79:1A:6D:0C", "00:1A:79:1A:6D:3C", "00:1A:79:1F:1C:CF", "00:1A:79:1F:1C:D0",
        "00:1A:79:1F:1D:1C", "00:1A:79:1F:1D:20", "00:1A:79:1F:1E:84", "00:1A:79:22:AD:EE",
        "00:1A:79:23:01:06", "00:1A:79:23:01:11", "00:1A:79:23:01:66", "00:1A:79:23:01:69",
        "00:1A:79:23:02:EE", "00:1A:79:2D:1A:80", "00:1A:79:2F:55:41", "00:1A:79:34:2F:96",
        "00:1A:79:34:67:AC", "00:1A:79:4D:02:49", "00:1A:79:4D:05:F4", "00:1A:79:50:24:B5",
        "00:1A:79:5A:1F:8E", "00:1A:79:5D:8B:D4", "00:1A:79:5D:AB:EA", "00:1A:79:5E:47:93",
        "00:1A:79:5E:47:AA", "00:1A:79:5E:48:E6", "00:1A:79:6B:BC:60", "00:1A:79:6B:C0:29",
        "00:1A:79:6E:29:0B", "00:1A:79:6E:2B:C7", "00:1A:79:6E:2E:F4", "00:1A:79:6E:2F:94",
        "00:1A:79:6E:2F:AD", "00:1A:79:77:06:7B", "00:1A:79:77:07:04", "00:1A:79:7C:6B:27",
        "00:1A:79:A0:E6:5E", "00:1A:79:A0:E6:A7", "00:1A:79:A0:FD:66", "00:1A:79:A0:FD:9B",
        "00:1A:79:A0:FE:93", "00:1A:79:A1:E8:EC", "00:1A:79:A1:FA:4A", "00:1A:79:A2:8B:54",
        "00:1A:79:A3:B9:C6", "00:1A:79:A7:B1:A1", "00:1A:79:AA:5B:12", "00:1A:79:AB:5D:55",
        "00:1A:79:AB:62:5D", "00:1A:79:AB:63:1C", "00:1A:79:AC:81:13", "00:1A:79:AE:CE:68",
        "00:1A:79:AF:F8:81", "00:1A:79:AF:F8:DF", "00:1A:79:BA:A8:10", "00:1A:79:BA:B6:BF",
        "00:1A:79:BB:F1:74", "00:1A:79:BB:F3:84", "00:1A:79:BF:A2:ED", "00:1A:79:C0:1D:96",
        "00:1A:79:C1:A1:65", "00:1A:79:C1:A1:DE", "00:1A:79:C2:7A:3E", "00:1A:79:C2:94:BE",
        "00:1A:79:C3:C9:95", "00:1A:79:C3:C9:9A", "00:1A:79:C4:06:6D", "00:1A:79:C4:14:E9",
        "00:1A:79:C4:35:1D", "00:1A:79:C8:4B:31", "00:1A:79:C9:BE:85", "00:1A:79:F1:B1:63",
        "00:1B:79:1C:7B:70",
        "A0:BB:3E:00:07:36", "A0:BB:3E:00:0A:53", "A0:BB:3E:00:0C:EC", "A0:BB:3E:00:0A:CF",
        "A0:BB:3E:00:06:87", "A0:BB:3E:00:0C:EE", "A0:BB:3E:00:0A:FD", "A0:BB:3E:00:0B:4D",
        "A0:BB:3E:00:0F:85", "A0:BB:3E:00:0E:13", "A0:BB:3E:00:0D:3A", "A0:BB:3E:00:0E:F5",
        "A0:BB:3E:00:10:97", "A0:BB:3E:00:12:87", "A0:BB:3E:00:11:BD", "A0:BB:3E:00:10:3E",
        "A0:BB:3E:00:10:AB", "A0:BB:3E:00:10:AC", "A0:BB:3E:00:02:2D", "A0:BB:3E:00:10:30",
        "A0:BB:3E:00:0F:44", "A0:BB:3E:00:10:52", "A0:BB:3E:00:10:CB", "A0:BB:3E:00:10:C0",
        "A0:BB:3E:00:11:17", "A0:BB:3E:00:10:C3", "A0:BB:3E:00:10:BC", "A0:BB:3E:00:11:41",
        "A0:BB:3E:00:12:8F", "A0:BB:3E:00:12:B0", "A0:BB:3E:00:12:CF", "A0:BB:3E:00:14:03",
        "A0:BB:3E:00:13:EE", "A0:BB:3E:00:14:D1", "A0:BB:3E:00:14:F9", "A0:BB:3E:00:15:E8",
        "A0:BB:3E:00:15:EC", "A0:BB:3E:00:18:5C", "A0:BB:3E:00:16:17", "A0:BB:3E:00:18:B2",
        "A0:BB:3E:00:05:75", "A0:BB:3E:00:05:EB", "A0:BB:3E:00:08:E3", "A0:BB:3E:00:0A:FA",
        "A0:BB:3E:00:09:BA", "A0:BB:3E:00:0B:FD", "A0:BB:3E:00:0A:2E", "A0:BB:3E:00:0B:D9",
        "A0:BB:3E:00:0C:ED", "A0:BB:3E:00:0E:4D", "A0:BB:3E:00:0E:7C", "A0:BB:3E:00:0F:79",
        "A0:BB:3E:00:0F:BA", "A0:BB:3E:00:11:F3", "A0:BB:3E:00:11:5F", "A0:BB:3E:00:12:C1",
        "A0:BB:3E:00:12:34", "A0:BB:3E:00:13:BF", "A0:BB:3E:00:14:5F", "A0:BB:3E:00:14:EA",
        "A0:BB:3E:00:17:65", "A0:BB:3E:00:15:73", "A0:BB:3E:00:18:60", "A0:BB:3E:00:18:E8",
    }

    # Server 18 (z1mag - Porta 8080 non soggetta a blocchi AGCOM / Piracy Shield)
    # Lista rigorosamente filtrata: solo i 46 MAC verificati con streaming continuo > 35s
    PORTAL_18_URL = "http://z1mag.xyz:8080"
    PORTAL_18_MACS = [
        "00:1A:79:13:57:47", "00:1A:79:13:59:AB", "00:1A:79:14:61:CE", "00:1A:79:14:64:52",
        "00:1A:79:14:64:A1", "00:1A:79:14:64:AD", "00:1A:79:14:66:26", "00:1A:79:14:6D:47",
        "00:1A:79:14:DE:DA", "00:1A:79:14:E0:99", "00:1A:79:14:E4:22", "00:1A:79:14:E7:39",
        "00:1A:79:19:1E:E2", "00:1A:79:19:1F:9C", "00:1A:79:19:20:E5", "00:1A:79:1A:67:A3",
        "00:1A:79:1A:6C:B4", "00:1A:79:1A:6E:48", "00:1A:79:1F:0F:F3", "00:1A:79:1F:12:7F",
        "00:1A:79:1F:19:40", "00:1A:79:1F:19:4E", "00:1A:79:1F:1C:7A", "00:1A:79:21:10:70",
        "00:1A:79:22:AD:79", "00:1A:79:22:AD:EB", "00:1A:79:22:FF:AC", "00:1A:79:22:FF:AE",
        "00:1A:79:23:00:A7", "00:1A:79:23:00:D0", "00:1A:79:23:01:02", "00:1A:79:23:01:22",
        "00:1A:79:6E:2C:B6", "00:1A:79:6F:4F:00", "00:1A:79:77:01:2E", "00:1A:79:77:02:4D",
        "00:1A:79:77:02:5F", "00:1A:79:77:04:6D", "00:1A:79:77:05:98", "00:1A:79:7C:4F:D3",
        "00:1A:79:7C:69:9C", "00:1A:79:7C:6B:BF", "00:1A:79:A0:E3:ED", "00:1A:79:A0:E4:BF",
        "00:1A:79:A0:E8:79", "00:1A:79:A1:9D:ED"
    ]

    # Server 12 (Direct IP 204.52.191.254 - Motore primario WebApp, no blocchi AGCOM / Piracy Shield)
    PORTAL_12_URL = "http://204.52.191.254:80"
    PORTAL_12_MACS = [
        "00:1A:79:23:3D:04", "00:1A:79:49:70:7F", "00:1A:79:4B:73:63", "00:1A:79:4C:CF:19",
        "00:1A:79:4D:10:EA", "00:1A:79:B6:E3:F9", "A0:BB:3E:FF:D1:F6", "A0:BB:3E:01:63:19",
        "A0:BB:3E:02:7D:3D", "00:1A:79:77:D7:0A", "00:1A:79:B5:69:40", "00:1A:79:7C:99:37"
    ]

    # Set di sessione condiviso per escludere all'istante qualsiasi MAC caduto spontaneamente durante la riproduzione
    DROPPED_MACS = set()

    PORTAL_1_URL = PORTAL_18_URL
    PORTAL_1_MACS = PORTAL_18_MACS

    REMOTE_HUB_URL = "https://raw.githubusercontent.com/staycanuca/hub/main/servers.json"

    UA = ("Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 "
          "(KHTML, like Gecko) MAG200 stbapp ver: 2 rev: 250 Safari/533.3")
    STREAM_UA = "VLC/3.0.18 LibVLC/3.0.18"

    # ---- inizializzazione ----
    def __init__(self, server_id="s12"):
        self.server_id = server_id
        if server_id == "s18":
            self.portal_url = self.PORTAL_18_URL
            self.mac_pool = list(self.PORTAL_18_MACS)
        else:
            self.portal_url = self.PORTAL_12_URL
            self.mac_pool = list(self.PORTAL_12_MACS)

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

            if self.server_id == "s12":
                if "204.52.191.254" in portal or "server7" in s.get("id", "").lower() or name in ["Server 12", "Server 7"]:
                    if not target_portal and "204.52" in portal:
                        target_portal = s.get("portal_url") or s.get("portal") or s.get("url")
                    for m in macs:
                        if m and m not in combined_macs:
                            combined_macs.append(m)
            else:
                if "z1mag" in portal or "zeroone" in portal or "zerotv" in portal or name in ["Server 18", "Server 8", "Server 66"]:
                    if not target_portal and "z1mag" in portal:
                        target_portal = s.get("portal_url") or s.get("portal") or s.get("url")
                    for m in macs:
                        if m and m not in combined_macs:
                            combined_macs.append(m)

        base_macs = self.PORTAL_12_MACS if self.server_id == "s12" else self.PORTAL_18_MACS
        if combined_macs:
            for m in base_macs:
                if m not in combined_macs:
                    combined_macs.append(m)
            self.mac_pool = [m for m in combined_macs if m not in self.BLACKLISTED_MACS and m not in self.DROPPED_MACS]
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
        """Restituisce il MAC memorizzato per questo canale, solo se non è caduto o in quarantena."""
        if not channel_name:
            return None
        safe_key = re.sub(r'[^a-zA-Z0-9_]', '_', channel_name).lower()
        f = os.path.join(self.cache_dir, f"hl_ch_mac_{self.server_id}_{safe_key}.json")
        if os.path.exists(f):
            try:
                with open(f, 'r', encoding='utf-8') as fh:
                    data = json.load(fh)
                    mac = data.get("mac")
                    if mac:
                        # Se il MAC è caduto spontaneamente o è stato bandito, scartalo all'istante
                        if mac in self.DROPPED_MACS or mac in self.BLACKLISTED_MACS:
                            xbmc.log(f"[CBTV-HB] Canale '{channel_name}': MAC memorizzato {mac} appartiene ai MAC caduti. Scartato.", xbmc.LOGINFO)
                            self.remove_channel_working_mac(channel_name)
                            return None
                        # Se il MAC è attualmente in quarantena (occupato)
                        busy_macs = self.get_busy_macs()
                        if mac in busy_macs:
                            xbmc.log(f"[CBTV-HB] Canale '{channel_name}': MAC memorizzato {mac} è in quarantena. Scartato.", xbmc.LOGINFO)
                            self.remove_channel_working_mac(channel_name)
                            return None
                        if mac in self.mac_pool:
                            return mac
            except Exception:
                pass
        return None

    def record_channel_working_mac(self, channel_name, mac):
        """Memorizza l'abbinamento canale -> MAC che lo ha avviato con successo."""
        if not channel_name or not mac or mac in self.DROPPED_MACS or mac in self.BLACKLISTED_MACS:
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
        """Rimuove l'abbinamento canale -> MAC."""
        if not channel_name:
            return
        safe_key = re.sub(r'[^a-zA-Z0-9_]', '_', channel_name).lower()
        f = os.path.join(self.cache_dir, f"hl_ch_mac_{self.server_id}_{safe_key}.json")
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    def mark_mac_dropped(self, mac, channel_name=None, duration_sec=45):
        """Scarta un MAC caduto: lo banna dalla sessione, mette in quarantena breve (45s) ed elimina i salvataggi."""
        if not mac:
            return
        self.DROPPED_MACS.add(mac)
        self.record_busy_mac(mac, duration_sec=duration_sec)
        self.remove_top_verified_mac(mac)
        if self._get_last_working_mac() == mac:
            f = os.path.join(self.cache_dir, f"hl_last_mac_{self.server_id}.json")
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass
        if channel_name:
            self.remove_channel_working_mac(channel_name)
        xbmc.log(f"[CBTV-HB] MAC {mac} è caduto spontaneamente su '{channel_name}'. Scartato temporaneamente ({duration_sec}s).", xbmc.LOGWARNING)

    def get_busy_macs(self):
        """Restituisce il set di MAC attualmente in quarantena (occupati negli ultimi secondi)."""
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

    def record_busy_mac(self, mac, duration_sec=45):
        """Mette un MAC in quarantena temporanea (default 45s)."""
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
                    xbmc.log(f"[CBTV-HB] Handshake risposto ma senza token: {str(data)[:100]}", xbmc.LOGWARNING)
            else:
                xbmc.log(f"[CBTV-HB] Handshake HTTP {r.status_code} per MAC {mac}: {r.text[:100]}", xbmc.LOGWARNING)
        except Exception as e:
            xbmc.log(f"[CBTV-HB] Handshake ECCEZIONE per MAC {mac}: {type(e).__name__} - {e}", xbmc.LOGWARNING)

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
            else:
                xbmc.log(f"[CBTV-HB] API '{action}' HTTP {r.status_code} per MAC {mac}: {r.text[:100]}", xbmc.LOGWARNING)
        except Exception as e:
            xbmc.log(f"[CBTV-HB] API '{action}' ECCEZIONE per MAC {mac}: {type(e).__name__} - {e}", xbmc.LOGWARNING)

        return {}

    # ---- create_link ----
    def create_link(self, mac, token, cmd, timeout=12):
        """Chiama create_link e restituisce (play_token, stream_id) o (None, None)."""
        sid_match = re.search(r'stream=(\d+)', cmd)
        if not sid_match:
            # Fallback: prova formato /ch/XXXXX o /media/XXXXX o ID numerico diretto
            m2 = re.search(r'(?:/ch/|/media/)(\d+)', cmd)
            if m2:
                stream_id = m2.group(1)
            elif re.match(r'^\d+$', cmd.strip()):
                stream_id = cmd.strip()
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

    def resolve_stream(self, cmd, exclude_macs=None, channel_name=None, max_tries=3, sids=None):
        """
        Prova i canali candidati in cascata qualitativa (sids) e i MAC disponibili.
        Per ogni sid candidato prova fino a max_tries MAC (default 3).
        Se il flusso risponde con 'black.ts', interrompe subito i tentativi su quel sid
        e passa all'ID successivo della sequenza senza sprecare altri MAC.
        Restituisce (final_url, mac_usato) o (None, None).
        """
        if exclude_macs is None:
            exclude_macs = set()

        # Risolvi la lista ordinata dei cmd/sid da provare
        candidate_cmds = []
        if sids:
            if isinstance(sids, str):
                sids_list = [s.strip() for s in sids.split(",") if s.strip()]
            else:
                sids_list = list(sids)
            for s in sids_list:
                candidate_cmds.append(f"ffmpeg /media/{s}.ts")
        elif cmd:
            candidate_cmds.append(cmd)

        if not candidate_cmds:
            return None, None

        pool = [m for m in self.mac_pool if m not in self.BLACKLISTED_MACS and m not in self.DROPPED_MACS]

        # 0. Quarantena: escludi MAC occupati/bloccati
        busy_macs = self.get_busy_macs()
        if busy_macs:
            available = [m for m in pool if m not in busy_macs]
            if len(available) < 5:
                xbmc.log(f"[CBTV-HB] Pochi MAC liberi ({len(available)}) per {self.server_id}! Reset preventivo quarantena.", xbmc.LOGINFO)
                self.clear_busy_macs()
                self.DROPPED_MACS.clear()
            else:
                xbmc.log(f"[CBTV-HB] Esclusi {len(busy_macs)} MAC in quarantena temporanea (occupati)", xbmc.LOGINFO)
                pool = available
        
        # Escludi MAC già falliti in questa sessione
        if exclude_macs:
            pool = [m for m in pool if m not in exclude_macs]
        
        # Mescola casualmente per ruotare ed esplorare nuovi MAC
        priority_base = self.PORTAL_12_MACS if self.server_id == "s12" else self.PORTAL_18_MACS
        priority_macs = [m for m in priority_base if m in pool]
        random.shuffle(priority_macs)
        other_macs = [m for m in pool if m not in priority_macs]
        random.shuffle(other_macs)
        base_pool = priority_macs + other_macs

        ch_mac = self.get_channel_working_mac(channel_name) if channel_name else None
        if ch_mac and ch_mac in base_pool:
            base_pool.remove(ch_mac)
            base_pool.insert(0, ch_mac)

        if not base_pool:
            xbmc.log(f"[CBTV-HB] Tutti i MAC disponibili sono stati esauriti per {self.server_id}", xbmc.LOGWARNING)
            return None, None

        # Prova ogni cmd candidato in ordine decrescente di qualità
        for sid_idx, target_cmd in enumerate(candidate_cmds, 1):
            sid_match = re.search(r'/media/(\d+)\.ts', target_cmd)
            curr_sid = sid_match.group(1) if sid_match else target_cmd
            xbmc.log(f"[CBTV-HB] Valuto flusso candidato {sid_idx}/{len(candidate_cmds)}: ID {curr_sid}", xbmc.LOGINFO)

            mac_candidates = [m for m in base_pool if m not in exclude_macs]
            if max_tries:
                mac_candidates = mac_candidates[:max_tries]

            blacklisted_stream = False

            for attempt, mac in enumerate(mac_candidates, 1):
                is_top = mac in priority_base
                xbmc.log(f"[CBTV-HB] [ID {curr_sid}] Tentativo {attempt}/{len(mac_candidates)} con MAC: {mac} (Priority: {is_top})", xbmc.LOGINFO)

                # 1. Handshake
                token = self._handshake(mac, timeout=5.0)
                if not token:
                    xbmc.log(f"[CBTV-HB] Handshake fallito per MAC {mac}", xbmc.LOGWARNING)
                    if ch_mac and mac == ch_mac:
                        self.remove_channel_working_mac(channel_name)
                    exclude_macs.add(mac)
                    self.record_busy_mac(mac, duration_sec=120)
                    continue

                # 2. create_link
                url_or_token, stream_id_out = self.create_link(mac, token, target_cmd, timeout=5.0)
                if not url_or_token:
                    xbmc.log(f"[CBTV-HB] create_link fallito per MAC {mac} su ID {curr_sid}", xbmc.LOGWARNING)
                    exclude_macs.add(mac)
                    self.record_busy_mac(mac, duration_sec=120)
                    continue

                # 3. Costruisci URL finale
                if stream_id_out is None and url_or_token.startswith("http"):
                    final_url = re.sub(r"http[s]?://[^/]+", self.portal_url, url_or_token)
                else:
                    final_url = (f"{self.portal_url}/play/live.php"
                                 f"?mac={mac}&stream={stream_id_out}&extension=ts&play_token={url_or_token}")

                # 4. Verifica stream ed estrazione rapida redirect CDN
                v_session = None
                try:
                    v_session = requests.Session()
                    v_session.trust_env = False
                    with v_session.get(final_url, headers={"User-Agent": self.UA}, timeout=(3.0, 5.0), stream=True, allow_redirects=True) as r_play:
                        if r_play.status_code >= 400:
                            xbmc.log(f"[CBTV-HB] MAC {mac} HTTP error {r_play.status_code} su ID {curr_sid}", xbmc.LOGWARNING)
                            exclude_macs.add(mac)
                            self.record_busy_mac(mac, duration_sec=180)
                            self.remove_top_verified_mac(mac)
                            if ch_mac and mac == ch_mac:
                                self.remove_channel_working_mac(channel_name)
                            continue

                        final_dest = str(r_play.url)
                        final_dest_lower = final_dest.lower()
                        content_type = (r_play.headers.get("Content-Type") or "").lower()

                        if "black.ts" in final_dest_lower:
                            xbmc.log(f"[CBTV-HB] ID {curr_sid} reindirizza a black.ts (flusso spento). Salto immediato al prossimo ID!", xbmc.LOGWARNING)
                            blacklisted_stream = True
                            break

                        if "85.18.95.155" in final_dest_lower or "text/html" in content_type:
                            xbmc.log(f"[CBTV-HB] MAC {mac} bloccato AGCOM o HTML ({final_dest[:60]})", xbmc.LOGWARNING)
                            exclude_macs.add(mac)
                            self.record_busy_mac(mac, duration_sec=300)
                            continue

                        head = r_play.raw.read(188)
                        if not head or head.startswith(b'\x1f\x8b\x08') or b"Sito Illegale" in head or b"AGCOM" in head:
                            xbmc.log(f"[CBTV-HB] MAC {mac} non valido o vuoto su ID {curr_sid}", xbmc.LOGWARNING)
                            exclude_macs.add(mac)
                            self.record_busy_mac(mac, duration_sec=120)
                            continue
                except requests.exceptions.ReadTimeout:
                    xbmc.log(f"[CBTV-HB] MAC {mac} ReadTimeout su ID {curr_sid}", xbmc.LOGWARNING)
                    if ch_mac and mac == ch_mac:
                        self.remove_channel_working_mac(channel_name)
                    exclude_macs.add(mac)
                    self.record_busy_mac(mac, duration_sec=120)
                    continue
                except Exception as e:
                    xbmc.log(f"[CBTV-HB] MAC {mac} errore verifica su ID {curr_sid}: {e}", xbmc.LOGWARNING)
                    if ch_mac and mac == ch_mac:
                        self.remove_channel_working_mac(channel_name)
                    exclude_macs.add(mac)
                    self.record_busy_mac(mac, duration_sec=120)
                    continue
                finally:
                    if v_session:
                        try:
                            v_session.close()
                        except Exception:
                            pass

                # 5. Linea verificata e funzionante al 100%!
                final_target = final_dest if (final_dest and "204.52.191.254" in final_url and "204.52" not in final_dest) else final_url
                final_url_with_ua = f"{final_target}|User-Agent={quote_plus(self.STREAM_UA)}"
                xbmc.log(f"[CBTV-HB] Stream risolto con successo usando ID {curr_sid} e MAC {mac} -> {final_target[:80]}", xbmc.LOGINFO)
                
                self.remove_busy_mac(mac)
                self._set_last_working_mac(mac)
                self.record_top_verified_mac(mac)
                if channel_name:
                    self.record_channel_working_mac(channel_name, mac)
                
                return final_url_with_ua, mac

            if blacklisted_stream:
                continue

        # Se tutti i tentativi su tutti gli ID hanno fallito
        return None, None

    # ---- cache ----
    CACHE_VERSION = "3.4.1"  # Incrementare ad ogni cambio nella logica di fetch/filtro canali

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

        if self.server_id == "s12":
            fallback_genres = [
                {"id": "265", "title": "IT| SPORT HD/4K"},
                {"id": "457", "title": "IT| FORMULA 1 / MOTOGP"},
                {"id": "467", "title": "IT| SERIE A/B/C"},
                {"id": "476", "title": "IT| DAZN VIP HD/4K"},
                {"id": "681", "title": "IT| DAZN PPV"},
                {"id": "295", "title": "IT| CINEMA HD/4K"},
                {"id": "417", "title": "IT| PLATINUM TV UHD/4K"},
                {"id": "18", "title": "IT| GOLD TV HEVC"},
                {"id": "419", "title": "IT| GENERALE HD/4K"},
                {"id": "294", "title": "IT| DOCUMENTARIO HD/4K"}
            ]
        elif self.server_id == "s18":
            fallback_genres = [
                {"id": "923", "title": "IT ✨ SPORT"},
                {"id": "1233", "title": "IT ✨ DAZN"},
                {"id": "924", "title": "IT ✨ CINEMA"},
                {"id": "922", "title": "IT ✨ ITALIA"},
                {"id": "925", "title": "IT ✨ CULTURA"},
                {"id": "1332", "title": "IT ✨ HEVC"}
            ]
        else:
            fallback_genres = [
                {"id": "2728", "title": "┃IT┃ SKY SPORT"},
                {"id": "2729", "title": "┃IT┃ SKY CALCIO"},
                {"id": "2730", "title": "┃IT┃ DAZN"},
                {"id": "3331", "title": "┃IT┃ ZONA DAZN"},
                {"id": "2731", "title": "┃IT┃ DAZN SERIE A"},
                {"id": "2723", "title": "┃IT┃ FILM E SERIE"},
                {"id": "2724", "title": "┃IT┃ INTRATTENIMENTO"},
                {"id": "2732", "title": "┃IT┃ DOCUMENTARIO"}
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
            "IT| PLATINUM TV UHD/4K", "IT| GOLD TV HEVC", "IT| GENERALE HD/4K", "IT| DOCUMENTARIO HD/4K",
            "┃IT┃ FILM E SERIE", "┃IT┃ INTRATTENIMENTO", "┃IT┃ DOCUMENTARIO",
            "IT ✨ ITALIA", "IT ✨ CULTURA", "IT ✨ HEVC", "IT| GENERALE"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids:
            gids = ["417", "18", "419", "294"] if self.server_id == "s12" else ["922", "925", "1332"]
        channels = self._fetch_channels_for_genres(gids, "sky_tv",
            keywords=["SKY ATLANTIC", "SKY UNO", "SKY NATURE", "SKY DOCUMENTARIES", "SKY ARTE", "SKY INVESTIGATION", "SKY CRIME", "SKY SERIE"],
            negatives=["SPORT", "DAZN", "CALCIO", "F1", "MOTOGP", "PRIMAFILA", "CINEMA", "SERIE A", "SERIE B", "BASKET", "BAR"],
            force=force_refresh)
            
        if not channels:
            xbmc.log("[CBTV-HB] get_sky_tv_channels vuoto/timeout, carico sky_tv_fallback.json integrato", xbmc.LOGWARNING)
            channels = self._load_fallback("sky_tv_fallback.json")
            if channels:
                self._set_cache("sky_tv", channels)
            
        def tv_sort_key(c):
            n = c.get('name', '').upper()
            if 'SKY ATLANTIC' in n: order = 1
            elif 'SKY UNO' in n: order = 2
            elif 'SKY SERIE' in n: order = 3
            elif 'SKY NATURE' in n: order = 4
            elif 'SKY DOCUMENTARIES' in n or 'SKY DOCS' in n: order = 5
            elif 'SKY ARTE' in n: order = 6
            elif 'SKY INVESTIGATION' in n: order = 7
            elif 'SKY CRIME' in n: order = 8
            else: order = 20
            
            if 'FHD' in n: q = 1
            elif 'HEVC' in n: q = 2
            elif 'HD' in n: q = 3
            elif 'SD' in n: q = 4
            else: q = 5
            return (order, q, n)

        channels.sort(key=tv_sort_key)
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
            "IT| CINEMA HD/4K", "IT| CINEMA VIP HD/4K", "┃IT┃ FILM E SERIE", "IT ✨ CINEMA"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids:
            gids = ["295"] if self.server_id == "s12" else ["924"]
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
            "IT| SPORT HD/4K", "IT| AMAZON PRIME PPV", "IT| FORMULA 1 / MOTOGP", "IT| SERIE A/B/C",
            "┃IT┃ SKY SPORT", "┃IT┃ SKY CALCIO", "┃IT┃ SPORT", "IT ✨ SPORT"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids:
            gids = ["265", "457", "467"] if self.server_id == "s12" else ["923"]
        channels = self._fetch_channels_for_genres(gids, "sky_sport", 
            keywords=["SKY SPORT", "SKY CALCIO", "EUROSPORT", "SUPERTENNIS"],
            negatives=["SERIE C", "SERIE D", "LEGA PRO", "DAZN CHANNEL", "VETRINA DAZN", "WOMEN"],
            force=force_refresh)
            
        if not channels:
            xbmc.log("[CBTV-HB] get_sky_sport_channels vuoto/timeout, carico sky_sport_fallback.json integrato", xbmc.LOGWARNING)
            channels = self._load_fallback("sky_sport_fallback.json")

        def sky_sport_sort_key(ch):
            n = ch.get('name', '').upper().strip()
            q = 2 if ("4K" in n or "UHD" in n) else 1
            if "24" in n: return (1, q, n)
            if "UNO" in n and "BAR" not in n: return (2, q, n)
            if "CALCIO HD" in n or "CALCIO 4K" in n or "CALCIO FHD" in n or "CALCIO HEVC" in n: return (3, q, n)
            if "TENNIS" in n: return (4, q, n)
            if "ARENA" in n: return (5, q, n)
            if "MAX" in n: return (6, q, n)
            if "F1" in n: return (7, q, n)
            if "MOTOGP" in n or "MOTO GP" in n: return (8, q, n)
            if "GOLF" in n: return (9, q, n)
            if "NBA" in n: return (10, q, n)
            if "MIX" in n: return (11, q, n)
            if "LEGEND" in n: return (12, q, n)
            if "BAR UNO" in n: return (13, q, n)
            if "BAR DUE" in n: return (14, q, n)
            if "BAR PRIME" in n or "PRIMEVIDEO" in n: return (15, q, n)
            if "CALCIO 1" in n or "CALCIO 251" in n: return (16, q, n)
            if "CALCIO 2" in n or "CALCIO 252" in n: return (17, q, n)
            if "CALCIO 3" in n or "CALCIO 253" in n: return (18, q, n)
            if "CALCIO 4" in n or "CALCIO 254" in n: return (19, q, n)
            if "CALCIO 5" in n or "CALCIO 255" in n: return (20, q, n)
            if "CALCIO 6" in n or "CALCIO 256" in n: return (21, q, n)
            if "CALCIO 7" in n or "CALCIO 257" in n: return (22, q, n)
            if "EUROSPORT 1" in n: return (23, q, n)
            if "EUROSPORT 2" in n: return (24, q, n)
            return (25, q, n)

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
            "IT| DAZN VIP HD/4K", "IT| SERIE A/B/C", "IT| DAZN PPV",
            "┃IT┃ ZONA DAZN", "┃IT┃ DAZN", "┃IT┃ DAZN SERIE A", "IT ✨ DAZN"
        ]
        gids = self._find_genre_ids_by_titles(target_titles)
        if not gids:
            gids = ["476", "681"] if self.server_id == "s12" else ["1233"]

        channels = self._fetch_channels_for_genres(gids, "dazn",
            keywords=None,
            negatives=["WOMEN", "PALLAVOLO", "PALLAMANO", "PALLANUOTO"],
            force=force_refresh)
            
        if not channels:
            xbmc.log("[CBTV-HB] get_dazn_channels vuoto o incompleto, carico dazn_fallback.json integrato", xbmc.LOGINFO)
            channels = self._load_fallback("dazn_fallback.json")

        if channels:
            import re
            filtered = []
            for ch in channels:
                name = ch.get('name', '').upper()
                if any(k in name for k in ["EVENT", "SERIE B", "WOMEN", "PALLAVOLO", "PALLAMANO", "PALLANUOTO"]):
                    continue
                if "SERIE A" not in name:
                    if any(f"DAZN {i}" in name or f"ZONA DAZN {i}" in name for i in range(5, 30)):
                        continue
                filtered.append(ch)

            def dazn_sort_key(ch):
                name = ch.get('name', '').upper()
                if "DAZN 1" in name or "ZONA DAZN 1" in name or name == "ZONA DAZN":
                    group = 1
                elif "DAZN 2" in name or "ZONA DAZN 2" in name:
                    group = 2
                elif "DAZN 3" in name:
                    group = 3
                elif "DAZN 4" in name:
                    group = 4
                elif "SERIE A" in name:
                    group = 5
                else:
                    group = 6

                num_match = re.search(r'\d+', name)
                num = int(num_match.group()) if num_match else 1
                if group == 5:
                    end_num = re.search(r'(\d+)\s*$', name)
                    if end_num:
                        num = int(end_num.group(1))
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
            if fn.startswith("hl_s12_") and fn.endswith(".json") and "genres" not in fn:
                try:
                    with open(os.path.join(self.cache_dir, fn), 'r', encoding='utf-8') as fh:
                        d = json.load(fh)
                        for ch in d.get('data', []):
                            if self._normalize_channel_name(ch.get('name', '')) == norm_target:
                                category_key = fn.replace("hl_s12_", "").replace(".json", "")
                                break
                except:
                    pass
                if category_key:
                    break
                    
        if not category_key:
            # Fallback: cerca nelle altre cache caricate
            for fn in cache_files:
                if fn.startswith("hl_") and fn.endswith(".json") and "genres" not in fn:
                    try:
                        with open(os.path.join(self.cache_dir, fn), 'r', encoding='utf-8') as fh:
                            d = json.load(fh)
                            for ch in d.get('data', []):
                                if self._normalize_channel_name(ch.get('name', '')) == norm_target:
                                    return ch.get('cmd')
                    except:
                        pass
            return None
            
        # 2. Cerca nella cache specifica se presente
        s12_fn = f"hl_s12_{category_key}.json"
        if s12_fn in cache_files:
            try:
                with open(os.path.join(self.cache_dir, s12_fn), 'r', encoding='utf-8') as fh:
                    d = json.load(fh)
                    for ch in d.get('data', []):
                        if self._normalize_channel_name(ch.get('name', '')) == norm_target:
                            return ch.get('cmd')
            except:
                pass
                
        return None
