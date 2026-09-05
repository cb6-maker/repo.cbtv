import requests
import re
import base64
import time
import urllib3
import xbmc

urllib3.disable_warnings()

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Cache in memoria per link m3u8 già risolti (TTL 180s = 3 minuti)
_RESOLVE_CACHE = {} # {key: (m3u8_url, referer, timestamp)}

# Mappa codici WideIPTV / Bluetier (Sorgente primaria stabile e veloce)
WIDEIPTV_MAP = {
    "869": "SkySport24IT",
    "461": "SkySportUnoIT",
    "870": "SkySportCalcioIT",
    "576": "SkySportTennisIT",
    "577": "SkySportF1IT",
    "575": "SkySportMotoGPIT",
    "462": "SkySportArenaIT",
    "460": "SkySportMaxIT",
    "574": "SkySportGolfIT",
    "877": "ZonaDAZN",
    "445": "DAZN1ES",
    "538": "DAZNLaLiga"
}

def resolve_wideiptv(code):
    """Risolve stream m3u8 diretto da WideIPTV/Bluetier CDN."""
    try:
        url = f"https://wideiptv.top/player/{code}"
        headers = {"User-Agent": UA, "Referer": "https://wideiptv.top/"}
        r = requests.get(url, headers=headers, verify=False, timeout=3.5)
        if r.status_code == 200:
            m = re.search(r'streamUrl:\s*["\']([^"\']+)["\']', r.text)
            if m:
                m3u8_url = m.group(1).replace('\\/', '/')
                r_test = requests.get(m3u8_url, headers=headers, verify=False, timeout=2.5)
                if r_test.status_code == 200 and "#EXTM3U" in r_test.text:
                    xbmc.log(f"[CBTV-HLS] Risolto {code} da WideIPTV -> {m3u8_url[:60]}...", xbmc.LOGINFO)
                    return m3u8_url, "https://wideiptv.top/"
    except Exception as e:
        xbmc.log(f"[CBTV-HLS] Errore WideIPTV per {code}: {e}", xbmc.LOGWARNING)
    return None, None

def resolve_daddylive_m3u8(daddy_id):
    """
    Risolve l'URL dello stream .m3u8 autenticato:
    1. Prima tenta tramite WideIPTV (CDN Bluetier ad alte prestazioni).
    2. In fallback tenta i mirror DaddyLive / Phantemlis / Romponalis.
    Restituisce (m3u8_url, referer) oppure (None, None).
    """
    if not daddy_id:
        return None, None

    daddy_id = str(daddy_id).strip()
    now = time.time()

    # Controlla cache locale
    if daddy_id in _RESOLVE_CACHE:
        cached_url, cached_ref, ts = _RESOLVE_CACHE[daddy_id]
        if now - ts < 180:
            return cached_url, cached_ref

    # 1. Sorgente Primaria: WideIPTV
    wide_code = WIDEIPTV_MAP.get(daddy_id) or (daddy_id if not daddy_id.isdigit() else None)
    if wide_code:
        m3u8_url, referer = resolve_wideiptv(wide_code)
        if m3u8_url:
            _RESOLVE_CACHE[daddy_id] = (m3u8_url, referer, now)
            return m3u8_url, referer

    # 2. Sorgente Secondaria / Fallback: DaddyLive
    headers = {
        "User-Agent": UA,
        "Referer": "https://dlhd.st/"
    }

    # Mirror di DaddyLive (incluso dlive.sx)
    for domain in ["dlive.sx", "dlhd.st", "dlhd.pk", "dlhd.so"]:
        try:
            stream_url = f"https://{domain}/stream/stream-{daddy_id}.php"
            r_page = requests.get(stream_url, headers=headers, verify=False, timeout=3.0, allow_redirects=True)
            if r_page.status_code == 200:
                m_iframe = re.search(r'iframe[^>]*src=["\']([^"\']+)["\']', r_page.text)
                if m_iframe:
                    embed_url = m_iframe.group(1)
                    if embed_url.startswith("//"):
                        embed_url = "https:" + embed_url
                    headers_emb = {"User-Agent": UA, "Referer": r_page.url}
                    r_embed = requests.get(embed_url, headers=headers_emb, verify=False, timeout=3.0, allow_redirects=True)
                    if r_embed.status_code == 200:
                        m_b64 = re.search(r'source:\s*window\.atob\(["\']([^"\']+)["\']\)', r_embed.text)
                        if m_b64:
                            m3u8_url = base64.b64decode(m_b64.group(1)).decode('utf-8')
                            r_test = requests.get(m3u8_url, headers={"User-Agent": UA, "Referer": embed_url}, timeout=2.5)
                            if r_test.status_code == 200 and "#EXTM3U" in r_test.text:
                                xbmc.log(f"[CBTV-HLS] Risolto {daddy_id} da {domain} -> {m3u8_url[:60]}...", xbmc.LOGINFO)
                                _RESOLVE_CACHE[daddy_id] = (m3u8_url, embed_url, now)
                                return m3u8_url, embed_url
        except Exception:
            pass

    # Endpoint diretti Romponalis
    for ep_name in ["daddy2.php", "daddy.php", "daddy3.php", "daddy4.php", "daddy5.php"]:
        try:
            url = f"https://hamis.romponalis.st/premiumtv/{ep_name}?id={daddy_id}"
            r = requests.get(url, headers=headers, verify=False, timeout=2.5)
            if r.status_code == 200:
                m = re.search(r'source:\s*window\.atob\(["\']([^"\']+)["\']\)', r.text)
                if m:
                    b64_str = m.group(1)
                    m3u8_url = base64.b64decode(b64_str).decode('utf-8')
                    r_test = requests.get(m3u8_url, headers={"User-Agent": UA, "Referer": url}, timeout=2.0)
                    if r_test.status_code == 200 and "#EXTM3U" in r_test.text:
                        xbmc.log(f"[CBTV-HLS] Risolto {daddy_id} da {ep_name} -> {m3u8_url[:60]}...", xbmc.LOGINFO)
                        _RESOLVE_CACHE[daddy_id] = (m3u8_url, url, now)
                        return m3u8_url, url
        except Exception:
            pass

    xbmc.log(f"[CBTV-HLS] Impossibile risolvere stream per ID {daddy_id}", xbmc.LOGWARNING)
    return None, None
