import threading
try:
    from http.server import ThreadingHTTPServer as _BaseHTTPServer, BaseHTTPRequestHandler
except ImportError:
    from http.server import HTTPServer as _BaseHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qsl, urlencode, urljoin, quote
import requests
from requests.adapters import HTTPAdapter
import re
import time
import xbmc

# Stato globale del proxy (per mantenere i token)
TOKEN_CACHE = {}
S14_SESSION_CACHE = {}
S14_WORKERS = {}
S14_LOCK = threading.Lock()

S14_STALL_REPIN_SECONDS = 45.0
S14_IDLE_TIMEOUT_SECONDS = 180.0


HLS_SERVERS = {
    's14': {
        'base_url': 'http://ios.dragonsdog.com/live/peppedent/Rl8HYEmMFn24',
        'headers': {
            'User-Agent': 'VLC/3.0.20 LibVLC/3.0.20',
            'Accept': 'audio/x-mpegurl,application/vnd.apple.mpegurl,text/plain,*/*',
            'Cache-Control': 'no-cache'
        },
        'pin_host': True,
        'exclude_hosts': ('load2.sploadbl.date', 'load6.sploadbl.org.uk'),
        'tag': 'S14',
    },
    's17': {
        'base_url': 'http://103.205.18.126/live/elettro1/h0cg1VkmhN',
        'headers': {
            'User-Agent': 'VegetaTV/1.0',
            'Accept': 'application/vnd.apple.mpegurl, application/x-mpegURL, */*',
            'Cache-Control': 'no-cache'
        },
        'pin_host': False,
        'exclude_hosts': (),
        'poll_ok': 9.0,
        'poll_same': 4.0,
        'poll_fail': 4.0,
        'tag': 'S17',
    },
}

S14_HEADERS = HLS_SERVERS['s14']['headers']


def _s14_log(msg, level=None, source='s14'):
    tag = HLS_SERVERS.get(source, HLS_SERVERS['s14'])['tag']
    xbmc.log(f"[CBTV {tag}] {msg}", level if level is not None else xbmc.LOGINFO)


def _s14_parse_manifest_from(s, sid, matched_loc, headers=None):
    """Scarica e analizza il manifest da un URL di nodo gia' noto. Ritorna (segments|None, info)."""
    try:
        r_m3u8 = s.get(matched_loc, headers=headers or S14_HEADERS, timeout=3.0)
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


_S14_MANIFEST_SESSION = requests.Session()
_S14_SEG_SESSION = None


def _get_s14_seg_session():
    """Restituisce una Session condivisa con connection pool keep-alive per i segmenti .ts."""
    global _S14_SEG_SESSION
    with S14_LOCK:
        if _S14_SEG_SESSION is None:
            s = requests.Session()
            adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8)
            s.mount('http://', adapter)
            s.mount('https://', adapter)
            _S14_SEG_SESSION = s
        return _S14_SEG_SESSION


def _close_s14_seg_session():
    """Chiude e azzera la Session condivisa dei segmenti (rilascia subito i socket TCP)."""
    global _S14_SEG_SESSION
    with S14_LOCK:
        s = _S14_SEG_SESSION
        _S14_SEG_SESSION = None
    if s is not None:
        try:
            s.close()
        except Exception:
            pass


def _s14_download_segment(seg_url, sid="", seq="?", source="s14", max_tries=2):
    """Scarica un segmento .ts con sessione condivisa keep-alive, timeout rapido e tetto wall-clock.
    Ritorna (data_bytes|None, attempt, elapsed_ms, last_err)."""
    s = _get_s14_seg_session()
    headers = HLS_SERVERS.get(source, HLS_SERVERS['s14'])['headers']

    last_err = ""
    for attempt in range(1, max_tries + 1):
        t0 = time.time()
        try:
            with s.get(seg_url, headers=headers, cookies={}, timeout=(2.5, 4.0), stream=True) as r:
                if r.status_code != 200:
                    ms = int((time.time() - t0) * 1000)
                    last_err = f"HTTP {r.status_code}"
                    _s14_log(f"SEG_FAIL sid={sid} seq={seq} try={attempt} {last_err} ms={ms}", xbmc.LOGWARNING, source=source)
                else:
                    chunks = []
                    for chunk in r.iter_content(chunk_size=65536):
                        if chunk:
                            chunks.append(chunk)
                        if time.time() - t0 > 6.0:
                            raise requests.exceptions.ReadTimeout("Wall-clock timeout > 6.0s")
                    data = b"".join(chunks)
                    ms = int((time.time() - t0) * 1000)
                    if data:
                        return data, attempt, ms, ""
                    last_err = "empty_body"
                    _s14_log(f"SEG_FAIL sid={sid} seq={seq} try={attempt} {last_err} ms={ms}", xbmc.LOGWARNING, source=source)
        except Exception as e:
            ms = int((time.time() - t0) * 1000)
            last_err = f"{type(e).__name__}: {e}"
            _s14_log(f"SEG_FAIL sid={sid} seq={seq} try={attempt} {last_err} ms={ms}", xbmc.LOGWARNING, source=source)
        if attempt < max_tries:
            time.sleep(0.2)
    return None, max_tries, 0, last_err


def _s14_fetch_manifest(sid, pinned_host=None, exclude_host=None, source="s14", last_loc=None, extra_exclude=()):
    """Richiede un nuovo manifest al load balancer per il server HLS indicato (s14/s17).
    Per server con pin_host=True (es. S14) mantiene blocco rigido su pinned_host fino a 25 tentativi.
    Per server con sequenza condivisa tra i nodi (es. S17) fa una singola chiamata rapida."""
    cfg = HLS_SERVERS.get(source, HLS_SERVERS['s14'])
    headers = cfg['headers']
    s14_url = f"{cfg['base_url']}/{sid}.m3u8"
    exclude_hosts = tuple(cfg.get('exclude_hosts', ())) + tuple(extra_exclude or ())
    matched_loc = None
    seen_hosts = {}
    last_err = None

    if not cfg.get('pin_host', True):
        try:
            ts = int(time.time() * 1000)
            r_redir = _S14_MANIFEST_SESSION.get(f"{s14_url}?_vegeta_refresh={ts}", headers=headers, allow_redirects=False, timeout=4.0)
            loc = r_redir.headers.get('Location') or (s14_url if r_redir.status_code == 200 else None)
            if not loc:
                return None, None, f"lb_http {r_redir.status_code}"
            pinned_host = urlparse(loc).netloc
            if last_loc and loc == last_loc:
                return None, pinned_host, "same_token"
            matched_loc = loc
        except Exception as e:
            return None, None, f"lb_err {type(e).__name__}"
    elif pinned_host:
        for _ in range(25):
            try:
                ts = int(time.time() * 1000)
                r_redir = _S14_MANIFEST_SESSION.get(f"{s14_url}?_vegeta_refresh={ts}", headers=headers, allow_redirects=False, timeout=1.5)
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
        failed_hosts = set()
        fallback_locs = {}
        last_parse_info = None
        last_parse_host = None
        for idx in range(16):
            try:
                ts = int(time.time() * 1000)
                r_redir = _S14_MANIFEST_SESSION.get(f"{s14_url}?_vegeta_refresh={ts}", headers=headers, allow_redirects=False, timeout=2.0)
                loc = r_redir.headers.get('Location') or (s14_url if r_redir.status_code == 200 else None)
                if not loc:
                    last_err = f"HTTP{r_redir.status_code}"
                    continue
                h = urlparse(loc).netloc
                seen_hosts[h] = seen_hosts.get(h, 0) + 1
                if any(ex in h for ex in exclude_hosts) or h in failed_hosts:
                    continue
                fallback_locs[h] = loc
                if exclude_host and exclude_host in h and idx < 10:
                    continue
                segs, p_info = _s14_parse_manifest_from(_S14_MANIFEST_SESSION, sid, loc, headers=headers)
                if segs:
                    _s14_fetch_manifest.last_loc = loc
                    return segs, h, p_info
                failed_hosts.add(h)
                last_parse_info = p_info
                last_parse_host = h
            except Exception as e:
                last_err = type(e).__name__
        if exclude_host and exclude_host in fallback_locs and exclude_host not in failed_hosts:
            loc = fallback_locs[exclude_host]
            segs, p_info = _s14_parse_manifest_from(_S14_MANIFEST_SESSION, sid, loc, headers=headers)
            if segs:
                _s14_fetch_manifest.last_loc = loc
                return segs, exclude_host, p_info
            last_parse_info = p_info
            last_parse_host = exclude_host
        _s14_fetch_manifest.last_loc = None
        if last_parse_info:
            return None, last_parse_host, f"{last_parse_info} hosts={seen_hosts}"
        return None, None, f"redirect_err hosts={seen_hosts} err={last_err}"

    segments, info = _s14_parse_manifest_from(_S14_MANIFEST_SESSION, sid, matched_loc, headers=headers)
    _s14_fetch_manifest.last_loc = matched_loc if segments else None
    return segments, pinned_host, info


def _s14_render_playlist(sess, window_size=6):
    """Genera una playlist HLS rigorosamente MONOTONICA: EXT-X-MEDIA-SEQUENCE non può mai decrescere.
    Le chiavi di sess['segments'] sono numeri di sequenza LOCALI (upstream + seq_offset)."""
    seg_dict = sess.get('segments', {})
    if not seg_dict:
        return None

    all_seqs = sorted(seg_dict.keys())
    kodi_seq = sess.get('last_kodi_seq', 0)
    if not kodi_seq and not sess.get('startup_done') and len(all_seqs) >= 5:
        # Tampone iniziale (+20s di buffer): all'avvio nascondi gli ultimi 2 segmenti
        # così Kodi parte ~2 segmenti più indietro e li ritrova subito al refresh successivo.
        active_seqs = all_seqs[:-2][-window_size:]
    else:
        active_seqs = all_seqs[-window_size:]
    if kodi_seq:
        next_needed = kodi_seq + 1
        if next_needed < active_seqs[0] and next_needed in seg_dict:
            gap = active_seqs[0] - next_needed
            # Scorri in modo continuo senza gradini: se gap supera max_extra (10),
            # avanza di 1 segmento alla volta invece di azzerare e saltarne 3+ in blocco.
            extra = min(gap, 10)
            active_seqs = all_seqs[-(window_size + extra):]
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
    source = sess.get('source', 's14')
    for s in valid_seqs:
        if s in disc and s != valid_seqs[0]:
            lines.append('#EXT-X-DISCONTINUITY')
        inf, url = seg_dict[s]
        lines.append(inf)
        lines.append(f"/s14_seg?src={source}&sid={sid}&seq={s}&u={quote(url, safe='')}")

    playlist_body = "\n".join(lines)
    sess['last_body'] = playlist_body
    sess['max_seq'] = last_seq
    return playlist_body


def _s14_worker_loop(sess_key, worker_id=None):
    """Worker background: mantiene fresca la playlist per server HLS (S14 / S17).
    Se il nodo non fornisce segmenti nuovi per S14_STALL_REPIN_SECONDS o l'encoder riparte da zero,
    rimappa la sequenza in avanti inserendo #EXT-X-DISCONTINUITY."""
    with S14_LOCK:
        _init = S14_SESSION_CACHE.get(sess_key) or {}
        source = _init.get('source', 's14')
        sid = _init.get('sid', sess_key)
    cfg = HLS_SERVERS.get(source, HLS_SERVERS['s14'])
    pin_mode = cfg.get('pin_host', True)
    poll_ok = cfg.get('poll_ok', 5.0)
    poll_same = cfg.get('poll_same', 2.0)
    poll_fail = cfg.get('poll_fail', 1.0)
    _s14_log(f"worker avviato sid={sid}", source=source)
    t_start = time.time()
    # Pausa iniziale: do_GET ha appena scaricato il manifest a t=0s; attendiamo poll_ok
    # per non collidere col download del primo segmento .ts su account max_connections=1.
    time.sleep(poll_ok)
    while True:
        with S14_LOCK:
            sess = S14_SESSION_CACHE.get(sess_key)
            if not sess or (worker_id is not None and sess.get('worker_id') != worker_id):
                _s14_log(f"worker sostituito sid={sid}", source=source)
                break
            if time.time() - sess.get('last_seen', 0) > S14_IDLE_TIMEOUT_SECONDS:
                S14_SESSION_CACHE.pop(sess_key, None)
                S14_WORKERS.pop(sess_key, None)
                _s14_log(f"worker terminato sid={sid} (nessuna richiesta da Kodi)", source=source)
                break
            pinned_host = sess.get('pinned_host')
            last_new_ts = sess.setdefault('last_new_ts', time.time())
            miss_streak = sess.get('miss_streak', 0)
            last_loc = sess.get('last_loc')
            bad_hosts = tuple(sess.get('bad_hosts', ()))

        elapsed = int(time.time() - t_start)
        stalled_for = time.time() - last_new_ts
        repin = pin_mode and ((stalled_for > S14_STALL_REPIN_SECONDS) or (miss_streak >= 3) or (pinned_host in bad_hosts))

        t0 = time.time()
        _s14_fetch_manifest.last_loc = None
        if repin:
            new_segs, new_host, info = _s14_fetch_manifest(sid, pinned_host=None, exclude_host=pinned_host, source=source, extra_exclude=bad_hosts)
        else:
            new_segs, new_host, info = _s14_fetch_manifest(sid, pinned_host, source=source, last_loc=last_loc, extra_exclude=bad_hosts)
        raw_info = info
        info = f"LB:{info}"
        fetch_ms = int((time.time() - t0) * 1000)

        has_new_segment = False
        stale_skip = False
        if new_segs:
            fetched_loc = getattr(_s14_fetch_manifest, 'last_loc', None)
            with S14_LOCK:
                sess = S14_SESSION_CACHE.get(sess_key)
                if sess:
                    sess['miss_streak'] = 0
                    if fetched_loc:
                        sess['last_loc'] = fetched_loc
                    seg_dict = sess.setdefault('segments', {})
                    host_offsets = sess.setdefault('host_offsets', {})
                    if not pin_mode and new_host:
                        offset = host_offsets.get(new_host, 0)
                    else:
                        offset = sess.get('seq_offset', 0)
                    max_seq = sess.get('max_seq', 0)
                    floor_seq = max(max_seq, sess.get('last_kodi_seq', 0))
                    new_max = new_segs[-1][0] + offset
                    lag = floor_seq - new_max
                    if not pin_mode and (lag > 0 or (new_max - floor_seq) > 30) and stalled_for <= 30.0:
                        stale_skip = True
                    else:
                        seq_reset = (lag > 10) if not pin_mode else (new_max < floor_seq)
                        host_switched = pin_mode and bool(new_host and pinned_host and new_host != pinned_host)
                        if host_switched or seq_reset:
                            # Cambio nodo (se pin_mode) o reset encoder da 0:
                            # su cambio nodo ricalcola SEMPRE l'offset in modo contiguo da floor_seq + 1
                            # (mai sommare il vecchio seq_offset del nodo precedente!) così EXT-X-MEDIA-SEQUENCE
                            # non fa salti enormi (es. 449 -> 899) e #EXT-X-DISCONTINUITY resta sempre nella finestra.
                            if host_switched:
                                tail = new_segs[-3:] if len(new_segs) >= 3 else new_segs
                                offset = floor_seq + 1 - tail[0][0]
                                sess['seq_offset'] = offset
                                first_local = tail[0][0] + offset
                                new_segs = tail
                            else:
                                forward = [x for x in new_segs if (x[0] + offset) > floor_seq]
                                if forward and (forward[0][0] + offset) <= floor_seq + 20:
                                    first_local = forward[0][0] + offset
                                    new_segs = forward
                                else:
                                    tail = new_segs[-2:]
                                    offset = floor_seq + 1 - tail[0][0]
                                    if not pin_mode and new_host:
                                        host_offsets[new_host] = offset
                                    else:
                                        sess['seq_offset'] = offset
                                    first_local = tail[0][0] + offset
                                    new_segs = tail
                            sess['pinned_host'] = new_host or pinned_host
                            sess.setdefault('disc_seqs', set()).add(first_local)
                            sess['disc_total'] = sess.get('disc_total', 0) + 1
                            tag = "SEQ_RESET" if (not host_switched and seq_reset) else "NODE_SWITCH"
                            _s14_log(f"{tag} sid={sid} t={elapsed}s {pinned_host} -> {new_host} from={first_local}", xbmc.LOGWARNING, source=source)
                        elif repin:
                            _s14_log(f"REPIN_SAME sid={sid} t={elapsed}s stallo={stalled_for:.0f}s host={new_host} (continua senza buchi)", source=source)
                        elif new_host and not pin_mode:
                            sess['pinned_host'] = new_host
                        for seq, inf, url in new_segs:
                            local = seq + offset
                            if local > max_seq:
                                has_new_segment = True
                            if local >= sess.get('media_seq', 0):
                                # Su server multi-IP senza pinning (S17), non sovrascrivere segmenti
                                # gia' in cache per evitare duplicati da nodi sfasati di +-1.
                                if pin_mode or local not in seg_dict:
                                    seg_dict[local] = (inf, url)
                        if has_new_segment:
                            sess['last_new_ts'] = time.time()
                        if len(seg_dict) > 18:
                            for old_k in sorted(seg_dict.keys())[:-18]:
                                seg_dict.pop(old_k, None)
                        disc = sess.get('disc_seqs', set())
                        if disc and seg_dict:
                            lo = min(seg_dict.keys())
                            sess['disc_seqs'] = {d for d in disc if d >= lo}
                        _s14_render_playlist(sess, window_size=6)
                        max_seq = sess.get('max_seq', 0)
            if stale_skip:
                _s14_log(f"sid={sid} t={elapsed}s SKIP stale_manifest host={new_host} up_segs={new_segs[0][0]}-{new_segs[-1][0]} max={max_seq} fetch={fetch_ms}ms", source=source)
            else:
                _s14_log(f"sid={sid} t={elapsed}s host={new_host} {info} up_segs={new_segs[0][0]}-{new_segs[-1][0]} new={has_new_segment} max={max_seq} fetch={fetch_ms}ms", source=source)
        elif raw_info == "same_token":
            _s14_log(f"sid={sid} t={elapsed}s SKIP same_token host={new_host} fetch={fetch_ms}ms", source=source)
        else:
            with S14_LOCK:
                sess = S14_SESSION_CACHE.get(sess_key)
                if sess:
                    sess['miss_streak'] = sess.get('miss_streak', 0) + 1
                    streak = sess['miss_streak']
                else:
                    streak = 0
            _s14_log(f"sid={sid} t={elapsed}s FAIL {info} miss={streak}/3 stallo={stalled_for:.0f}s fetch={fetch_ms}ms", xbmc.LOGWARNING, source=source)

        time.sleep(poll_ok if has_new_segment else (poll_same if (new_segs or raw_info == "same_token") else poll_fail))


class FreeshotProxyHandler(BaseHTTPRequestHandler):
    
    def log_message(self, format, *args):
        # Disabilita il log standard di BaseHTTPRequestHandler per non intasare kodi.log
        pass

    def _handle_s14_segment(self, params):
        seg_url = params.get('u')
        sid = params.get('sid', '')
        seq = params.get('seq', '?')
        source = params.get('src', 's14')
        sess_key = f"{source}:{sid}" if sid else ""
        pin_mode = HLS_SERVERS.get(source, HLS_SERVERS['s14']).get('pin_host', True)
        if not seg_url:
            self.send_response(400)
            self.end_headers()
            return

        seq_num = None
        if sess_key:
            with S14_LOCK:
                sess = S14_SESSION_CACHE.get(sess_key)
                if sess:
                    sess['last_seen'] = time.time()
                    try:
                        seq_num = int(seq)
                        if seq_num > sess.get('last_kodi_seq', 0):
                            sess['last_kodi_seq'] = seq_num
                    except (TypeError, ValueError):
                        pass

        is_startup_seg = False
        if sess_key:
            with S14_LOCK:
                sess = S14_SESSION_CACHE.get(sess_key)
                if sess:
                    is_startup_seg = not sess.get('served_any_seg', False)

        data, attempt, ms, last_err = _s14_download_segment(seg_url, sid=sid, seq=seq, source=source)
        if not data and pin_mode and sess_key:
            bad_host = urlparse(seg_url).netloc
            is_net_err = any(k in (last_err or "") for k in ("Timeout", "ConnectionError", "ConnectTimeout", "ReadTimeout"))
            bad_hosts = ()
            with S14_LOCK:
                sess = S14_SESSION_CACHE.get(sess_key)
                if sess:
                    bh_set = sess.setdefault('bad_hosts', set())
                    if bad_host and is_net_err:
                        bh_set.add(bad_host)
                    bad_hosts = tuple(bh_set)
                    sess['miss_streak'] = max(sess.get('miss_streak', 0), 3)
            if is_startup_seg:
                # Solo all'avvio (prima che Kodi abbia agganciato il clock A/V): cambia nodo al volo
                # per evitare il timeout di OpenInputStream su nodi morti come load6.
                _s14_log(f"SEG_REPIN_STARTUP sid={sid} seq={seq} escludo host={bad_host} (bad_hosts={bad_hosts})", xbmc.LOGWARNING, source=source)
                new_segs, new_host, info = _s14_fetch_manifest(sid, pinned_host=None, exclude_host=bad_host, source=source, extra_exclude=bad_hosts)
                if new_segs and new_host:
                    tail = new_segs[-3:] if len(new_segs) >= 3 else new_segs
                    with S14_LOCK:
                        sess = S14_SESSION_CACHE.get(sess_key)
                        if sess:
                            sess['pinned_host'] = new_host
                            sess['miss_streak'] = 0
                            start_target = seq_num if seq_num is not None else tail[0][0]
                            offset = start_target - tail[0][0]
                            sess['seq_offset'] = offset
                            sess['segments'] = {s_num + offset: (s_inf, s_url) for s_num, s_inf, s_url in tail}
                            sess['disc_seqs'] = set()
                            _s14_render_playlist(sess, window_size=6)
                    data, attempt, ms, last_err = _s14_download_segment(tail[0][2], sid=sid, seq=f"{seq}->repin({new_host})", source=source)
            else:
                # A riproduzione avviata MAI iniettare byte di un altro encoder sullo stesso seq senza #EXT-X-DISCONTINUITY
                # (causa velocizzazioni video su Firestick/MediaCodec): lasciamo fare NODE_SWITCH pulito al worker.
                _s14_log(f"SEG_FAIL_TRIGGER_REPIN sid={sid} seq={seq} host={bad_host} err={last_err} (bad_hosts={bad_hosts})", xbmc.LOGWARNING, source=source)
        if data and not pin_mode and sess_key and seq_num is not None:
            sig = len(data)
            candidates = []
            recent_snapshot = set()
            with S14_LOCK:
                sess = S14_SESSION_CACHE.get(sess_key)
                if sess:
                    recent = sess.setdefault('recent_sigs', [])
                    recent_snapshot = set(recent)
                    if sig in recent_snapshot:
                        segs_map = sess.get('segments', {})
                        for step in (1, 2, 3):
                            nxt = segs_map.get(seq_num + step)
                            if nxt and nxt[1] != seg_url:
                                candidates.append((seq_num + step, nxt[1]))
            for cand_seq, cand_url in candidates:
                data2, att2, ms2, _ = _s14_download_segment(cand_url, sid=sid, seq=str(cand_seq), source=source)
                if data2:
                    sig2 = len(data2)
                    if sig2 not in recent_snapshot and sig2 != sig:
                        _s14_log(f"SEG_DEDUP sid={sid} seq={seq} -> {cand_seq} bytes={len(data2)} ms={ms2}", xbmc.LOGWARNING, source=source)
                        data, attempt, ms, sig = data2, att2, ms2, sig2
                        with S14_LOCK:
                            sess = S14_SESSION_CACHE.get(sess_key)
                            if sess and cand_seq > sess.get('last_kodi_seq', 0):
                                sess['last_kodi_seq'] = cand_seq
                        break
            with S14_LOCK:
                sess = S14_SESSION_CACHE.get(sess_key)
                if sess:
                    recent = sess.setdefault('recent_sigs', [])
                    recent.append(sig)
                    if len(recent) > 6:
                        del recent[:-6]

        if data:
            if sess_key:
                with S14_LOCK:
                    sess = S14_SESSION_CACHE.get(sess_key)
                    if sess:
                        sess['served_any_seg'] = True
            if attempt > 1 or ms > 2000:
                _s14_log(f"SEG_OK sid={sid} seq={seq} bytes={len(data)} ms={ms} try={attempt}", xbmc.LOGWARNING, source=source)
            else:
                _s14_log(f"SEG_OK sid={sid} seq={seq} bytes={len(data)} ms={ms}", source=source)
            self.send_response(200)
            self.send_header("Content-Type", "video/mp2t")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        _s14_log(f"SEG_GIVEUP sid={sid} seq={seq} url={seg_url} err={last_err}", xbmc.LOGERROR, source=source)
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

        if path_base == '/s14_seg':
            self._handle_s14_segment(params)
            return

        code = params.get('code')
        source_type = params.get('source')
        
        if not code or not source_type:
            self.send_response(400)
            self.end_headers()
            return

        # ─── GESTIONE SPECIALE SERVER HLS (S14 / S17) ───
        if source_type in HLS_SERVERS:
            sid = code
            sess_key = f"{source_type}:{sid}"
            now = time.time()

            with S14_LOCK:
                sess = S14_SESSION_CACHE.get(sess_key)
                if sess:
                    sess['last_seen'] = now

            # Se abbiamo già un manifest in cache, invialo SUBITO a Kodi (< 1ms)
            if sess and sess.get('last_body'):
                # Assicurati che il worker thread sia attivo
                with S14_LOCK:
                    if sess_key not in S14_WORKERS or not S14_WORKERS[sess_key].is_alive():
                        wid = sess.get('worker_id')
                        t = threading.Thread(target=_s14_worker_loop, args=(sess_key, wid), daemon=True)
                        S14_WORKERS[sess_key] = t
                        t.start()

                self.send_response(200)
                self.send_header("Content-Type", "application/x-mpegURL")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                _s14_log(f"M3U8_SERVED sid={sid} media={sess.get('media_seq')} max={sess.get('max_seq')}", source=source_type)
                self.wfile.write(sess['last_body'].encode('utf-8'))
                return

            # Primo avvio del canale: fetch iniziale sincrono
            new_segs, pinned_host, info = _s14_fetch_manifest(sid, pinned_host=None, source=source_type)
            _s14_log(f"avvio sid={sid} host={pinned_host} {info}", source=source_type)
            if new_segs:
                with S14_LOCK:
                    wid = now
                    sess = {
                        'sid': sid,
                        'source': source_type,
                        'worker_id': wid,
                        'pinned_host': pinned_host,
                        'segments': {seq: (inf, url) for seq, inf, url in new_segs},
                        'last_seen': now,
                        'media_seq': 0,
                        'seq_offset': 0,
                        'disc_seqs': set(),
                        'last_new_ts': now,
                        'last_loc': getattr(_s14_fetch_manifest, 'last_loc', None),
                        'direct_loc': getattr(_s14_fetch_manifest, 'last_loc', None),
                        'direct_since': now
                    }
                    body = _s14_render_playlist(sess, window_size=6)
                    sess['startup_done'] = True
                    S14_SESSION_CACHE[sess_key] = sess

                    t = threading.Thread(target=_s14_worker_loop, args=(sess_key, wid), daemon=True)
                    S14_WORKERS[sess_key] = t
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
        with S14_LOCK:
            S14_SESSION_CACHE.clear()
            S14_WORKERS.clear()
        _close_s14_seg_session()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            xbmc.log("[CBTV Proxy] Server arrestato", xbmc.LOGINFO)
