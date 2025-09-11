import os
import re
import sys
import time
import random
from urllib.parse import urljoin, urlparse, urlencode, parse_qs

import requests
from bs4 import BeautifulSoup

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'datalink.txt')
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'
TARGET_COUNT = 500  # total unique links desired in datalink.txt (unused in quick mode)
BATCH_LIMIT = 200   # add at most this many new links per cycle (unused in quick mode)
REFRESH_DELAY = 20  # seconds between refresh attempts
MAX_RETRIES = 50    # max refresh attempts before stopping
RANDOM_PICK_COUNT = 7


def normalize_url(u: str) -> str:
	u = u.strip()
	if not re.match(r'^https?://', u, re.I):
		u = 'https://' + u
	p = urlparse(u)
	if not p.netloc or 'xhamster' not in p.netloc.lower():
		raise ValueError('Invalid xHamster URL')
	return u


def parse_duration_to_seconds(text: str) -> int | None:
	"""Parse duration like '12:34' or '1:23:45' to seconds."""
	text = (text or '').strip()
	m = re.search(r'(\d{1,2}:\d{2}:\d{2}|\d{1,2}:\d{2})', text)
	if not m:
		return None
	parts = m.group(1).split(':')
	if len(parts) == 3:
		h, m_, s = parts
		return int(h) * 3600 + int(m_) * 60 + int(s)
	else:
		m_, s = parts
		return int(m_) * 60 + int(s)


def extract_cards(soup: BeautifulSoup, base_url: str) -> list[tuple[str, int]]:
	"""Return list of (video_url, duration_seconds)."""
	results: list[tuple[str, int]] = []
	for a in soup.select('a[href*="/videos/"]'):
		href = a.get('href')
		if not href:
			continue
		url = href if href.startswith('http') else urljoin(base_url, href)
		if '/videos/' not in url:
			continue
		dur_text = None
		time_el = a.find('time')
		if time_el and time_el.text:
			dur_text = time_el.text
		if not dur_text:
			span = a.find('span', string=re.compile(r'\d{1,2}:\d{2}(?::\d{2})?'))
			if span:
				dur_text = span.text
		if not dur_text and a.parent:
			cand = a.parent.get_text(" ", strip=True)
			m = re.search(r'\b\d{1,2}:\d{2}(?::\d{2})?\b', cand or '')
			if m:
				dur_text = m.group(0)
		dur_sec = parse_duration_to_seconds(dur_text or '')
		if dur_sec is None:
			continue
		results.append((url, dur_sec))
	uniq: dict[str, int] = {}
	for u, s in results:
		if u not in uniq or s < uniq[u]:
			uniq[u] = s
	return [(u, uniq[u]) for u in uniq]


def fetch_listing(url: str, timeout: int = 30) -> BeautifulSoup:
	s = requests.Session()
	s.headers.update({'User-Agent': USER_AGENT, 'Accept-Language': 'en-US,en;q=0.9'})
	# cache-bust param to avoid CDN caching identical HTML
	parsed = urlparse(url)
	qs = parse_qs(parsed.query)
	qs['_ts'] = [str(int(time.time()))]
	new_query = urlencode({k: v[0] if isinstance(v, list) and v else v for k, v in qs.items()})
	rebuilt = parsed._replace(query=new_query).geturl()
	r = s.get(rebuilt, headers={'Referer': url}, timeout=timeout)
	r.raise_for_status()
	return BeautifulSoup(r.content, 'html.parser')


def load_existing() -> dict[str, str]:
	"""Load existing URL -> mm:ss mapping from OUTPUT_FILE if exists."""
	mapping: dict[str, str] = {}
	if not os.path.exists(OUTPUT_FILE):
		return mapping
	with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
		for line in f:
			line = line.strip()
			if not line:
				continue
			parts = line.split('\t')
			if len(parts) >= 2:
				mapping[parts[0]] = parts[1]
	return mapping


def read_existing_urls() -> list[str]:
	urls: list[str] = []
	if not os.path.exists(OUTPUT_FILE):
		return urls
	with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
		for line in f:
			line = line.strip()
			if not line:
				continue
			url = line.split('\t')[0]
			urls.append(url)
	return urls


def write_new_under_15(candidates: list[tuple[str, int]], batch_limit: int, target_total: int) -> int:
	"""Append up to batch_limit new <15 min unique links to OUTPUT_FILE, without exceeding target_total total unique links. Returns number written."""
	existing = load_existing()
	current_total = len(existing)
	room = max(0, target_total - current_total)
	if room == 0:
		return 0
	limit = min(batch_limit, room)
	new_lines: list[str] = []
	added = 0
	for (u, s) in candidates:
		if s >= 15 * 60:
			continue
		if u in existing:
			continue
		mm = s // 60
		ss = s % 60
		new_lines.append(f"{u}\t{mm:02d}:{ss:02d}\n")
		existing[u] = f"{mm:02d}:{ss:02d}"
		added += 1
		if added >= limit:
			break
	if added > 0:
		with open(OUTPUT_FILE, 'a', encoding='utf-8') as f:
			for line in new_lines:
				f.write(line)
	return added


def interactive_pick(candidates: list[tuple[str, int]]) -> str | None:
	print('Found videos:')
	for i, (u, s) in enumerate(candidates, 1):
		mm = s // 60
		ss = s % 60
		print(f"{i}. {mm:02d}:{ss:02d}  {u}")
	print()
	under = [(u, s) for (u, s) in candidates if s < 15*60]
	print(f"Under 15 min: {len(under)} (saved to {OUTPUT_FILE} if any)")
	choice = input('Select a video index to fetch (or press Enter to skip): ').strip()
	if not choice:
		return None
	try:
		idx = int(choice)
		if 1 <= idx <= len(candidates):
			return candidates[idx - 1][0]
	except Exception:
		# Also allow pasting a full URL directly
		if choice.startswith('http'):
			return choice
		return None
	return None


def build_paged_url(base_url: str, page_num: int) -> str:
	parsed = urlparse(base_url)
	qs = parse_qs(parsed.query)
	qs['page'] = [str(page_num)]
	new_query = urlencode({k: v[0] if isinstance(v, list) and v else v for k, v in qs.items()})
	return parsed._replace(query=new_query).geturl()


def find_alternate_listing(soup: BeautifulSoup, current_url: str) -> str | None:
	# If given a video page, try to find a channel/search/tag link to pivot to a listing
	for selector in ['a[href*="/channels/"]', 'a[href*="/tags/"]', 'a[href*="/search/"]', 'a[rel="next"]']:
		el = soup.select_one(selector)
		if el and el.get('href'):
			href = el['href']
			return href if href.startswith('http') else urljoin(current_url, href)
	return None


def pick_random_from_existing() -> str | None:
	mapping = load_existing()
	if not mapping:
		return None
	return random.choice(list(mapping.keys()))


def pick_random_from_cards(cards: list[tuple[str, int]]) -> str | None:
	under = [u for (u, s) in cards if s < 15*60]
	pool = under or [u for (u, _) in cards]
	return random.choice(pool) if pool else None


def refresh_until_filled(url: str, target_total: int, batch_limit: int, delay_seconds: int, max_retries: int, auto: bool = False) -> None:
	attempt = 0
	page_num = 1
	base_url = url
	while True:
		existing_count = len(load_existing())
		if existing_count >= target_total:
			print(f"Target reached: {existing_count} unique links in {OUTPUT_FILE}")
			return
		if attempt >= max_retries:
			print(f"Stop after {max_retries} attempts. Collected {existing_count}/{target_total}.")
			return
		attempt += 1
		try:
			# Rotate pages to avoid repetition
			candidate_url = build_paged_url(base_url, page_num)
			soup = fetch_listing(candidate_url)
			cards = extract_cards(soup, candidate_url)
			# If we are on a single video page, pivot to a richer listing immediately to avoid repetition
			if '/videos/' in urlparse(candidate_url).path:
				alt0 = find_alternate_listing(soup, candidate_url)
				if alt0:
					base_url = alt0
					page_num = 1
					print(f"Attempt {attempt}: pivoted from video to listing {base_url}")
					# Re-fetch listing after pivot
					soup = fetch_listing(base_url)
					cards = extract_cards(soup, base_url)
			if not cards:
				# Try pivot to an alternate listing (channel/search/next)
				alt = find_alternate_listing(soup, candidate_url)
				if alt:
					base_url = alt
					page_num = 1
					print(f"Attempt {attempt}: pivoting to {base_url}")
					time.sleep(2)
					continue
				# last resort: fall back to generic search listing
				root = f"{urlparse(candidate_url).scheme}://{urlparse(candidate_url).netloc}"
				fallback = root + '/search/'
				if base_url != fallback:
					base_url = fallback
					page_num = 1
					print(f"Attempt {attempt}: falling back to {base_url}")
					time.sleep(2)
					continue
				print(f"Attempt {attempt}: no videos found. Retrying in {delay_seconds}s...")
				time.sleep(delay_seconds)
				page_num = page_num + 1 if page_num < 50 else 1
				continue
			added = write_new_under_15(cards, batch_limit, target_total)
			print(f"Attempt {attempt}: added {added} new links. Total now {len(load_existing())}/{target_total} from page {page_num}.")
			# Auto pivot or interactive pivot
			if auto:
				pivot = pick_random_from_cards(cards) or pick_random_from_existing()
				if pivot:
					# If pivot is a video, next cycle will auto-convert it to listing
					base_url = pivot
					page_num = 1
					print(f"Pivoting (auto) to: {base_url}")
			else:
				sel = interactive_pick(cards)
				if sel:
					base_url = sel
					page_num = 1
					print(f"Pivoting to user-selected URL: {base_url}")
			# Advance page to explore different content next (for listings)
			page_num = page_num + 1 if page_num < 50 else 1
			time.sleep(delay_seconds)
		except requests.RequestException as e:
			print(f"Attempt {attempt}: network error: {e}. Retrying in {delay_seconds}s...")
			time.sleep(delay_seconds)


def main():
	# If no URL passed, use quick mode from datalink.txt only
	if len(sys.argv) < 2:
		existing_urls = read_existing_urls()
		if not existing_urls:
			print('No links available in datalink.txt')
			return
		# Pick up to 7 random seed links from datalink.txt
		seeds = random.sample(existing_urls, min(RANDOM_PICK_COUNT, len(existing_urls)))
		print('Random picks:')
		for u in seeds:
			print(u)
		# For each seed, fetch that page and append new <15 min links
		added_total = 0
		for seed in seeds:
			try:
				print(f"Fetching from seed: {seed}")
				soup = fetch_listing(seed)
				cards = extract_cards(soup, seed)
				# randomize and write all available under-15 links from this page
				random.shuffle(cards)
				added = write_new_under_15(cards, batch_limit=10**6, target_total=10**9)
				added_total += added
			except Exception as e:
				print(f"Skip seed due to error: {e}")
		print(f"New links added: {added_total}")
		return
	try:
		url = sys.argv[1]
	except IndexError:
		print('Usage: python src/linkfetch.py "https://xhamster.com/channels/..."')
		sys.exit(1)
	try:
		url = normalize_url(url)
	except ValueError as e:
		print('Invalid URL:', e)
		sys.exit(1)


if __name__ == '__main__':
	main()
