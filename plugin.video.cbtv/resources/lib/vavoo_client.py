# -*- coding: utf-8 -*-
"""
Client per la risoluzione e lo streaming di flussi HLS (Vavoo / MediaHubMX).
Fornisce link .m3u8 diretti non soggetti a blocchi AGCOM/Piracy Shield in Italia,
senza necessità di proxy per i dati video.
"""

import json
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

RESOLVE_API = "https://vavoo.to/mediahubmx-resolve.json"
USER_AGENT = "MediaHubMX/2"

def resolve_vavoo_stream(vavoo_url, timeout=5):
    """
    Risolve un URL vavoo.to (es: https://vavoo.to/vavoo-iptv/play/...)
    in un URL .m3u8 riproducibile direttamente con le dovute intestazioni.
    Verifica anche la disponibilità effettiva dello stream (HTTP 200).
    Restituisce (final_url, error_message)
    """
    payload = {
        "language": "de",
        "region": "AT",
        "url": vavoo_url,
        "clientVersion": "3.0.2"
    }
    
    headers = {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json"
    }
    
    try:
        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(RESOLVE_API, data=data_bytes, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            res = json.loads(response.read().decode("utf-8"))
            if res and isinstance(res, list) and len(res) > 0:
                raw_url = res[0].get("url")
                if raw_url:
                    # Verifica rapida se lo stream risponde davvero con HTTP 200 prima di passarlo a Kodi
                    try:
                        chk_req = urllib.request.Request(raw_url, headers={
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                            "Referer": "https://vavoo.to/"
                        })
                        with urllib.request.urlopen(chk_req, timeout=3) as chk_res:
                            if chk_res.status != 200:
                                return None, f"Stream ha risposto con codice {chk_res.status}"
                    except Exception as chk_err:
                        return None, f"Stream offline o timeout: {chk_err}"

                    # Intestazioni richieste da Kodi per la corretta riproduzione HLS
                    kodi_headers = "|User-Agent=Mozilla%2F5.0%20(Macintosh%3B%20Intel%20Mac%20OS%20X%2010_15_7)&Referer=https%3A%2F%2Fvavoo.to%2F"
                    final_url = raw_url + kodi_headers
                    return final_url, None
            return None, "Nessun flusso disponibile nella risposta"
    except Exception as e:
        if xbmc:
            xbmc.log(f"[CBTV-HLS] Errore risoluzione {vavoo_url}: {e}", xbmc.LOGWARNING)
        return None, str(e)


def play_hls_channel(sources, title="Canale HLS"):
    """
    Riproduce un canale provando sequenzialmente le sorgenti (fallback automatico trasparente).
    sources: lista di stringhe di URL Vavoo, es: ["https://vavoo.to/...", "https://vavoo.to/..."]
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
        
        final_url, err = resolve_vavoo_stream(src)
        if final_url:
            if pDialog:
                pDialog.update(100, "Avvio riproduzione...")
                pDialog.close()
            
            if xbmcgui:
                listitem = xbmcgui.ListItem(label=title)
                listitem.setPath(final_url)
                listitem.setProperty('IsPlayable', 'true')
                listitem.setMimeType('application/vnd.apple.mpegurl')
                
                import sys
                import xbmcplugin
                try:
                    handle = int(sys.argv[1])
                    xbmcplugin.setResolvedUrl(handle, True, listitem)
                except Exception:
                    xbmc.Player().play(final_url, listitem)
            return True
            
        if xbmc:
            xbmc.log(f"[CBTV-HLS] Sorgente {idx+1}/{total} per {title} non valida ({err}), provo successiva...", xbmc.LOGINFO)
        
    if pDialog:
        pDialog.close()
    if xbmcgui:
        xbmcgui.Dialog().notification("CBTV", f"Tutte le sorgenti per {title} sono offline", xbmcgui.NOTIFICATION_WARNING)
    return False
