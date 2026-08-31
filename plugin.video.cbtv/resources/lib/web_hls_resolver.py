import requests
import re
import base64
import time
import urllib3
import xbmc

urllib3.disable_warnings()

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Cache in memoria per link m3u8 già risolti (TTL 180s = 3 minuti)
_RESOLVE_CACHE = {} # {daddy_id: (m3u8_url, referer, timestamp)}

def resolve_daddylive_m3u8(daddy_id):
    """
    Risolve l'URL dello stream .m3u8 autenticato da DaddyLive / Phantemlis CDN.
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

    headers = {
        "User-Agent": UA,
        "Referer": "https://dlstreams.st/"
    }

    # 1. Metodo Primario: Estrazione iframe dinamico dai domini mirror
    for domain in ["dlstreams.st", "dlhd.st", "dlhd.so", "dlhd.pk"]:
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

    # 2. Metodo Secondario: Endpoint diretti Romponalis
    for ep_name in ["daddy5.php", "daddy2.php", "daddy.php", "daddy3.php", "daddy4.php"]:
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
