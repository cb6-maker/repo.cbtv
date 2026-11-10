import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qsl, urlencode, urljoin
import requests
import re
import time
import xbmc

# Stato globale del proxy (per mantenere i token)
TOKEN_CACHE = {}
S22_SESSION_CACHE = {}
S22_WORKERS = {}
S22_LOCK = threading.Lock()

def _s22_fetch_manifest(sid, pinned_host=None):
    """Richiede un nuovo manifest al load balancer garantendo l'aggancio RIGIDO allo stesso nodo encoder."""
    s = requests.Session()
    s22_headers = {
        'User-Agent': 'Mozilla/5.0 (Android TV; VegetaTV/1.0)',
        'Accept': 'audio/x-mpegurl,application/vnd.apple.mpegurl,text/plain,*/*',
        'Cache-Control': 'no-cache'
    }
    s22_url = f"http://interstellar.salex74.xyz:25461/live/gTfM0070/fBJb8hB/{sid}.m3u8"
    matched_loc = None

    if pinned_host:
        # Fai fino a 20 tentativi rapidi in sessione HTTP per agganciare ESCLUSIVAMENTE il nodo assegnato
        # Con HTTP keep-alive 20 tentativi richiedono appena ~0.3s e coprono qualsiasi raffica del Load Balancer
        for _ in range(20):
            try:
                ts = int(time.time() * 1000)
                r_redir = s.get(f"{s22_url}?_vegeta_refresh={ts}", headers=s22_headers, allow_redirects=False, timeout=1.0)
                loc = r_redir.headers.get('Location')
                if loc and pinned_host in loc:
                    matched_loc = loc
                    break
            except Exception:
                pass
        # Se in questo ciclo il nodo non ha risposto, NON mischiare segmenti con altri nodi!
        if not matched_loc:
            return None, pinned_host
    else:
        try:
            ts = int(time.time() * 1000)
            r_redir = s.get(f"{s22_url}?_vegeta_refresh={ts}", headers=s22_headers, allow_redirects=False, timeout=3.0)
            matched_loc = r_redir.headers.get('Location') or s22_url
            pinned_host = urlparse(matched_loc).netloc
        except Exception:
            return None, None

    if not matched_loc:
        return None, pinned_host

    try:
        r_m3u8 = s.get(matched_loc, headers=s22_headers, timeout=3.0)
        if r_m3u8.status_code == 200:
            parsed_cdn = urlparse(matched_loc)
            cdn_host = f"{parsed_cdn.scheme}://{parsed_cdn.netloc}"
            base_dir = matched_loc.rsplit('/', 1)[0]
            raw_text = r_m3u8.text

            segments = []
            lines = raw_text.splitlines()
            for i, line in enumerate(lines):
                line = line.strip()
                if line.startswith('#EXTINF:'):
                    inf_line = line
                    if i + 1 < len(lines):
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
                            segments.append((seq_num, inf_line, full_url))
            return segments, pinned_host
    except Exception:
        pass
    return None, pinned_host

def _s22_render_playlist(sess, window_size=10):
    """Genera una playlist HLS rigorosamente MONOTONICA: EXT-X-MEDIA-SEQUENCE non può mai decrescere."""
    seg_dict = sess.get('segments', {})
    if not seg_dict:
        return None

    all_seqs = sorted(seg_dict.keys())
    # Mantieni fino a window_size segmenti più recenti (fino a 100 secondi di buffer continuo)
    active_seqs = all_seqs[-window_size:]
    
    first_seq = active_seqs[0]
    last_seq = active_seqs[-1]
    prev_media_seq = sess.get('media_seq', 0)

    # REQUISITO CRITICO HLS: media sequence deve essere sempre >= a quella precedente
    media_seq = max(prev_media_seq, first_seq)
    sess['media_seq'] = media_seq

    valid_seqs = [s for s in active_seqs if s >= media_seq]
    if not valid_seqs:
        valid_seqs = active_seqs

    lines = [
        '#EXTM3U',
        '#EXT-X-VERSION:3',
        f'#EXT-X-MEDIA-SEQUENCE:{media_seq}',
        '#EXT-X-ALLOW-CACHE:YES',
        '#EXT-X-TARGETDURATION:12'
    ]
    for s in valid_seqs:
        inf, url = seg_dict[s]
        lines.append(inf)
        lines.append(url)

    playlist_body = "\n".join(lines)
    sess['last_body'] = playlist_body
    sess['max_seq'] = last_seq
    return playlist_body

def _s22_worker_loop(sid):
    """Worker background per mantenere costantemente fresca la playlist sincronizzata sul battito reale dell'encoder."""
    while True:
        with S22_LOCK:
            sess = S22_SESSION_CACHE.get(sid)
            if not sess or (time.time() - sess.get('last_seen', 0) > 40):
                # Nessuna richiesta da oltre 40 secondi: canale chiuso o cambiato
                S22_SESSION_CACHE.pop(sid, None)
                S22_WORKERS.pop(sid, None)
                break
            pinned_host = sess.get('pinned_host')
            current_max_seq = sess.get('max_seq', 0)

        # Fetch segmenti ESCLUSIVAMENTE dal nodo pinned_host
        new_segs, _ = _s22_fetch_manifest(sid, pinned_host)
        has_new_segment = False
        if new_segs:
            with S22_LOCK:
                sess = S22_SESSION_CACHE.get(sid)
                if sess:
                    seg_dict = sess.setdefault('segments', {})
                    for seq, inf, url in new_segs:
                        seg_dict[seq] = (inf, url)
                        if seq > current_max_seq:
                            has_new_segment = True

                    # Conserva fino a 20 segmenti in memoria
                    if len(seg_dict) > 20:
                        for old_k in sorted(seg_dict.keys())[:-20]:
                            seg_dict.pop(old_k, None)

                    _s22_render_playlist(sess, window_size=10)

        # Polling adattivo sul ritmo di generazione dell'encoder:
        # Se è appena comparso un nuovo segmento, attendi 5 secondi (metà durata segmento).
        # Se non è ancora comparso il nuovo segmento, ricontrolla tra 2.0 secondi per non accumulare drift!
        if has_new_segment:
            time.sleep(5.0)
        else:
            time.sleep(2.0)

class FreeshotProxyHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Disabilita il log standard di BaseHTTPRequestHandler per non intasare kodi.log
        pass

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
                self.wfile.write(sess['last_body'].encode('utf-8'))
                return

            # Primo avvio del canale: fetch iniziale sincrono
            new_segs, pinned_host = _s22_fetch_manifest(sid, pinned_host=None)
            if new_segs:
                with S22_LOCK:
                    sess = {
                        'pinned_host': pinned_host,
                        'segments': {seq: (inf, url) for seq, inf, url in new_segs},
                        'last_seen': now,
                        'media_seq': 0
                    }
                    body = _s22_render_playlist(sess, window_size=10)
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
        self.server = HTTPServer(('127.0.0.1', 0), FreeshotProxyHandler)
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
