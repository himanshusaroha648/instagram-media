import os
import json
import time
import datetime
import requests
from src.direct import InstagramDirect

ACCOUNTS_DIR = 'accounts'
THREAD_FILE = 'thread.txt'


def load_first_account_config():
	files = [f for f in os.listdir(ACCOUNTS_DIR) if f.endswith('.json')]
	if not files:
		raise RuntimeError("No account JSON found in 'accounts/'")
	files.sort()
	with open(os.path.join(ACCOUNTS_DIR, files[0]), 'r', encoding='utf-8') as f:
		return json.load(f)


def _collect_threads(data_obj, collector: dict):
	"""Update collector mapping thread_id -> {usernames: [...], is_group: bool} from API response."""
	for th in data_obj.get('inbox', {}).get('threads', []) or []:
		thread_id = th.get('thread_id')
		if not thread_id:
			continue
		usernames = []
		try:
			for u in th.get('users', []) or []:
				uname = u.get('username')
				if uname:
					usernames.append(uname)
		except Exception:
			pass
		is_group = len(usernames) > 1
		collector[str(thread_id)] = {
			'usernames': usernames,
			'is_group': is_group,
		}


def fetch_threads_for_account(config):
	client = InstagramDirect(config)
	proxies = {"http": client.proxy, "https": client.proxy} if client.proxy != "no_proxy" else None
	headers = client.headers

	all_threads: dict[str, dict] = {}

	# Inbox: all threads
	params_all = {
		'visual_message_return_type': 'default',
		'persistentBadging': 'true',
		'limit': '100',
		'is_prefetching': 'false',
		'selected_filter': 'all',
	}
	r = requests.get('https://i.instagram.com/api/v1/direct_v2/inbox/', params=params_all, headers=headers, proxies=proxies)
	time.sleep(1)
	if r.status_code == 200:
		_collect_threads(r.json(), all_threads)

	# Inbox: unread
	params_unseen = {
		'visual_message_return_type': 'unseen',
		'persistentBadging': 'true',
		'limit': '100',
		'is_prefetching': 'false',
		'selected_filter': 'unread',
	}
	r = requests.get('https://i.instagram.com/api/v1/direct_v2/inbox/', params=params_unseen, headers=headers, proxies=proxies)
	time.sleep(1)
	if r.status_code == 200:
		_collect_threads(r.json(), all_threads)

	# Pending inbox
	params_pending = {
		'visual_message_return_type': 'unseen',
		'persistentBadging': 'true',
		'limit': '100',
		'is_prefetching': 'false',
	}
	r = requests.get('https://i.instagram.com/api/v1/direct_v2/pending_inbox/', params=params_pending, headers=headers, proxies=proxies)
	time.sleep(1)
	if r.status_code == 200:
		_collect_threads(r.json(), all_threads)

	# Return list of (thread_id, is_group, usernames)
	items = []
	for tid, meta in all_threads.items():
		items.append((tid, meta.get('is_group', False), meta.get('usernames', [])))
	items.sort(key=lambda x: x[0])
	return items


def write_threads(thread_items):
	with open(THREAD_FILE, 'w', encoding='utf-8') as f:
		for tid, is_group, usernames in thread_items:
			type_str = 'group' if is_group else 'single'
			names = ','.join(usernames)
			f.write(f"{tid}\t{type_str}\t{names}\n")


def main():
	try:
		config = load_first_account_config()
		print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Loaded account {config.get('account')}")
		threads = fetch_threads_for_account(config)
		write_threads(threads)
		print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Saved {len(threads)} thread IDs to {THREAD_FILE}")
	except Exception as e:
		print(f"Error: {e}")


if __name__ == '__main__':
	main()
