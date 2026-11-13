import threading
try:
    from http.server import ThreadingHTTPServer as _BaseHTTPServer, BaseHTTPRequestHandler
except ImportError:
    from http.server import HTTPServer as _BaseHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qsl, urlencode, urljoin, quote
import requests
import re
import time
import xbmc

# Stato globale del proxy (per mantenere i token)
TOKEN_CACHE = {}
S22_SESSION_CACHE = {}
S22_WORKERS = {}
S22_LOCK = threading.Lock()

S22_STALL_REPIN_SECONDS = 25.0


def _s22_log(msg, level=None):
    xbmc.log(f"[CBTV S22] {msg}", level if level is not None else xbmc.LOGINFO)


S22_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Android TV; VegetaTV/1.0)',
    'Accept': 'audio/x-mpegurl,application/vnd.apple.mpegurl,text/plain,*/*',
    'Cache-Control': 'no-cache'
}


def _s22_parse_manifest_from(s, sid, matched_loc):
    """Scarica e analizza il manifest da un URL di nodo gia' noto. Ritorna (segments|None, info)."""
    try:
        r_m3u8 = s.get(matched_loc, headers=S22_HEADERS, timeout=3.0)
        if r_m3u8.status_code != 200:
            return None, f"m3u8_http {r_m3u8.status_code}"
        parsed_cdn = urlparse(matched_loc)
        # Mai accettare un redirect verso un nodo diverso (timestamp incompatibili)
        if urlparse(r_m3u8.url).netloc != parsed_cdn.netloc:
            return None, f"redirected_to {urlparse(r_m3u8.url).netloc}"
        cdn_host = f"{parsed_cdn.scheme}://{parsed_cdn.netloc}"
        base_dir = matched_loc.split('?', 1)[0].rsplit('/', 1)[0]
        segments = []
        lines = r_m3u8.text.splitlines()
        for i, line in enumerate(lines):
            line = line.strip()
            if line.startswith('#EXTINF:') and i + 1 < len(lines):
                seg_line = lines[i + 1].strip()
                m = re.search(rf'{sid}_(\d+)\.ts', seg_line)
                if m:
                    seq_num = int(m.group(1))
                    if seg_line.startswith('/'):
                        full_url = f"{cdn_host}{seg_line}"
                    elif not seg_line.startswith('http'):
                        full_url = f"{base_dir}/{seg_line}"
                    else:
                        full_url = seg_line
                    segments.append((seq_num, line, full_url))
        if not segments:
            return None, "m3u8_empty"
        return segments, "ok"
    except Exception as e:
        return None, f"m3u8_err {type(e).__name__}"


_S22_DIRECT_SESSION = requests.Session()
_S22_SEG_TLS = threading.local()


def _s22_fetch_direct(sid, direct_loc):
    """Richiede il manifest DIRETTAMENTE al nodo (URL salvato), senza passare dal load balancer."""
    return _s22_parse_manifest_from(_S22_DIRECT_SESSION, sid, direct_loc)


def _s22_fetch_manifest(sid, pinned_host=None):
    """Richiede un nuovo manifest al load balancer.
    Ritorna (segments, host, info) dove info descrive l'esito per i log diagnostici."""
    s = requests.Session()
    s22_headers = {
        'User-Agent': 'Mozilla/5.0 (Android TV; VegetaTV/1.0)',
        'Accept': 'audio/x-mpegurl,application/vnd.apple.mpegurl,text/plain,*/*',
        'Cache-Control': 'no-cache'
    }
    s22_url = f"http://interstellar.salex74.xyz:25461/live/gTfM0070/fBJb8hB/{sid}.m3u8"
    matched_loc = None
    seen_hosts = {}
    last_err = None

    if pinned_host:
        # Fino a 20 tentativi rapidi per agganciare ESCLUSIVAMENTE il nodo assegnato
        for _ in range(20):
            try:
                ts = int(time.time() * 1000)
                r_redir = s.get(f"{s22_url}?_vegeta_refresh={ts}", headers=s22_headers, allow_redirects=False, timeout=1.0)
                loc = r_redir.headers.get('Location')
                h = urlparse(loc).netloc if loc else f"HTTP{r_redir.status_code}"
                seen_hosts[h] = seen_hosts.get(h, 0) + 1
                if loc and pinned_host in loc:
                    matched_loc = loc
                    break
            except Exception as e:
                last_err = type(e).__name__
        if not matched_loc:
            return None, pinned_host, f"pinned_miss hosts={seen_hosts} err={last_err}"
    else:
        try:
            ts = int(time.time() * 1000)
            r_redir = s.get(f"{s22_url}?_vegeta_refresh={ts}", headers=s22_headers, allow_redirects=False, timeout=3.0)
            matched_loc = r_redir.headers.get('Location') or s22_url
            pinned_host = urlparse(matched_loc).netloc
        except Exception as e:
            return None, None, f"redirect_err {type(e).__name__}"

    segments, info = _s22_parse_manifest_from(s, sid, matched_loc)
    _s22_fetch_manifest.last_loc = matched_loc if segments else None
    return segments, pinned_host, info


def _s22_render_playlist(sess, window_size=6):
    """Genera una playlist HLS rigorosamente MONOTONICA: EXT-X-MEDIA-SEQUENCE non può mai decrescere.
    Le chiavi di sess['segments'] sono numeri di sequenza LOCALI (upstream + seq_offset)."""
    seg_dict = sess.get('segments', {})
    if not seg_dict:
        return None

    all_seqs = sorted(seg_dict.keys())
    active_seqs = all_seqs[-window_size:]
    last_seq = active_seqs[-1]
    media_seq = max(sess.get('media_seq', 0), active_seqs[0])
    sess['media_seq'] = media_seq

    valid_seqs = [s for s in active_seqs if s >= media_seq] or [last_seq]
    disc = sess.get('disc_seqs', set())
    # Conta le discontinuità uscite dalla finestra (richiesto da HLS per coerenza)
    tagged = len([s for s in valid_seqs[1:] if s in disc])
    disc_seq_num = max(0, sess.get('disc_total', 0) - tagged)

    lines = [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        f'#EXT-X-MEDIA-SEQUENCE:{valid_seqs[0]}',
        f'#EXT-X-DISCONTINUITY-SEQUENCE:{disc_seq_num}',
        '#EXT-X-ALLOW-CACHE:YES',
        '#EXT-X-TARGETDURATION:12'
    ]
    sid = sess.get('sid', '')
    for s in valid_seqs:
        if s in disc and s != valid_seqs[0]:
            lines.append('#EXT-X-DISCONTINUITY')
        inf, url = seg_dict[s]
        lines.append(inf)
        lines.append(f"/s22_seg?sid={sid}&seq={s}&u={quote(url, safe='')}")

    playlist_body = "\n".join(lines)
    sess['last_body'] = playlist_body
    sess['max_seq'] = last_seq
    return playlist_body


def _s22_worker_loop(sid):
    """Worker background: mantiene fresca la playlist sul nodo pinned.
    Se il nodo non fornisce segmenti nuovi per S22_STALL_REPIN_SECONDS, si ri-aggancia a un nuovo nodo
    inserendo #EXT-X-DISCONTINUITY (niente mescolanza di timestamp, niente playlist ferma -> niente EOF)."""
    _s22_log(f"worker avviato sid={sid}")
    t_start = time.time()
    while True:
        with S22_LOCK:
            sess = S22_SESSION_CACHE.get(sid)
            if not sess or (time.time() - sess.get('last_seen', 0) > 40):
                S22_SESSION_CACHE.pop(sid, None)
                S22_WORKERS.pop(sid, None)
                _s22_log(f"worker terminato sid={sid} (nessuna richiesta da Kodi)")
                break
            pinned_host = sess.get('pinned_host')
            last_new_ts = sess.setdefault('last_new_ts', time.time())

        elapsed = int(time.time() - t_start)
        stalled_for = time.time() - last_new_ts
        repin = stalled_for > S22_STALL_REPIN_SECONDS

        with S22_LOCK:
            direct_loc = sess.get('direct_loc')
            direct_since = sess.get('direct_since', time.time())

        t0 = time.time()
        new_segs, new_host, info = None, pinned_host, ""
        if direct_loc and not repin:
            new_segs, dinfo = _s22_fetch_direct(sid, direct_loc)
            if new_segs:
                info = "direct"
            else:
                _s22_log(f"sid={sid} t={elapsed}s DIRECT_FAIL {dinfo} url_age={int(time.time() - direct_since)}s -> riserva LB", xbmc.LOGWARNING)
                direct_loc = None
        if not new_segs:
            _s22_fetch_manifest.last_loc = None
            if repin:
                new_segs, new_host, info = _s22_fetch_manifest(sid, pinned_host=None)
            else:
                new_segs, new_host, info = _s22_fetch_manifest(sid, pinned_host)
            info = f"LB:{info}"
            fresh_loc = getattr(_s22_fetch_manifest, 'last_loc', None)
            if fresh_loc:
                with S22_LOCK:
                    sess['direct_loc'] = fresh_loc
                    sess['direct_since'] = time.time()
                _s22_log(f"sid={sid} nuovo URL diretto salvato: {fresh_loc}")
            elif not direct_loc:
                with S22_LOCK:
                    sess.pop('direct_loc', None)
        fetch_ms = int((time.time() - t0) * 1000)

        has_new_segment = False
        if new_segs:
            with S22_LOCK:
                sess = S22_SESSION_CACHE.get(sid)
                if sess:
                    seg_dict = sess.setdefault('segments', {})
                    offset = sess.get('seq_offset', 0)
                    if repin:
                        # Ri-aggancio: mappa gli ultimi 2 segmenti del nuovo nodo subito dopo l'ultimo servito
                        tail = new_segs[-2:]
                        offset = sess.get('max_seq', 0) + 1 - tail[0][0]
                        sess['seq_offset'] = offset
                        sess['pinned_host'] = new_host
                        sess.setdefault('disc_seqs', set()).add(tail[0][0] + offset)
                        sess['disc_total'] = sess.get('disc_total', 0) + 1
                        new_segs = tail
                        _s22_log(f"REPIN sid={sid} t={elapsed}s stallo={stalled_for:.0f}s {pinned_host} -> {new_host}", xbmc.LOGWARNING)
                    max_seq = sess.get('max_seq', 0)
                    for seq, inf, url in new_segs:
                        local = seq + offset
                        if local > max_seq:
                            has_new_segment = True
                        if local >= sess.get('media_seq', 0):
                            seg_dict[local] = (inf, url)
                    if has_new_segment:
                        sess['last_new_ts'] = time.time()
                    if len(seg_dict) > 12:
                        for old_k in sorted(seg_dict.keys())[:-12]:
                            seg_dict.pop(old_k, None)
                    disc = sess.get('disc_seqs', set())
                    if disc and seg_dict:
                        lo = min(seg_dict.keys())
                        sess['disc_seqs'] = {d for d in disc if d >= lo}
                    _s22_render_playlist(sess, window_size=6)
                    max_seq = sess.get('max_seq', 0)
            _s22_log(f"sid={sid} t={elapsed}s host={new_host} {info} up_segs={new_segs[0][0]}-{new_segs[-1][0]} new={has_new_segment} max={max_seq} fetch={fetch_ms}ms")
        else:
            _s22_log(f"sid={sid} t={elapsed}s FAIL {info} stallo={stalled_for:.0f}s fetch={fetch_ms}ms", xbmc.LOGWARNING)

        time.sleep(5.0 if has_new_segment else 2.0)


class FreeshotProxyHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Disabilita il log standard di BaseHTTPRequestHandler per non intasare kodi.log
        pass

    def _handle_s22_segment(self, params):
        seg_url = params.get('u')
        sid = params.get('sid', '')
        seq = params.get('seq', '?')
        if not seg_url:
            self.send_response(400)
            self.end_headers()
            return

        if sid:
            with S22_LOCK:
                sess = S22_SESSION_CACHE.get(sid)
                if sess:
                    sess['last_seen'] = time.time()

        s = getattr(_S22_SEG_TLS, 'session', None)
        if s is None:
            s = requests.Session()
            _S22_SEG_TLS.session = s

        last_err = ""
        for attempt in range(1, 4):
            t0 = time.time()
            try:
                r = s.get(seg_url, headers=S22_HEADERS, timeout=6.0)
                ms = int((time.time() - t0) * 1000)
                if r.status_code == 200 and r.content:
                    data = r.content
                    if attempt > 1 or ms > 2000:
                        _s22_log(f"SEG_OK sid={sid} seq={seq} bytes={len(data)} ms={ms} try={attempt}", xbmc.LOGWARNING)
                    else:
                        _s22_log(f"SEG_OK sid={sid} seq={seq} bytes={len(data)} ms={ms}")
                    self.send_response(200)
                    self.send_header("Content-Type", "video/mp2t")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                last_err = f"HTTP {r.status_code} bytes={len(r.content)}"
                _s22_log(f"SEG_FAIL sid={sid} seq={seq} try={attempt} {last_err} ms={ms}", xbmc.LOGWARNING)
            except Exception as e:
                ms = int((time.time() - t0) * 1000)
                last_err = f"{type(e).__name__}: {e}"
                _s22_log(f"SEG_FAIL sid={sid} seq={seq} try={attempt} {last_err} ms={ms}", xbmc.LOGWARNING)
            if attempt < 3:
                time.sleep(0.3)

        _s22_log(f"SEG_GIVEUP sid={sid} seq={seq} url={seg_url} err={last_err}", xbmc.LOGERROR)
        self.send_response(502)
        self.end_headers()

    def get_token(self, code, source_type):
        now = time.time()
        # Se abbiamo un token in cache valido per altri 60 secondi, usalo
        if code in TOKEN_CACHE and "token" in TOKEN_CACHE[code]:
            if now < (TOKEN_CACHE[code]["expires"] - 60):
                return TOKEN_CACHE[code]["token"], TOKEN_CACHE[code].get("path")
                
        # Altrimenti fetch nuovo token
        xbmc.log(f"[CBTV Proxy] Refresh token per {code} (Fonte {source_type})", xbmc.LOGINFO)
        s = requests.Session()
        s.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        })
        
        token = None
        path_override = None
        host_override = None
        try:
            if source_type == "freeshot": # Fonte 1
                s.headers.update({'Referer': 'https://thisnot.business/'})
                url = f"https://popcdn.day/player/{code}"
            elif source_type == "freeshot_v3": # Fonte 3
                s.headers.update({'Referer': 'https://lovetier.bz/'})
                url = f"https://lovetier.bz/player/{code}"
                
            r = s.get(url, timeout=10)
            m = re.search(r'currentToken:\s*["\']([^"\']+)["\']', r.text)
            if m:
                token = m.group(1)
                
            m_path = re.search(r'streamUrl:\s*["\']([^"\']+)["\']', r.text)
            if m_path:
                full_stream_url = m_path.group(1).replace('\\/', '/')
                parsed_stream = urlparse(full_stream_url)
                path_override = parsed_stream.path
                host_override = f"{parsed_stream.scheme}://{parsed_stream.netloc}"
                
            if token:
                TOKEN_CACHE[code] = {
                    "token": token,
                    "expires": now + 240,
                    "path": path_override,
                    "host": host_override
                }
                xbmc.log(f"[CBTV Proxy] Nuovo token ottenuto, host: {host_override}, path: {path_override}", xbmc.LOGINFO)
                
        except Exception as e:
            xbmc.log(f"[CBTV Proxy] Errore get_token_and_path: {e}", xbmc.LOGERROR)
            
        return token, path_override

    def do_GET(self):
        parsed = urlparse(self.path)
        params = dict(parse_qsl(parsed.query))
        
        path_base = parsed.path

        if path_base == '/s22_seg':
            self._handle_s22_segment(params)
            return

        code = params.get('code')
        source_type = params.get('source')
        
        if not code or not source_type:
            self.send_response(400)
            self.end_headers()
            return

        # ─── GESTIONE SPECIALE SERVER 22 (ATLANTIX HLS PROXY) ───
        if source_type == "s22":
            sid = code
            now = time.time()

            with S22_LOCK:
                sess = S22_SESSION_CACHE.get(sid)
                if sess:
                    sess['last_seen'] = now

            # Se abbiamo già un manifest in cache, invialo SUBITO a Kodi (< 1ms)
            if sess and sess.get('last_body'):
                # Assicurati che il worker thread sia attivo
                with S22_LOCK:
                    if sid not in S22_WORKERS or not S22_WORKERS[sid].is_alive():
                        t = threading.Thread(target=_s22_worker_loop, args=(sid,), daemon=True)
                        S22_WORKERS[sid] = t
                        t.start()

                self.send_response(200)
                self.send_header("Content-Type", "application/x-mpegURL")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                _s22_log(f"M3U8_SERVED sid={sid} media={sess.get('media_seq')} max={sess.get('max_seq')}")
                self.wfile.write(sess['last_body'].encode('utf-8'))
                return

            # Primo avvio del canale: fetch iniziale sincrono
            new_segs, pinned_host, info = _s22_fetch_manifest(sid, pinned_host=None)
            _s22_log(f"avvio sid={sid} host={pinned_host} {info}")
            if new_segs:
                with S22_LOCK:
                    sess = {
                        'sid': sid,
                        'pinned_host': pinned_host,
                        'segments': {seq: (inf, url) for seq, inf, url in new_segs},
                        'last_seen': now,
                        'media_seq': 0,
                        'seq_offset': 0,
                        'disc_seqs': set(),
                        'last_new_ts': now,
                        'direct_loc': getattr(_s22_fetch_manifest, 'last_loc', None),
                        'direct_since': now
                    }
                    body = _s22_render_playlist(sess, window_size=6)
                    S22_SESSION_CACHE[sid] = sess

                    if sid not in S22_WORKERS or not S22_WORKERS[sid].is_alive():
                        t = threading.Thread(target=_s22_worker_loop, args=(sid,), daemon=True)
                        S22_WORKERS[sid] = t
                        t.start()

                self.send_response(200)
                self.send_header("Content-Type", "application/x-mpegURL")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body.encode('utf-8'))
                return

            self.send_response(500)
            self.end_headers()
            return
        # ────────────────────────────────────────────────────────
            
        # Get valid token and path
        token, path_override = self.get_token(code, source_type)
        
        # Recupera host dall'estrazione o usa default
        cached = TOKEN_CACHE.get(code, {})
        stream_base_url = cached.get("host") or "https://beautifulpeople.lovecdn.ru"
        if not stream_base_url.endswith('/'): stream_base_url += '/'
        
        if not token:
            self.send_response(500)
            self.end_headers()
            return
            
        # Determina gli endpoint originali in base alla fonte
        # stream_base_url definito sopra dinamicamente
        
        # Se abbiamo catturato un path override dal javascript del player (es. /POLSATSPORTPL/index.m3u8) usiamo quello
        if path_override:
            orig_m3u8_path = path_override
        else:
            if source_type == "freeshot":
                orig_m3u8_path = f"/{code}/tracks-v1a1/mono.m3u8"
            else: # freeshot_v3
                orig_m3u8_path = f"/{code}/tracks-v1a1/mono.m3u8"
            
        # Se la richiesta è proxy/sub.m3u8, vuol dire che stiamo fetchando la sub-playlist
        if path_base == "/sub.m3u8":
            sub_path = params.get('sub_path', 'tracks-v1a1/mono.m3u8')
            if path_override:
                base_dir = path_override.rsplit('/', 1)[0]
                orig_m3u8_path = f"{base_dir}/{sub_path}"
            else:
                orig_m3u8_path = f"/{code}/{sub_path}"
            
        real_url = f"{stream_base_url}{orig_m3u8_path.lstrip('/')}?token={token}"
        
        try:
            s = requests.Session()
            s.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'
            })
            r = s.get(real_url, timeout=10)
            
            if r.status_code != 200:
                self.send_response(r.status_code)
                self.end_headers()
                return
                
            text = r.text
            new_lines = []
            
            # Rewrite playlist
            is_subplaylist = False
            for line in text.split('\n'):
                line = line.strip()
                if not line:
                    continue
                if line.startswith('#'):
                    new_lines.append(line)
                    if line.startswith('#EXT-X-STREAM-INF'):
                        is_subplaylist = True
                else:
                    # E' un URL
                    if is_subplaylist or line.split('?')[0].endswith('.m3u8'): 
                        # Sub-playlist trovata in index.m3u8
                        # Facciamo in modo che il player la chieda di nuovo al proxy
                        proxy_url = f"http://127.0.0.1:{self.server.server_port}/sub.m3u8?code={code}&source={source_type}&sub_path={line.split('?')[0]}"
                        new_lines.append(proxy_url)
                        is_subplaylist = False
                    else:
                        # Segmento TS trovato. Trasformiamo in URL assoluto diretto al server, con il token attuale
                        if line.startswith('http'):
                            # GIA assoluto, sostituiamo token
                            if 'token=' in line:
                                t_url = re.sub(r'token=[^&]+', f'token={token}', line)
                            else:
                                t_url = line + (f'&token={token}' if '?' in line else f'?token={token}')
                        else:
                            # Relativo
                            base_for_ts = real_url.split('?')[0].rsplit('/', 1)[0] + '/'
                            abs_url = urljoin(base_for_ts, line)
                            if 'token=' in abs_url:
                                t_url = re.sub(r'token=[^&]+', f'token={token}', abs_url)
                            else:
                                t_url = abs_url + (f'&token={token}' if '?' in abs_url else f'?token={token}')
                        new_lines.append(t_url)
                        
            final_m3u8 = "\n".join(new_lines)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/x-mpegURL")
            self.end_headers()
            self.wfile.write(final_m3u8.encode('utf-8'))
            
        except Exception as e:
            xbmc.log(f"[CBTV Proxy] Errore elaborazione richiesta: {e}", xbmc.LOGERROR)
            self.send_response(500)
            self.end_headers()

class ProxyManager:
    def __init__(self):
        self.server = None
        self.thread = None
        self.port = 0

    def start(self):
        # Binding alla porta 0 assegna una porta random libera
        class _ThreadedServer(_BaseHTTPServer):
            daemon_threads = True
            allow_reuse_address = True
        self.server = _ThreadedServer(('127.0.0.1', 0), FreeshotProxyHandler)
        self.port = self.server.server_port
        
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()
        xbmc.log(f"[CBTV Proxy] Server avviato su porta {self.port}", xbmc.LOGINFO)
        return self.port

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            xbmc.log("[CBTV Proxy] Server arrestato", xbmc.LOGINFO)
