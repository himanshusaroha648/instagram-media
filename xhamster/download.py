"""High-speed xHamster downloader (3–5 MB/s target)
Usage:
        python xhamster/download.py "https://xhamster.com/videos/..."
"""
import os
import sys
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from bs4 import BeautifulSoup
import m3u8
from tqdm import tqdm

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'downloads')
TS_WORKERS = int(os.getenv('XH_TS_WORKERS', '32'))
_LOG_LOCK = None


def now_host(url: str) -> str:
        p = urlparse(url)
        return f"{p.scheme}://{p.netloc}"


def ensure_dir(d: str) -> None:
        if not os.path.exists(d):
                os.makedirs(d, exist_ok=True)


def _get_log_lock():
        # Lazy import threading only when needed to keep load minimal
        global _LOG_LOCK
        if _LOG_LOCK is None:
                import threading
                _LOG_LOCK = threading.Lock()
        return _LOG_LOCK


def log_loaded(url: str, out_path: str) -> None:
        """Append only the URL to loded.txt (no file path)."""
        root = os.path.dirname(os.path.dirname(__file__))
        log_path = os.path.join(root, 'loded.txt')
        line = f"{url}\n"
        lock = _get_log_lock()
        with lock:
                with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(line)


def log_failed(url: str, error_msg: str) -> None:
        """Append only the URL to loded.txt for failed downloads as well."""
        root = os.path.dirname(os.path.dirname(__file__))
        log_path = os.path.join(root, 'loded.txt')
        line = f"{url}\n"
        lock = _get_log_lock()
        with lock:
                with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(line)


def normalize_url(u: str) -> str:
        u = u.strip()
        if not re.match(r'^https?://', u, re.I):
                u = 'https://' + u
        p = urlparse(u)
        if not p.netloc or 'xhamster' not in p.netloc.lower():
                raise ValueError('Invalid xHamster URL')
        return u


def have_ffmpeg() -> bool:
        return shutil.which('ffmpeg') is not None


def title_from_soup(soup: BeautifulSoup) -> str:
        t = soup.find('main').find('h1') if soup.find('main') else None
        return (t.text if t else 'xhamster_video').strip()


def ffmpeg_base_cmd() -> list:
        return [
                'ffmpeg', '-y', '-hide_banner', '-stats',
                '-reconnect', '1', '-reconnect_at_eof', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
                '-http_persistent', '1',
                '-allowed_extensions', 'ALL',
                '-protocol_whitelist', 'file,http,https,tcp,tls',
        ]


def ffmpeg_copy(referer: str, video_playlist_url: str, audio_playlist_url: str | None, out_path: str) -> bool:
        headers = f"Referer: {referer}\r\nUser-Agent: Mozilla/5.0\r\nConnection: keep-alive"
        cmd = ffmpeg_base_cmd() + ['-headers', headers, '-i', video_playlist_url]
        if audio_playlist_url:
                cmd += ['-headers', headers, '-i', audio_playlist_url, '-map', '0:v:0', '-map', '1:a:0']
        cmd += ['-c', 'copy', out_path]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0


def fetch_master(session: requests.Session, page_url: str, soup: BeautifulSoup) -> str:
        # 1) <link rel="preload"> 2) meta 3) regex
        for link in soup.find_all('link', attrs={'rel': 'preload'}):
                h = link.get('href')
                if h and '.m3u8' in h:
                        return h if h.startswith('http') else urljoin(page_url, h)
        for prop in ('og:video', 'og:video:url', 'twitter:player:stream'):
                m = soup.find('meta', attrs={'property': prop}) or soup.find('meta', attrs={'name': prop})
                if m and m.get('content') and '.m3u8' in m['content']:
                        return m['content'] if m['content'].startswith('http') else urljoin(page_url, m['content'])
        html = str(soup)
        mm = re.search(r'https?://[^"\s]+?\.m3u8[^"\s]*', html)
        if mm:
                return mm.group(0)
        mm = re.search(r'"([^"\s]+?\.m3u8[^"\s]*)"', html)
        if mm:
                return urljoin(page_url, mm.group(1))
        raise RuntimeError('Master playlist not found')


def is_video_playlist(pl) -> bool:
        try:
                info = getattr(pl, 'stream_info', None)
                if info and getattr(info, 'resolution', None):
                        return True
                codecs = getattr(info, 'codecs', '') if info else ''
                return isinstance(codecs, str) and ('avc1' in codecs or 'h264' in codecs)
        except Exception:
                return False


def label_for(pl) -> str:
        try:
                info = getattr(pl, 'stream_info', None)
                if info and getattr(info, 'resolution', None):
                        return f"{info.resolution[1]}p"
        except Exception:
                pass
        u = getattr(pl, 'uri', '') or ''
        m = re.search(r'([0-9]{3,4})p', u)
        if m:
                return f"{m.group(1)}p"
        m = re.search(r'([0-9]{3,4})(?=\D|$)', u)
        return f"{m.group(1)}p" if m else (u or 'unknown')


def find_audio_uri(master: m3u8.M3U8, video_pl) -> str | None:
        try:
                ainfo = getattr(video_pl, 'stream_info', None)
                gid = getattr(ainfo, 'audio', None) if ainfo else None
                if not gid:
                        return None
                for m in getattr(master, 'media', []) or []:
                        if getattr(m, 'type', '').upper() == 'AUDIO' and getattr(m, 'group_id', None) == gid and getattr(m, 'uri', None):
                                return m.uri
        except Exception:
                return None
        return None


def parallel_ts_download_and_concat(session: requests.Session, referer: str, variant_url: str, playlist_obj: m3u8.M3U8, out_path: str, workers: int | None = None) -> bool:
        if not workers:
                workers = TS_WORKERS
        headers = {"Referer": referer, "User-Agent": 'Mozilla/5.0', "Connection": "keep-alive"}
        segs = playlist_obj.segments or []
        uris = [s.uri for s in segs] if segs else [s['uri'] for s in playlist_obj.data.get('segments', [])]
        if not uris:
                return False
        base = variant_url.rsplit('/', 1)[0]
        with tempfile.TemporaryDirectory() as tmpdir:
                def fetch(idx_uri):
                        idx, uri = idx_uri
                        url = uri if str(uri).lower().startswith('http') else f"{base}/{uri}"
                        r = session.get(url, headers=headers, stream=True, timeout=60)
                        r.raise_for_status()
                        p = os.path.join(tmpdir, f"seg_{idx:06d}.ts")
                        with open(p, 'wb') as f:
                                for chunk in r.iter_content(chunk_size=1024*256):
                                        if chunk:
                                                f.write(chunk)
                        return p
                futs = []
                with ThreadPoolExecutor(max_workers=workers) as ex:
                        for i, uri in enumerate(uris):
                                futs.append(ex.submit(fetch, (i, uri)))
                        bar = tqdm(total=len(futs), desc=f'Downloading (x{workers})')
                        paths = [None] * len(futs)
                        for fut in as_completed(futs):
                                p = fut.result()
                                idx = int(os.path.basename(p).split('_')[1].split('.')[0])
                                paths[idx] = p
                                bar.update(1)
                        bar.close()
                # concat
                lst = os.path.join(tmpdir, 'list.txt')
                with open(lst, 'w', encoding='utf-8') as f:
                        for p in paths:
                                normalized_path = p.replace('\\', '/')
                                f.write(f"file '{normalized_path}'\n")
                cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', lst, '-c', 'copy', out_path]
                proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                return proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0


def _playlist_height(pl) -> int:
        try:
                info = getattr(pl, 'stream_info', None)
                if info and getattr(info, 'resolution', None):
                        return int(info.resolution[1])
        except Exception:
                pass
        try:
                u = getattr(pl, 'uri', '') or ''
                m = re.search(r'([0-9]{3,4})p', u)
                if m:
                        return int(m.group(1))
                m = re.search(r'([0-9]{3,4})(?=\D|$)', u)
                return int(m.group(1)) if m else 0
        except Exception:
                return 0


def download(url: str, out_dir: str = DEFAULT_OUT):
        # Validate and setup
        url = normalize_url(url)
        ensure_dir(out_dir)
        if not have_ffmpeg():
                raise RuntimeError('ffmpeg is required (install and add to PATH).')

        s = requests.Session()
        s.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                'Accept-Language': 'en-US,en;q=0.9',
                'Connection': 'keep-alive',
        })

        # Load page
        r = s.get(url, headers={'Referer': url}, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.content, 'html.parser')
        title = title_from_soup(soup)

        # Find master
        m3u8_master = fetch_master(s, url, soup)
        rm = s.get(m3u8_master, headers={'Referer': url}, timeout=30)
        rm.raise_for_status()
        master = m3u8.loads(rm.text)
        pls = getattr(master, 'playlists', None) or []
        video_pls = [pl for pl in pls if is_video_playlist(pl)] or pls
        if not video_pls:
                raise RuntimeError('No video variants found')

        # Select 480p only; skip if not available
        preferred = None
        for pl in video_pls:
                try:
                        h = _playlist_height(pl)
                        if h == 480:
                                preferred = pl
                                break
                except Exception:
                        continue
        # fallback: label text contains '480'
        if preferred is None:
                for pl in video_pls:
                        try:
                                if '480' in (label_for(pl) or ''):
                                        preferred = pl
                                        break
                        except Exception:
                                continue
        if preferred is None:
                raise RuntimeError('480p not available for this video')

        best_pl = preferred
        best_label = label_for(best_pl)
        variant_rel = best_pl.uri
        variant_url = variant_rel if variant_rel.startswith('http') else f"{m3u8_master.rsplit('/', 1)[0]}/{variant_rel}"
        audio_rel = find_audio_uri(master, best_pl)
        audio_url = audio_rel if (audio_rel and audio_rel.startswith('http')) else (f"{m3u8_master.rsplit('/', 1)[0]}/{audio_rel}" if audio_rel else None)

        outfile = os.path.join(out_dir, f"{title} {best_label}.mp4")

        # Try to prefetch variant to enable parallel TS fast path
        variant_obj = None
        try:
                headers = {
                        'Referer': url,
                        'Origin': now_host(url),
                        'User-Agent': s.headers['User-Agent'],
                        'Accept': 'application/vnd.apple.mpegurl,application/x-mpegURL,application/octet-stream,*/*',
                        'Connection': 'keep-alive'
                }
                rv = s.get(variant_url, headers=headers, timeout=30)
                rv.raise_for_status()
                variant_obj = m3u8.loads(rv.text)
        except Exception:
                variant_obj = None

        # Fast TS path
        if variant_obj and not audio_url:
                first = None
                try:
                        first = variant_obj.segments[0].uri if variant_obj.segments else None
                except Exception:
                        first = None
                if first and str(first).lower().endswith('.ts'):
                        ok = parallel_ts_download_and_concat(s, url, variant_url, variant_obj, outfile, workers=TS_WORKERS)
                        if ok:
                                print('✅ Done (parallel TS)')
                                try:
                                        log_loaded(url, outfile)
                                except Exception:
                                        pass
                                return outfile

        # Fallback to ffmpeg copy (handles fMP4 and separate audio)
        ok = ffmpeg_copy(url, variant_url, audio_url, outfile)
        if not ok:
                raise RuntimeError('ffmpeg failed to download stream')
        print('✅ Done (ffmpeg)')
        try:
                log_loaded(url, outfile)
        except Exception:
                pass
        return outfile


def _read_urls_from_file(path: str) -> list[str]:
        urls = []
        try:
                with open(path, 'r', encoding='utf-8') as f:
                        for line in f:
                                line = line.strip()
                                if not line:
                                        continue
                                # take first token before whitespace/tab
                                url = line.split()[0]
                                try:
                                        urls.append(normalize_url(url))
                                except Exception:
                                        pass
        except FileNotFoundError:
                return []
        # de-duplicate while preserving order
        seen = set()
        uniq = []
        for u in urls:
                if u in seen:
                        continue
                seen.add(u)
                uniq.append(u)
        return uniq


def _read_logged_url_set(log_path: str) -> set[str]:
        logged = set()
        try:
                with open(log_path, 'r', encoding='utf-8') as f:
                        for line in f:
                                line = line.strip()
                                if not line:
                                        continue
                                u = line.split()[0]
                                try:
                                        logged.add(normalize_url(u))
                                except Exception:
                                        pass
        except FileNotFoundError:
                return set()
        return logged


def download_batch_from_datalink(max_concurrent: int = 5, limit: int = 10, out_dir: str = DEFAULT_OUT) -> list[tuple[str, str | None, str | None]]:
        """Return list of (url, outfile, error)."""
        ensure_dir(out_dir)
        root = os.path.dirname(os.path.dirname(__file__))
        link_file = os.path.join(root, 'datalink.txt')
        log_file = os.path.join(root, 'loded.txt')
        logged = _read_logged_url_set(log_file)
        all_urls = _read_urls_from_file(link_file)
        urls = [u for u in all_urls if u not in logged][:limit]
        results = []
        if not urls:
                print('No URLs found in datalink.txt')
                return results
        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=max_concurrent) as ex:
                future_to_url = {ex.submit(download, u, out_dir): u for u in urls}
                for fut in as_completed(future_to_url):
                        u = future_to_url[fut]
                        try:
                                out = fut.result()
                                print('Saved:', out)
                                results.append((u, out, None))
                        except Exception as e:
                                print('Error:', u, e)
                                results.append((u, None, str(e)))
                                try:
                                        log_failed(u, str(e))
                                except Exception:
                                        pass
        return results


if __name__ == '__main__':
        try:
                if len(sys.argv) >= 2 and sys.argv[1].strip():
                        in_url = sys.argv[1]
                        # Skip if already logged
                        root = os.path.dirname(os.path.dirname(__file__))
                        log_file = os.path.join(root, 'loded.txt')
                        logged = _read_logged_url_set(log_file)
                        if normalize_url(in_url) in logged:
                                print('Skipping: already logged in loded.txt')
                        else:
                                out = download(in_url)
                                print('Saved:', out)
                else:
                        # Default: read from datalink.txt, 5 at a time, stop after 10
                        download_batch_from_datalink(max_concurrent=5, limit=10, out_dir=DEFAULT_OUT)
        except Exception as e:
                # Log single-URL failures as well
                try:
                        if len(sys.argv) >= 2 and sys.argv[1].strip():
                                log_failed(sys.argv[1], str(e))
                except Exception:
                        pass
                print('Error:', e)
                sys.exit(2)
