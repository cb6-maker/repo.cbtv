# -*- coding: utf-8 -*-
"""
Client per la risoluzione e lo streaming di flussi HLS (Vavoo / MediaHubMX).
Include autenticazione dinamica con firma 'mediahubmx-signature' (tramite ping API)
e configurazione avanzata per 'inputstream.ffmpegdirect' per evitare blocchi HTTP 403 sui segmenti .ts.
"""

import json
import time
import uuid
import urllib.request
import urllib.parse
try:
    import xbmc
    import xbmcgui
    import xbmcplugin
except ImportError:
    xbmc = None
    xbmcgui = None
    xbmcplugin = None

AUTH_PING_URL = "https://www.vavoo.tv/api/app/ping"
RESOLVE_API = "https://vavoo.to/mediahubmx-resolve.json"
USER_AGENT = "electron-fetch/1.0 electron (+https://github.com/arantes555/electron-fetch)"

# Cache in memoria della firma per evitare ping ridondanti
_AUTH_CACHE = {
    "signature": None,
    "expires": 0
}
AUTH_CACHE_TTL = 3600  # 1 ora


def get_auth_signature():
    """
    Ottiene la firma crittografica 'mediahubmx-signature' necessaria per
    autorizzare il download del manifest HLS e dei relativi segmenti .ts video.
    """
    global _AUTH_CACHE
    now = time.time()
    if _AUTH_CACHE["signature"] and now < _AUTH_CACHE["expires"]:
        return _AUTH_CACHE["signature"]

    headers = {
        "accept": "*/*",
        "user-agent": USER_AGENT,
        "Accept-Language": "de",
        "Accept-Encoding": "gzip, deflate",
        "content-type": "application/json; charset=utf-8",
        "Connection": "close"
    }

    payload = {
        "token": "8Us2TfjeOFrzqFFTEjL3E5KfdAWGa5PV3wQe60uK4BmzlkJRMYFu0ufaM_eeDXKS2U04XUuhbDTgGRJrJARUwzDyCcRToXhW5AcDekfFMfwNUjuieeQ1uzeDB9YWyBL2cn5Al3L3gTnF8Vk1t7rPwkBob0swvxA",
        "reason": "player.enter",
        "locale": "de",
        "theme": "dark",
        "metadata": {
            "device": {
                "type": "Desktop",
                "brand": "Unknown",
                "model": "Unknown",
                "name": "Unknown",
                "uniqueId": uuid.uuid4().hex[:16]
            },
            "os": {
                "name": "windows",
                "version": "10.0.22631",
                "abis": [],
                "host": "electron"
            },
            "app": {
                "platform": "electron",
                "version": "3.1.4",
                "buildId": "288045000",
                "engine": "jsc",
                "signatures": [],
                "installer": "unknown"
            },
            "version": {
                "package": "tv.vavoo.app",
                "binary": "3.1.4",
                "js": "3.1.4"
            }
        },
        "appFocusTime": 27229,
        "playerActive": True,
        "playDuration": 0,
        "devMode": False,
        "hasAddon": False,
        "castConnected": False,
        "package": "tv.vavoo.app",
        "version": "3.1.4",
        "process": "app",
        "firstAppStart": int(now * 1000) - 86400000,
        "lastAppStart": int(now * 1000),
        "ipLocation": "",
        "adblockEnabled": False,
        "proxy": {
            "supported": ["ss"],
            "engine": "ss",
            "enabled": False,
            "autoServer": True,
            "id": "ca-bhs"
        },
        "iap": {"supported": True}
    }

    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(AUTH_PING_URL, data=data_bytes, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            sig = data.get("addonSig")
            if sig:
                _AUTH_CACHE["signature"] = sig
                _AUTH_CACHE["expires"] = now + AUTH_CACHE_TTL
                if xbmc:
                    xbmc.log("[CBTV-HLS] Firma 'mediahubmx-signature' generata e memorizzata in cache.", xbmc.LOGINFO)
                return sig
    except Exception as e:
        if xbmc:
            xbmc.log(f"[CBTV-HLS] Errore richiesta firma Vavoo: {e}", xbmc.LOGWARNING)

    return _AUTH_CACHE.get("signature")


def resolve_vavoo_stream(vavoo_url, timeout=6):
    """
    Risolve un URL vavoo.to in un flusso HLS autenticato.
    Restituisce (final_url, stream_headers, error_message)
    """
    signature = get_auth_signature()

    payload = {
        "language": "de",
        "region": "AT",
        "url": vavoo_url,
        "clientVersion": "3.1.4"
    }

    headers = {
        "accept": "*/*",
        "user-agent": USER_AGENT,
        "content-type": "application/json; charset=utf-8"
    }
    if signature:
        headers["mediahubmx-signature"] = signature

    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(RESOLVE_API, data=data_bytes, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res = json.loads(response.read().decode("utf-8"))
            if res and isinstance(res, list) and len(res) > 0:
                raw_url = res[0].get("url")
                if raw_url:
                    # Intestazioni complete di streaming da passare a Kodi / ffmpegdirect
                    stream_headers = {
                        "User-Agent": USER_AGENT,
                        "Accept": "*/*",
                        "Accept-Encoding": "gzip, deflate",
                        "Connection": "close",
                        "Referer": "https://vavoo.to/",
                        "Origin": "https://vavoo.to"
                    }
                    if signature:
                        stream_headers["mediahubmx-signature"] = signature

                    # Verifica rapida disponibilità manifest HLS
                    try:
                        chk_req = urllib.request.Request(raw_url, headers=stream_headers)
                        with urllib.request.urlopen(chk_req, timeout=4) as chk_res:
                            if chk_res.status != 200:
                                return None, None, f"Status stream non valido: {chk_res.status}"
                    except Exception as chk_err:
                        return None, None, f"Stream timeout o non raggiungibile: {chk_err}"

                    # Stringa URL con headers formattati per Kodi
                    encoded_headers = urllib.parse.urlencode(stream_headers)
                    final_url = f"{raw_url}|{encoded_headers}"
                    return final_url, stream_headers, None

            return None, None, "Nessun flusso disponibile nella risposta"
    except Exception as e:
        if xbmc:
            xbmc.log(f"[CBTV-HLS] Errore risoluzione {vavoo_url}: {e}", xbmc.LOGWARNING)
        return None, None, str(e)


def play_hls_channel(sources, title="Canale HLS"):
    """
    Riproduce un canale provando sequenzialmente le sorgenti (fallback trasparente).
    Configura inputstream.ffmpegdirect con gli header autenticati.
    """
    if isinstance(sources, str):
        sources = [sources]

    pDialog = xbmcgui.DialogProgress() if xbmcgui else None
    if pDialog:
        pDialog.create("CBTV", f"Connessione a {title} (HLS)...")

    total = len(sources)
    for idx, src in enumerate(sources):
        pct = int(((idx) / float(total)) * 100)
        if pDialog:
            pDialog.update(pct, f"Tentativo sorgente {idx+1}/{total}...")

        final_url, stream_headers, err = resolve_vavoo_stream(src)
        if final_url:
            if pDialog:
                pDialog.update(100, "Avvio riproduzione...")
                pDialog.close()

            if xbmcgui:
                listitem = xbmcgui.ListItem(label=title)
                listitem.setPath(final_url)
                listitem.setProperty('IsPlayable', 'true')
                listitem.setMimeType('application/vnd.apple.mpegurl')

                # Configurazione inputstream.ffmpegdirect (fondamentale per trasmettere mediahubmx-signature ai chunk .ts)
                listitem.setProperty('inputstream', 'inputstream.ffmpegdirect')
                listitem.setProperty('inputstream.ffmpegdirect.is_realtime_stream', 'true')
                listitem.setProperty('inputstream.ffmpegdirect.stream_mode', 'default')
                listitem.setProperty('inputstream.ffmpegdirect.manifest_type', 'hls')

                if stream_headers:
                    header_str = '&'.join(f'{k}={v}' for k, v in stream_headers.items())
                    listitem.setProperty('inputstream.ffmpegdirect.headers', header_str)

                import sys
                try:
                    handle = int(sys.argv[1])
                    xbmcplugin.setResolvedUrl(handle, True, listitem)
                except Exception:
                    xbmc.Player().play(final_url, listitem)
            return True

        if xbmc:
            xbmc.log(f"[CBTV-HLS] Sorgente {idx+1}/{total} per {title} scartata ({err}), provo successiva...", xbmc.LOGINFO)

    if pDialog:
        pDialog.close()
    if xbmcgui:
        xbmcgui.Dialog().notification("CBTV", f"Tutte le sorgenti per {title} sono temporaneamente offline", xbmcgui.NOTIFICATION_WARNING)
    return False
