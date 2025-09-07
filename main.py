import os
import sys
from src.direct import InstagramDirect
import json
import random
import time
import datetime

def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)
        
ensure_dir('accounts')
ensure_dir('responded_users')
ensure_dir('locks')

console_width = os.get_terminal_size().columns
print('-' * console_width)

def choose_account():
    config_files = [f for f in os.listdir('accounts') if f.endswith('.json')]

    if not config_files:
        print("There's no config file in 'accounts'.")
        return None

    for i, file in enumerate(config_files):
        print(f'{i + 1}. {file}')

    console_width = os.get_terminal_size().columns
    print('-' * console_width)

    file_num = int(input("Select account: ")) - 1
    config_file = config_files[file_num]
    account_name, _ = os.path.splitext(config_file)

    print(f"Selected account: {account_name}")

    with open(f'accounts/{config_file}', 'r', encoding='utf-8') as f:
        config = json.load(f)
    return config

def choose_message_type():
    """Choose between text messages or video messages"""
    console_width = os.get_terminal_size().columns
    print('-' * console_width)
    print("Choose message type:")
    print("1. Text messages")
    print("2. Video messages")
    print("3. Both (random selection)")
    print("4. Send video to specific user")
    print('-' * console_width)
    
    while True:
        choice = input("Select message type (1/2/3/4): ").strip()
        if choice in ['1', '2', '3', '4']:
            return int(choice)
        else:
            print("Please enter 1, 2, 3, or 4.")

def get_video_paths():
    """Get video file paths from user"""
    video_paths = []
    print("\nEnter video file paths (one per line, press Enter twice when done):")
    
    while True:
        path = input("Video path: ").strip()
        if not path:
            break
        if os.path.exists(path):
            video_paths.append(path)
            print(f"✅ Added: {os.path.basename(path)}")
        else:
            print(f"❌ File not found: {path}")
    
    if not video_paths:
        print("No valid video paths provided.")
        return None
    
    # Show video count and selection options
    print(f"\n📹 Total videos added: {len(video_paths)}")
    print("How many videos to send per message?")
    print("1. Send 1 video per message")
    print("2. Send 2 videos per message") 
    print("3. Send random (1-2 videos)")
    
    while True:
        choice = input("Select option (1/2/3): ").strip()
        if choice in ['1', '2', '3']:
            video_count = int(choice)
            break
        else:
            print("Please enter 1, 2, or 3.")
    
    return video_paths, video_count

def has_responded(account_name, user_id):
    file_name = f'responded_users/{account_name}.json'
    if not os.path.exists(file_name):
        return False
    with open(file_name, 'r', encoding='utf-8') as f:
        responded_users = json.load(f)
    return str(user_id) in responded_users

def mark_as_responded(account_name, user_id, username):
    file_name = f'responded_users/{account_name}.json'
    responded_users = {}
    if os.path.exists(file_name):
        with open(file_name, 'r', encoding='utf-8') as f:
            responded_users = json.load(f)
    responded_users[str(user_id)] = username
    with open(file_name, 'w', encoding='utf-8') as f:
        json.dump(responded_users, f)

config = choose_account()

if config is None:
    print("Can't load config.")
else:
    # Choose message type
    message_type = choose_message_type()
    
    # Get video paths if needed
    video_paths = None
    video_count = 1
    target_username = None
    
    if message_type in [2, 3, 4]:  # Video messages, both, or specific user
        result = get_video_paths()
        if result is None and message_type in [2, 4]:
            print("No video paths provided. Exiting.")
            sys.exit()
        elif result is not None:
            video_paths, video_count = result
    
    # Get target username for specific user option
    if message_type == 4:
        target_username = input("Enter username to send video to (without @): ").strip()
        if not target_username:
            print("No username provided. Exiting.")
            sys.exit()

    while True:
        continue_choice = input("Do you want to continue? (yes/no): ").lower()
        if continue_choice in ["yes", "no"]:
            break
        else:
            print("Please enter 'yes' or 'no'.")

    if continue_choice == "no":
        print("Exiting.")
        sys.exit()

    lock_file = os.path.join('locks', f"{config['account']}.lock")

    if os.path.exists(lock_file):
        print(f"Account {config['account']} lock file found. Removing old lock file...")
        try:
            os.remove(lock_file)
            print(f"✅ Old lock file removed successfully.")
        except Exception as e:
            print(f"❌ Failed to remove lock file: {e}")
            print("Please manually delete the lock file and try again.")
            sys.exit()
    
    # Create new lock file
    open(lock_file, 'a').close()
    print(f"✅ Lock file created for account {config['account']}")

    session = InstagramDirect(config)
    session.test_proxy()

    # Handle specific user sending
    if message_type == 4:
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Sending video to @{target_username}...")
        try:
            success = session.send_video_to_user(target_username, video_paths)
            if success:
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ✅ Video sent successfully to @{target_username}")
            else:
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ Failed to send video to @{target_username}")
        except Exception as e:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ Error sending video to @{target_username}: {e}")
        
        # Remove lock file and exit
        if os.path.exists(lock_file):
            os.remove(lock_file)
        sys.exit()

    message_counter = 0
    while message_counter < config['num_replies']:
        user_ids = session.get_direct_threads()
        all_responded = all(has_responded(config['account'], user_id) for _, user_id, _ in user_ids)
        if all_responded:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: All users from direct threads have been responded to. Checking spam inbox...")
            user_ids = session.get_direct_threads_spam()  # Check spam inbox if all users from get_direct_threads have been responded to
        if not user_ids:
            wait_time = random.randint(120, 300) # Adjust the wait time as needed
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: No new threads in inbox or spam inbox. Waiting for {wait_time} seconds before checking for new threads...")
            time.sleep(wait_time)
        for thread_id, user_id, username in user_ids:
            if message_counter >= config['num_replies']:
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Reached reply limit ({config['num_replies']}). Stopping message sending.")
                break
            if has_responded(config['account'], user_id):
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Already responded to user {username} ; Skipping.")
                time.sleep(random.randint(120, 300)) # Adjust the wait time as needed
                continue
            
            # Determine what type of message to send
            if message_type == 1:  # Text only
                message = random.choice(config['messages'])
                session.send_message(thread_id, message)
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: [{message_counter+1}/{config['num_replies']}] Sent text message to user {username}: '{message}'")
                
            elif message_type == 2:  # Video only
                if video_paths:
                    # Select videos based on user choice
                    if video_count == 1:
                        selected_videos = [random.choice(video_paths)]
                    elif video_count == 2:
                        selected_videos = random.sample(video_paths, min(len(video_paths), 2))
                    else:  # random
                        selected_videos = random.sample(video_paths, min(len(video_paths), random.randint(1, 2)))
                    
                    try:
                        session.send_video_message(thread_id, selected_videos)
                        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: [{message_counter+1}/{config['num_replies']}] ✅ Successfully sent video message to user {username}: {[os.path.basename(v) for v in selected_videos]}")
                    except Exception as e:
                        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: [{message_counter+1}/{config['num_replies']}] ❌ Failed to send video to user {username}: {e}")
                        continue
                
            elif message_type == 3:  # Both (random selection)
                if random.choice([True, False]):  # Random choice between text and video
                    message = random.choice(config['messages'])
                    session.send_message(thread_id, message)
                    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: [{message_counter+1}/{config['num_replies']}] ✅ Sent text message to user {username}: '{message}'")
                else:
                    if video_paths:
                        selected_videos = random.sample(video_paths, min(len(video_paths), random.randint(1, 2)))
                        try:
                            session.send_video_message(thread_id, selected_videos)
                            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: [{message_counter+1}/{config['num_replies']}] ✅ Successfully sent video message to user {username}: {[os.path.basename(v) for v in selected_videos]}")
                        except Exception as e:
                            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: [{message_counter+1}/{config['num_replies']}] ❌ Failed to send video to user {username}: {e}")
                            continue
                    else:
                        message = random.choice(config['messages'])
                        session.send_message(thread_id, message)
                        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: [{message_counter+1}/{config['num_replies']}] ✅ Sent text message to user {username}: '{message}'")
            
            mark_as_responded(config['account'], user_id, username)
            wait_time = random.randint(600, 900) # Adjust the wait time as needed
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Waiting {wait_time} seconds before sending message to next user.")
            message_counter += 1
            time.sleep(wait_time)


    if os.path.exists(lock_file):
        os.remove(lock_file)
