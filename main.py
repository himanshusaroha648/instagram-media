import os
import sys
from src.direct import InstagramDirect
import json
import random
import time
import datetime
import subprocess


def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)
        
ensure_dir('accounts')
ensure_dir('responded_users')
ensure_dir('locks')

console_width = os.get_terminal_size().columns
print('-' * console_width)


def choose_account_configs():
        """Load all account configs in accounts/ as a list of dicts."""
        configs = []
        for file in os.listdir('accounts'):
                if file.endswith('.json'):
                        with open(os.path.join('accounts', file), 'r', encoding='utf-8') as f:
                                configs.append(json.load(f))
        return configs


def read_thread_ids(path='thread.txt'):
        """Read thread IDs (one per line). Returns a list of strings."""
        if not os.path.exists(path):
                return []
        with open(path, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip()]


def list_split_videos(folder='split'):
        """Return list of absolute paths to videos in split/ sorted by name."""
        # Get the correct path relative to the script location
        script_dir = os.path.dirname(os.path.abspath(__file__))
        split_path = os.path.join(script_dir, folder)
        
        if not os.path.isdir(split_path):
                return []
        paths = []
        for name in sorted(os.listdir(split_path)):
                p = os.path.join(split_path, name)
                if os.path.isfile(p) and name.lower().endswith(('.mp4', '.mov', '.mkv', '.webm')):
                        paths.append(p)
        return paths


def within_working_hours():
        """Return True only between 08:00 and 22:00 local time."""
        now = datetime.datetime.now().time()
        start = datetime.time(8, 0, 0)
        end = datetime.time(22, 0, 0)
        return start <= now <= end


def run_thread_mode_for_account(config):
        """Send videos from split/ to all thread IDs in batches of 10, deleting files after send."""
        account_name = config['account']
        lock_file = os.path.join('locks', f"{account_name}.lock")
        if os.path.exists(lock_file):
                try:
                        os.remove(lock_file)
                except Exception:
                        pass
        open(lock_file, 'a').close()

        session = InstagramDirect(config)
        try:
                session.test_proxy()
        except Exception:
                pass

        thread_ids = read_thread_ids('thread.txt')
        if not thread_ids:
                print('No thread IDs found in thread.txt')
                return

        videos = list_split_videos('split')
        if not videos:
                print('No videos found in split/')
                return

        # Shuffle videos so batches differ between accounts
        random.shuffle(videos)

        for thread_id in thread_ids:
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Sending videos to thread {thread_id}...")
                total = session.send_videos_in_batches(thread_id, videos, batch_size=10)
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ✅ Sent {total} videos to thread {thread_id}")
                # refresh remaining videos list after deletions
                videos = list_split_videos('split')
                if not videos:
                        break
        # Cleanup lock
        if os.path.exists(lock_file):
                os.remove(lock_file)


def run_continuous_workflow():
        """Run pipeline every 5 minutes during 8:00-22:00, sleep 22:00-8:00, rotate accounts every 90 minutes."""
        configs = choose_account_configs()
        if not configs:
                print("There's no config file in 'accounts'.")
                return
        
        account_idx = 0
        last_pipeline_run = 0
        last_account_switch = 0
        
        while True:
                now = datetime.datetime.now()
                current_time = now.time()
                
                # Check if we're in working hours (8:00-22:00)
                if not within_working_hours():
                        # Sleep until 08:00 next day
                        next_start = now.replace(hour=8, minute=0, second=0, microsecond=0)
                        if next_start <= now:
                                next_start += datetime.timedelta(days=1)
                        sleep_seconds = int((next_start - now).total_seconds())
                        print(f"{now.strftime('%Y-%m-%d %H:%M:%S')}: Outside working hours (22:00-08:00). Sleeping {sleep_seconds} seconds until 08:00...")
                        time.sleep(sleep_seconds)
                        continue
            
                # Run pipeline every 5 minutes
                if now.timestamp() - last_pipeline_run >= 300:  # 5 minutes = 300 seconds
                        print(f"{now.strftime('%Y-%m-%d %H:%M:%S')}: Running pipeline (linkfetch -> download -> split)...")
                        run_pipeline_once()
                        last_pipeline_run = now.timestamp()
                
                # Switch account every 90 minutes
                if now.timestamp() - last_account_switch >= 5400:  # 90 minutes = 5400 seconds
                        account_idx = (account_idx + 1) % len(configs)
                        last_account_switch = now.timestamp()
                        print(f"{now.strftime('%Y-%m-%d %H:%M:%S')}: Switched to account: {configs[account_idx]['account']}")
                
                # Send videos with current account
                config = configs[account_idx]
                print(f"{now.strftime('%Y-%m-%d %H:%M:%S')}: Using account: {config['account']}")
                run_thread_mode_for_account(config)
                
                # Wait 1 minute before next cycle
                print(f"{now.strftime('%Y-%m-%d %H:%M:%S')}: Waiting 1 minute before next cycle...")
                time.sleep(60)


def run_pipeline_once():
        """Run: linkfetch -> download -> split, then return to let DM sending begin."""
        proj_root = os.path.dirname(os.path.abspath(__file__))
        python = sys.executable
        # Build absolute script paths relative to project root
        linkfetch = os.path.join(proj_root, 'src', 'linkfetch.py')
        downloader = os.path.join(proj_root, 'xhamster', 'download.py')
        splitter = os.path.join(proj_root, 'src', 'split.py')
        # Execute sequentially, non-interactive
        print('Running linkfetch...')
        try:
                subprocess.run([python, linkfetch], check=False)
        except Exception as e:
                print('linkfetch failed:', e)
        print('Running downloader...')
        try:
                subprocess.run([python, downloader], check=False)
        except Exception as e:
                print('downloader failed:', e)
        print('Running splitter...')
        try:
                subprocess.run([python, splitter], check=False)
        except Exception as e:
                print('splitter failed:', e)


if __name__ == '__main__':
        # Run continuous workflow: pipeline every 5 minutes, account rotation every 90 minutes
        run_continuous_workflow()
