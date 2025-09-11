"""xhamster Downloader"""
import os
import sys
import shutil
import subprocess
from urllib.parse import urlparse, urljoin
from requests import Session
from bs4 import BeautifulSoup
import m3u8
from tqdm import tqdm
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import requests
from requests.adapters import HTTPAdapter

# How To Use
# 1. Open terminal/powershell/cmd
# 2. python src/downloder.py "url"


DEFAULT_SAVE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'downloads')
DATALINK_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'datalink.txt')
LODED_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'loded.txt')
MAX_CONCURRENCY = 10
PREFERRED_QUALITY = '480p'


def ensure_dir(directory: str) -> None:
	if not os.path.exists(directory):
		os.makedirs(directory, exist_ok=True)


def normalize_xhamster_url(url: str) -> str:
	"""Ensure URL has scheme and a valid xHamster host. Raise ValueError if invalid."""
	if not url:
		raise ValueError('Empty URL')
	u = url.strip()
	if not re.match(r'^https?://', u, re.I):
		u = 'https://' + u
	p = urlparse(u)
	if not p.netloc:
		raise ValueError('URL missing host')
	# Accept common xHamster domains
	if 'xhamster' not in p.netloc.lower():
		raise ValueError(f'URL host looks invalid for xHamster: {p.netloc}')
	return u


def get_title(soup, quality):
	"""Video Name"""
	title_tag = soup.find('main').find('h1') if soup.find('main') else None
	title_ = (title_tag.text if title_tag else 'xhamster_video').strip()
	video_name_ = f'{title_} {quality}.mp4'
	return video_name_


def require_ffmpeg() -> None:
	if shutil.which('ffmpeg') is None:
		print('ffmpeg is required for proper HLS download and muxing.')
		print('Install on Windows: choco install ffmpeg (or add ffmpeg to PATH).')
		sys.exit(3)


def _compute_total_duration_seconds(playlist_obj: m3u8.M3U8) -> float:
	try:
		segments = playlist_obj.segments or []
		if segments:
			return float(sum(getattr(seg, 'duration', 0.0) for seg in segments))
		return float(sum(seg.get('duration', 0.0) for seg in playlist_obj.data.get('segments', [])))
	except Exception:
		return 0.0


def _ffmpeg_base_cmd() -> list[str]:
	# Tuned ffmpeg input options for better stability and potential throughput
	return [
		'ffmpeg', '-y', '-hide_banner', '-stats',
		# HTTP reconnect options
		'-reconnect', '1', '-reconnect_at_eof', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
		# Keep connections alive
		'-http_persistent', '1',
		# Allow relevant protocols
		'-allowed_extensions', 'ALL',
		'-protocol_whitelist', 'file,http,https,tcp,tls',
	]


def ffmpeg_hls_download_with_progress(referer: str, video_playlist_url: str, out_path: str, total_duration_s: float, audio_playlist_url: str | None = None) -> bool:
	"""Use ffmpeg to fetch HLS and remux to MP4 (copy) showing progress by parsing stderr time= and speed= lines."""
	headers = f"Referer: {referer}\r\nUser-Agent: Mozilla/5.0\r\nConnection: keep-alive"
	cmd = _ffmpeg_base_cmd() + [
		'-headers', headers,
		'-referer', referer,
		'-user_agent', 'Mozilla/5.0',
		'-i', video_playlist_url,
	]
	if audio_playlist_url:
		cmd += ['-headers', headers, '-referer', referer, '-user_agent', 'Mozilla/5.0', '-i', audio_playlist_url, '-map', '0:v:0', '-map', '1:a:0']
	cmd += ['-c', 'copy', out_path]
	try:
		with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1) as proc:
			total = max(1, int(total_duration_s)) if total_duration_s > 0 else None
			bar = tqdm(total=total, desc='Downloading', unit='s') if total else tqdm(desc='Downloading')
			last_sec = 0
			time_re = re.compile(r'time=(\d+):(\d+):(\d+\.\d+)')
			speed_re = re.compile(r'speed=([\d\.x]+)')
			while True:
				line = proc.stderr.readline()
				if not line:
					if proc.poll() is not None:
						break
					continue
				line = line.strip()
				m = time_re.search(line)
				if m:
					hh, mm, ss = int(m.group(1)), int(m.group(2)), float(m.group(3))
					sec = int(hh * 3600 + mm * 60 + ss)
					if total:
						if sec > last_sec:
							bar.update(min(sec - last_sec, bar.total - bar.n))
							last_sec = sec
					else:
						bar.set_postfix_str(f"time {sec}s")
				ms = re.search(r'speed=([^\s]+)', line)
				if ms:
					bar.set_postfix(speed=ms.group(1))
			bar.close()
			proc.wait()
			return proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0
	except Exception:
		return False


def _parallel_download_ts_and_concat(session: Session, referer: str, playlist_obj: m3u8.M3U8, playlist_url: str, out_path: str, workers: int = 16) -> bool:
	"""Fast path for TS playlists: download segments concurrently and concat with ffmpeg."""
	headers = {"Referer": referer, "User-Agent": 'Mozilla/5.0', "Connection": "keep-alive"}
	segments = playlist_obj.segments or []
	uris = [seg.uri for seg in segments] if segments else [seg['uri'] for seg in playlist_obj.data.get('segments', [])]
	if not uris:
		return False
	base = playlist_url.rsplit('/', 1)[0]
	with tempfile.TemporaryDirectory() as tmpdir:
		def fetch(idx_uri):
			idx, uri = idx_uri
			url = uri if str(uri).lower().startswith('http') else f"{base}/{uri}"
			r = session.get(url, headers=headers, stream=True, timeout=60)
			r.raise_for_status()
			p = os.path.join(tmpdir, f"seg_{idx:06d}.ts")
			with open(p, 'wb') as f:
				for chunk in r.iter_content(chunk_size=1024*1024):
					if chunk:
						f.write(chunk)
			return p
		futures = []
		with ThreadPoolExecutor(max_workers=workers) as ex:
			for i, uri in enumerate(uris):
				futures.append(ex.submit(fetch, (i, uri)))
			bar = tqdm(total=len(futures), desc=f'Downloading (x{workers})')
			paths = [None] * len(futures)
			for fut in as_completed(futures):
				p = fut.result()
				idx = int(os.path.basename(p).split('_')[1].split('.')[0])
				paths[idx] = p
				bar.update(1)
			bar.close()
		list_file = os.path.join(tmpdir, 'list.txt')
		with open(list_file, 'w', encoding='utf-8') as f:
			for p in paths:
				f.write(f"file '{p.replace('\\', '/')}'\n")
		cmd = ['ffmpeg', '-y', '-hide_banner', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', list_file, '-c', 'copy', out_path]
		proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
		return proc.returncode == 0 and os.path.exists(out_path) and os.path.getsize(out_path) > 0


def _find_master_playlist_url(session: Session, page_url: str, soup: BeautifulSoup) -> str:
	# Strategy 1: <link rel="preload" ...>
	preloads = soup.find_all('link', attrs={'rel': 'preload'})
	for link in preloads:
		href = link.get('href')
		if href and '.m3u8' in href:
			return href if href.lower().startswith('http') else urljoin(page_url, href)
	# Strategy 2: OpenGraph or meta tags
	for prop in ('og:video', 'og:video:url', 'twitter:player:stream'):
		meta = soup.find('meta', attrs={'property': prop}) or soup.find('meta', attrs={'name': prop})
		if meta and meta.get('content') and '.m3u8' in meta['content']:
			href = meta['content']
			return href if href.lower().startswith('http') else urljoin(page_url, href)
	# Strategy 3: Regex scan of HTML for any m3u8
	html = str(soup)
	for m in re.finditer(r'https?://[^"\s]+?\.m3u8[^"\s]*', html):
		return m.group(0)
	# Strategy 4: relative m3u8
	m = re.search(r'"([^"]+?\.m3u8[^"]*)"', html)
	if m:
		return urljoin(page_url, m.group(1))
	raise RuntimeError('Could not find any m3u8 master/media URL on the page')


def _label_from_playlist(pl) -> str:
	# Try to derive a human label like 480p
	try:
		info = getattr(pl, 'stream_info', None)
		if info and getattr(info, 'resolution', None):
			w, h = info.resolution
			return f"{h}p"
	except Exception:
		pass
	# Fallback from URI
	uri = getattr(pl, 'uri', '') or ''
	m = re.search(r'([0-9]{3,4})p', uri)
	if m:
		return f"{m.group(1)}p"
	m = re.search(r'([0-9]{3,4})(?=\D|$)', uri)
	return f"{m.group(1)}p" if m else (uri or 'unknown')


def _is_video_playlist(pl) -> bool:
	"""Heuristic: has resolution or codecs with avc1/h264 => video. Some audio playlists are AAC only."""
	try:
		info = getattr(pl, 'stream_info', None)
		if info and getattr(info, 'resolution', None):
			return True
		codecs = getattr(info, 'codecs', '') if info else ''
		if isinstance(codecs, str) and ('avc1' in codecs or 'h264' in codecs or 'hev1' in codecs or 'hvc1' in codecs or 'av01' in codecs):
			return True
	except Exception:
		pass
	return False


def _find_audio_playlist_uri(master: m3u8.M3U8, video_playlist: m3u8.Playlist) -> str | None:
	try:
		ainfo = getattr(video_playlist, 'stream_info', None)
		group_id = getattr(ainfo, 'audio', None) if ainfo else None
		if not group_id:
			return None
		for m in getattr(master, 'media', []) or []:
			if getattr(m, 'type', '').upper() == 'AUDIO' and getattr(m, 'group_id', None) == group_id and getattr(m, 'uri', None):
				return m.uri
	except Exception:
		return None
	return None


def _pick_preferred_index(labels: list[str], preferred: str = PREFERRED_QUALITY) -> int:
	for i, q in enumerate(labels):
		if q == preferred:
			return i
	for i, q in enumerate(labels):
		if '480' in q:
			return i
	return max(0, (len(labels)//2) - 1)


def _ordered_variant_indices(video_playlists: list, labels: list[str]) -> list[int]:
	"""Return variant indices ordered by preference: prefer avc1, then others; within each, try 480p first, then nearby qualities."""
	avc_indices = []
	other_indices = []
	for i, pl in enumerate(video_playlists):
		codecs = ''
		try:
			codecs = (pl.stream_info.codecs or '').lower()
		except Exception:
			codecs = ''
		if 'avc1' in codecs or 'h264' in codecs:
			avc_indices.append(i)
		else:
			other_indices.append(i)
	# order by closeness to 480
	def score(idx: int) -> int:
		label = labels[idx]
		m = re.search(r'(\d{3,4})', label)
		if m:
			val = int(m.group(1))
			return abs(val - 480)
		return 9999
	avc_indices.sort(key=score)
	other_indices.sort(key=score)
	return avc_indices + other_indices


def xhamster(xhamster_url: str, save_dir: str = DEFAULT_SAVE_DIR):
	"""xhamster"""
	require_ffmpeg()
	try:
		xhamster_url = normalize_xhamster_url(xhamster_url)
	except ValueError as e:
		print(f"Invalid URL: {e}")
		print('Example: https://xhamster.com/videos/...')
		sys.exit(2)

	session = Session()
	# Larger HTTP connection pool for faster parallel segment fetching
	adapter = HTTPAdapter(pool_connections=64, pool_maxsize=64)
	session.mount('http://', adapter)
	session.mount('https://', adapter)
	session.headers.update({
		'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
		'Accept-Language': 'en-US,en;q=0.9',
		'Connection': 'keep-alive',
	})
	try:
		r = session.get(xhamster_url, headers={"Referer": xhamster_url}, timeout=30)
		r.raise_for_status()
	except requests.exceptions.RequestException as e:
		print(f"Failed to open page: {e}")
		print('Check the URL and your internet connection.')
		sys.exit(2)

	soup = BeautifulSoup(r.content, 'html.parser')

	master_url = _find_master_playlist_url(session, xhamster_url, soup)
	master_url = master_url if master_url.lower().startswith('http') else urljoin(xhamster_url, master_url)
	r = session.get(master_url, headers={"Referer": xhamster_url}, timeout=30)
	r.raise_for_status()
	main_playlist = m3u8.loads(r.text)

	# If it's a master playlist with variants
	playlists = getattr(main_playlist, 'playlists', None) or []
	if playlists:
		video_playlists = [pl for pl in playlists if _is_video_playlist(pl)] or playlists
		m3u8_quality_uris = [pl.uri for pl in video_playlists]
		quality_labels = [_label_from_playlist(pl) for pl in video_playlists]
		# Build an ordered list of variant indices (prefer avc1/h264 and closest to 480p)
		ordered = _ordered_variant_indices(video_playlists, quality_labels)
		last_err = None
		for idx in ordered:
			video_pl = video_playlists[idx]
			playlist_uri = m3u8_quality_uris[idx]
			res_url = playlist_uri if playlist_uri.lower().startswith('http') else f'{master_url.rsplit('/', 1)[0]}/{playlist_uri}'
			# Try to pre-fetch variant with robust headers to enable fast parallel TS path; if 403, skip to ffmpeg
			playlist_obj = None
			try:
				robust_headers = {
					"Referer": xhamster_url,
					"Origin": f"{urlparse(xhamster_url).scheme}://{urlparse(xhamster_url).netloc}",
					"User-Agent": session.headers.get('User-Agent', ''),
					"Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,application/octet-stream,*/*",
					"Connection": "keep-alive",
				}
				r = session.get(res_url, headers=robust_headers, timeout=30)
				r.raise_for_status()
				playlist_obj = m3u8.loads(r.text)
			except Exception:
				playlist_obj = None

			# Find matching audio playlist (if separate)
			audio_uri_rel = _find_audio_playlist_uri(main_playlist, video_pl)
			audio_url = None
			if audio_uri_rel:
				audio_url = audio_uri_rel if str(audio_uri_rel).lower().startswith('http') else f'{master_url.rsplit('/', 1)[0]}/{audio_uri_rel}'

			v_quality = quality_labels[idx]
			video_name = get_title(soup, v_quality)
			# Duration unknown if we couldn't prefetch variant
			total_duration = _compute_total_duration_seconds(playlist_obj) if playlist_obj else 0

			# If we have a TS-only playlist and no separate audio, use fast parallel path
			fast_done = False
			if playlist_obj and not audio_url:
				first_seg_uri = None
				try:
					first_seg_uri = playlist_obj.segments[0].uri if playlist_obj.segments else None
				except Exception:
					first_seg_uri = None
				if first_seg_uri and str(first_seg_uri).lower().endswith('.ts'):
					out_path = os.path.join(save_dir, video_name)
					fast_done = _parallel_download_ts_and_concat(session, xhamster_url, playlist_obj, res_url, out_path, workers=16)
			# Otherwise or if fast path failed, use ffmpeg
			if not fast_done:
				ok = ffmpeg_hls_download_with_progress(xhamster_url, res_url, os.path.join(save_dir, video_name), total_duration, audio_playlist_url=audio_url)
				if ok:
					return
				else:
					last_err = 'ffmpeg failed'
		# If none worked
		if last_err:
			raise RuntimeError('ffmpeg failed to produce a playable file.')
		return

	# Else: treat as media playlist directly (no variants)
	v_quality = 'HLS'
	video_name = get_title(soup, v_quality)
	total_duration = _compute_total_duration_seconds(main_playlist)
	ok = ffmpeg_hls_download_with_progress(xhamster_url, master_url, os.path.join(save_dir, video_name), total_duration)
	if not ok:
		raise RuntimeError('ffmpeg failed to produce a playable file.')


def _read_datalink_lines(path: str = DATALINK_FILE) -> list[str]:
	if not os.path.exists(path):
		return []
	urls = []
	with open(path, 'r', encoding='utf-8') as f:
		for line in f:
			line = line.strip()
			if not line:
				continue
			url = line.split('\t')[0]
			urls.append(url)
	return urls


def _read_loded_set(path: str = LODED_FILE) -> set[str]:
	seen = set()
	if not os.path.exists(path):
		return seen
	with open(path, 'r', encoding='utf-8') as f:
		for line in f:
			u = line.strip()
			if u:
				seen.add(u)
	return seen


def _append_loded(url: str, path: str = LODED_FILE) -> None:
	with open(path, 'a', encoding='utf-8') as f:
		f.write(url + '\n')


def batch_download():
	ensure_dir(DEFAULT_SAVE_DIR)
	require_ffmpeg()
	all_urls = _read_datalink_lines(DATALINK_FILE)
	if not all_urls:
		print('No URLs in datalink.txt')
		return
	seen = _read_loded_set(LODED_FILE)
	to_fetch = [u for u in all_urls if u not in seen]
	if not to_fetch:
		print('All URLs already downloaded (per loded.txt)')
		return
	# Only first 10, process serially one-by-one
	subset = to_fetch[:MAX_CONCURRENCY]
	for i, u in enumerate(subset, 1):
		try:
			print(f"[{i}/{len(subset)}] Downloading: {u}")
			xhamster(u, DEFAULT_SAVE_DIR)
			_append_loded(u)
		except Exception as e:
			print('Error downloading', u, ':', e)


if __name__ == '__main__':
	if len(sys.argv) > 1:
		try:
			URL = sys.argv[1]
			xhamster(URL)
		except Exception as e:
			print('Error:', e)
	else:
		batch_download() 