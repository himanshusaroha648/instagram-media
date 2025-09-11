import requests
import json
import uuid
import time
import random
import datetime
import os
import glob

class InstagramDirect:
    def __init__(self, account_data):
        self.account_data = account_data
        self.headers = {
            'user-agent': 'Instagram 329.0.0.0.58 Android (25/7.1.2; 320dpi; 900x1600; samsung; SM-G965N; star2lte; samsungexynos9810; en_US; 541635897)',
            'authorization': self.account_data['data']['IG-Set-Authorization'],
        }
        self.data = {
            'device_id': self.account_data['data']['device_id'],
            '_uuid': self.account_data['data']['uuid'],
        }
        self.proxy = self.account_data['data']['proxy']

    def get_direct_threads(self):
        # First try to get unread threads
        params = {
            'visual_message_return_type': 'unseen',
            'persistentBadging': 'true',
            'limit': '20',
            'is_prefetching': 'false',
            'selected_filter': 'unread',
        }

        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy != "no_proxy" else None
        response = requests.get('https://i.instagram.com/api/v1/direct_v2/inbox/', params=params, headers=self.headers, proxies=proxies)
        time.sleep(random.randint(3, 10))
        if response.status_code != 200:
            raise Exception(f'Failed to get direct threads: {response.text}')
        
        data = json.loads(response.text)

        if not data['inbox']['threads']:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: No unread threads found. Checking all threads...")
            # Try to get all threads if no unread ones
            params['selected_filter'] = 'all'
            response = requests.get('https://i.instagram.com/api/v1/direct_v2/inbox/', params=params, headers=self.headers, proxies=proxies)
            time.sleep(random.randint(3, 10))
            if response.status_code != 200:
                raise Exception(f'Failed to get all direct threads: {response.text}')
            
            data = json.loads(response.text)
            if not data['inbox']['threads']:
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: No threads found at all.")
                return []

        user_ids = [(thread['thread_id'], thread['users'][0]['pk_id'], thread['users'][0]['username']) for thread in data['inbox']['threads']]
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Found {len(user_ids)} thread(s)")

        return user_ids[:self.account_data['num_replies']]

    def get_direct_threads_spam(self):
        params = {
            'visual_message_return_type': 'unseen',
            'persistentBadging': 'true',
            'limit': '20',
            'is_prefetching': 'false',
        }

        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy != "no_proxy" else None
        response = requests.get('https://i.instagram.com/api/v1/direct_v2/pending_inbox/', params=params, headers=self.headers, proxies=proxies)
        time.sleep(random.randint(3, 10))
        if response.status_code != 200:
            raise Exception(f'Failed to get direct threads spam: {response.text}')
        
        data = json.loads(response.text)

        if not data['inbox']['threads']:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Could not find any unread threads in the spam inbox.")
            return []

        user_ids = [(thread['thread_id'], thread['users'][0]['pk_id'], thread['users'][0]['username']) for thread in data['inbox']['threads']]

        return user_ids[:self.account_data['num_replies']]


    def send_message(self, thread_id, message):
        client_context = self._generate_client_context()
        data = self.data.copy()
        data.update({
            'action': 'send_item',
            'is_x_transport_forward': 'false',
            'is_shh_mode': '0',
            'send_silently': 'false',
            'thread_ids': f'[{thread_id}]',
            'send_attribution': 'direct_thread',
            'client_context': client_context,
            'text': message,
            'mutation_token': client_context,
            'btt_dual_send': 'false',
            "nav_chain": (
                "1qT:feed_timeline:1,1qT:feed_timeline:2,1qT:feed_timeline:3,"
                "7Az:direct_inbox:4,7Az:direct_inbox:5,5rG:direct_thread:7"
            ),
            'is_ae_dual_send': 'false',
            'offline_threading_id': client_context,
        })

        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy != "no_proxy" else None
        response = requests.post('https://i.instagram.com/api/v1/direct_v2/threads/broadcast/text/', headers=self.headers, data=data, proxies=proxies)
        time.sleep(random.randint(3, 10))
        if response.status_code != 200:
            raise Exception(f'Failed to send message: {response.text}')

    def _generate_client_context(self):
        """Generate a numeric client context like the working API uses"""
        return str(random.randint(1000000000000000000, 9999999999999999999))

    def send_video_message(self, thread_id, video_paths):
        """
        Send video message using the exact format from successful Instagram video sends
        """
        try:
            if isinstance(video_paths, str):
                video_paths = [video_paths]
            
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Starting upload of {len(video_paths)} video(s)...")
            
            # Upload all videos first
            upload_data = []
            for i, video_path in enumerate(video_paths, 1):
                try:
                    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Uploading video {i}/{len(video_paths)}: {os.path.basename(video_path)}")
                    upload_result = self.upload_video(video_path)
                    upload_data.append(upload_result)
                    # concise progress update
                    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}:   progress uploaded {i}/{len(video_paths)}")
                    if i < len(video_paths):
                        time.sleep(random.randint(2, 5))
                except Exception as e:
                    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ Exception in upload loop: {str(e)}")
                    raise
            
            # Extract media IDs from upload results
            media_ids = []
            upload_ids = []
            for item in upload_data:
                if item and "media_id" in item and item["media_id"]:
                    media_ids.append(item["media_id"])
                if item and "upload_id" in item and item["upload_id"]:
                    upload_ids.append(item["upload_id"])
            
            # Try using media_ids first, fallback to upload_ids if needed
            if media_ids:
                attachment_data = media_ids
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Using media IDs: {media_ids}")
            elif upload_ids:
                attachment_data = upload_ids
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Using upload IDs: {upload_ids}")
            else:
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ No media IDs or upload IDs found!")
                raise Exception("No media IDs or upload IDs found from upload")
            
            # Generate numeric client context like the working API
            client_context = self._generate_client_context()
            
            # Use exact headers from your successful video send
            send_headers = {
                'x-ig-app-locale': 'en_US',
                'x-ig-device-locale': 'en_US',
                'x-ig-mapped-locale': 'en_US',
                'x-pigeon-session-id': f'UFS-{str(uuid.uuid4())}-0',
                'x-pigeon-rawclienttime': str(time.time()),
                'x-ig-bandwidth-speed-kbps': '4287.000',
                'x-ig-bandwidth-totalbytes-b': '2780468',
                'x-ig-bandwidth-totaltime-ms': '1021',
                'x-bloks-version-id': '16e9197b928710eafdf1e803935ed8c450a1a2e3eb696bff1184df088b900bcf',
                'x-ig-www-claim': 'hmac.AR2bDxedvsk50ihmi3QtM6HOf8oERHGUONBWvilycrpUKUkC',
                'x-bloks-prism-button-version': 'CONTROL',
                'x-bloks-prism-colors-enabled': 'true',
                'x-bloks-prism-ax-base-colors-enabled': 'false',
                'x-bloks-prism-font-enabled': 'false',
                'x-bloks-is-layout-rtl': 'false',
                'x-ig-device-id': self.account_data['data']['device_id'],
                'x-ig-family-device-id': '3166521a-7b9b-4cb1-823a-8d5c744a1a5a',
                'x-ig-android-id': 'android-c8d66328d217a2fc',
                'x-ig-timezone-offset': '28800',
                'x-ig-nav-chain': 'DirectInboxFragment:direct_inbox:2:main_direct:1757178178.551:::1757178178.551,DirectThreadFragment:direct_thread:3:inbox:1757178181.131:::1757178181.131,DirectThreadFragment:direct_thread:4:button:1757178181.412:::1757178217.899',
                'x-ig-client-endpoint': 'DirectThreadFragment:direct_thread',
                'x-ig-salt-ids': '51052545',
                'x-fb-session-id': 'nid=IU3dQGIkAPPn;nc=1;fc=1;bc=0;',
                'x-fb-session-private': 'fZSMhXNG/am2',
                'x-fb-connection-type': 'WIFI',
                'x-ig-connection-type': 'WIFI',
                'x-fb-network-properties': 'Validated;LocalAddrs=/fe80::8efd:f0ff:fe12:517a,/192.168.232.2,/3ffe:501:ffff:100:8efd:f0ff:fe12:517a,/3ffe:501:ffff:100:755e:eebd:9fb7:404,;',
                'x-ig-capabilities': '3brTv10=',
                'x-ig-app-id': '567067343352427',
                'user-agent': 'Instagram 361.0.0.46.88 Android (28/9; 239dpi; 1280x720; google; G011C; G011C; intel; en_US; 674674763)',
                'accept-language': 'en-US',
                'authorization': self.account_data['data']['IG-Set-Authorization'],
                'x-mid': 'aLf4qgABAAHh-qhyRy50Dxdn0T_-',
                'ig-u-ds-user-id': self.account_data['data']['pk_id'],
                'ig-u-rur': f'CCO,{self.account_data["data"]["pk_id"]},1788714193:01fe830d5fe846eff09eb36a8ad0d9aa40c383995dcd76112fa9c61710a3cfa900c246c7',
                'ig-intended-user-id': self.account_data['data']['pk_id'],
                'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'accept-encoding': 'zstd, gzip, deflate',
                'x-fb-http-engine': 'Liger',
                'x-fb-client-ip': 'True',
                'x-fb-server-cluster': 'True',
            }
            
            # Use exact data format from your successful video send
            data = {
                'action': 'send_item',
                'is_shh_mode': '0',
                'thread_ids': f'[{thread_id}]',
                'ai_generated_attachment_fbids': '[]',
                'send_attribution': 'inbox',
                'client_context': client_context,
                'meta_gallery_media_info': '[]',
                'device_id': 'android-c8d66328d217a2fc',
                'mutation_token': client_context,
                '_uuid': self.account_data['data']['uuid'],
                'allow_full_aspect_ratio': 'true',
                'nav_chain': 'DirectInboxFragment:direct_inbox:2:main_direct:1757178178.551:::1757178178.551,DirectThreadFragment:direct_thread:3:inbox:1757178181.131:::1757178181.131,DirectThreadFragment:direct_thread:4:button:1757178181.412:::1757178217.899',
                'attachment_fbids': json.dumps(attachment_data),
                'offline_threading_id': client_context,
            }
            
            # Send video message using the correct media_attachment_list endpoint
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Sending video message to thread {thread_id}...")
            proxies = {"http": self.proxy, "https": self.proxy} if self.proxy != "no_proxy" else None
            response = requests.post(
                'https://i.instagram.com/api/v1/direct_v2/threads/broadcast/media_attachment_list/', 
                headers=send_headers,
                data=data, 
                proxies=proxies
            )
            
            time.sleep(random.randint(3, 10))
            if response.status_code != 200:
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ Video message send FAILED: {response.text}")
                raise Exception(f'Failed to send video message: {response.text}')
            
            return True
            
        except Exception as e:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ Exception in send_video_message: {str(e)}")
            raise

    def send_video_to_user(self, username, video_paths):
        """
        Send video to a specific user by username
        Args:
            username: Instagram username (without @)
            video_paths: List of video file paths
        """
        # First, get all threads to find the user
        params = {
            'visual_message_return_type': 'unseen',
            'persistentBadging': 'true',
            'limit': '50',
            'is_prefetching': 'false',
            'selected_filter': 'all',
        }

        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy != "no_proxy" else None
        response = requests.get('https://i.instagram.com/api/v1/direct_v2/inbox/', params=params, headers=self.headers, proxies=proxies)
        time.sleep(random.randint(3, 10))
        if response.status_code != 200:
            raise Exception(f'Failed to get direct threads: {response.text}')
        
        data = json.loads(response.text)
        
        if not data['inbox']['threads']:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: No threads found.")
            return False

        # Find the specific user
        target_thread_id = None
        for thread in data['inbox']['threads']:
            if thread['users'][0]['username'].lower() == username.lower():
                target_thread_id = thread['thread_id']
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Found user @{username} with thread ID: {target_thread_id}")
                break
        
        if not target_thread_id:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: User @{username} not found in threads.")
            return False
        
        # Send video to the found thread
        try:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Sending video Instagram [{username}]")
            self.send_video_message(target_thread_id, video_paths)
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ✅ Video sent successfully")
            return True
        except Exception as e:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ Failed to send video to @{username}: {e}")
            return False

    def test_proxy(self):
        if self.proxy == "no_proxy":
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: No proxy is being used.")
            return

        proxies = {"http": self.proxy, "https": self.proxy}
        response = requests.get('https://api.ipify.org?format=json', proxies=proxies)
        proxy_ip = self.proxy.split('@')[1].split(':')[0]
        if response.json()['ip'] != proxy_ip:
            print(f"Expected Proxy IP: {proxy_ip}")
            print(f"Actual Proxy IP: {response.json()['ip']}")
            raise Exception(f'Proxy IP does not match: {response.text}')
        else:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Proxy IP matches.")

    def upload_video(self, file_path):
        """
        Upload a video file using the exact format from your successful uploads
        Returns the upload_id for the uploaded video
        """
        if not os.path.exists(file_path):
            raise Exception(f"Video file not found: {file_path}")
        
        # Get file size first
        file_size = os.path.getsize(file_path)
        
        # Generate upload ID in the exact format you used
        timestamp = int(time.time() * 1000)
        file_hash = str(hash(os.path.basename(file_path)))[:16]
        upload_id = f"{file_hash}-0-{file_size}-{timestamp}-{timestamp}"
        
        # Use the exact headers from your successful upload
        upload_headers = {
            'x-entity-length': str(file_size),
            'x-entity-name': upload_id,
            'x-entity-type': 'video/mp4',
            'segment-start-offset': '0',
            'video_type': 'FILE_ATTACHMENT',
            'uu_mos_cs': '66.140327585155',
            'x_fb_video_waterfall_id': f'{timestamp}_3FB4B5E6D14E_Mixed_0',
            'segment-type': '3',
            'offset': '0',
            'x-ig-salt-ids': '356981044,51052545',
            'x-fb-session-id': 'nid=2eJbz+yb7y36;nc=1;fc=3;bc=2;',
            'x-fb-session-private': 'm1FOzYvjwyGx',
            'user-agent': 'Instagram 361.0.0.46.88 Android (28/9; 239dpi; 1280x720; google; G011C; G011C; intel; en_US; 674674763)',
            'accept-language': 'en-US',
            'authorization': self.account_data['data']['IG-Set-Authorization'],
            'x-mid': 'aLf4qgABAAHh-qhyRy50Dxdn0T_-',
            'ig-u-ds-user-id': self.account_data['data']['pk_id'],
            'ig-u-rur': f'PRN,{self.account_data["data"]["pk_id"]},1788607255:01fea8c5a305387aad90733df57ccf2e83dc9470c00a0ccf09659de692f7fa96011966e3',
            'ig-intended-user-id': self.account_data['data']['pk_id'],
            'content-type': 'application/octet-stream',
            'accept-encoding': 'zstd, gzip, deflate',
            'x-fb-http-engine': 'Liger',
            'x-fb-client-ip': 'True',
            'x-fb-server-cluster': 'True',
        }
        
        # Use the exact upload URL from your successful uploads
        upload_url = f'https://rupload.facebook.com/messenger_video/{upload_id}'
        
        # Read video file
        with open(file_path, 'rb') as video_file:
            video_data = video_file.read()
        
        # Upload video
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy != "no_proxy" else None
        response = requests.post(upload_url, headers=upload_headers, data=video_data, proxies=proxies)
        
        if response.status_code != 200:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ Video upload FAILED: {response.text}")
            raise Exception(f'Failed to upload video: {response.text}')
        
        # Parse response to get media_id
        try:
            response_data = response.json()
            media_id = response_data.get('media_id')
            if media_id:
                return {"upload_id": upload_id, "media_id": str(media_id)}
            else:
                return {"upload_id": upload_id, "media_id": None}
        except:
            return {"upload_id": upload_id, "media_id": None}

    def send_video_with_upload_ids(self, thread_id, upload_ids):
        """
        Send videos using pre-existing upload IDs
        Args:
            thread_id: Target thread ID
            upload_ids: List of upload IDs (like the ones you got)
        """
        # Send videos via DM
        client_context = self._generate_client_context()
        data = self.data.copy()
        
        # Try different attachment formats
        # Format 1: As objects with upload_id
        attachments = [{"upload_id": upload_id} for upload_id in upload_ids]
        
        data.update({
            'action': 'send_item',
            'is_x_transport_forward': 'false',
            'is_shh_mode': '0',
            'send_silently': 'false',
            'thread_ids': f'[{thread_id}]',
            'send_attribution': 'direct_thread',
            'client_context': client_context,
            'media_type': 'video',
            'attachment': json.dumps(attachments),  # Try as objects
            'mutation_token': client_context,
            'btt_dual_send': 'false',
            "nav_chain": (
                "1qT:feed_timeline:1,1qT:feed_timeline:2,1qT:feed_timeline:3,"
                "7Az:direct_inbox:4,7Az:direct_inbox:5,5rG:direct_thread:7"
            ),
            'is_ae_dual_send': 'false',
            'offline_threading_id': client_context,
        })
        
        # Send DM with videos
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Sending video message to thread {thread_id}...")
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Using upload IDs: {upload_ids}")
        
        # Use exact headers from your successful DM send
        send_headers = {
            'x-ig-app-locale': 'en_US',
            'x-ig-device-locale': 'en_US',
            'x-ig-mapped-locale': 'en_US',
            'x-pigeon-session-id': f'UFS-{client_context[:8]}-{client_context[8:12]}-{client_context[12:16]}-{client_context[16:20]}-{client_context[20:32]}-2',
            'x-pigeon-rawclienttime': str(time.time()),
            'x-ig-bandwidth-speed-kbps': '1033.000',
            'x-ig-bandwidth-totalbytes-b': '166410405',
            'x-ig-bandwidth-totaltime-ms': '117906',
            'x-bloks-version-id': '16e9197b928710eafdf1e803935ed8c450a1a2e3eb696bff1184df088b900bcf',
            'x-ig-www-claim': 'hmac.AR0BU6uB5a5QLFavekJTP0tM7ranrHtQKwzvuoBkoJsmj5ca',
            'x-bloks-prism-button-version': 'CONTROL',
            'x-bloks-prism-colors-enabled': 'true',
            'x-bloks-prism-ax-base-colors-enabled': 'false',
            'x-bloks-prism-font-enabled': 'false',
            'x-bloks-is-layout-rtl': 'false',
            'x-ig-device-id': self.account_data['data']['device_id'],
            'x-ig-family-device-id': '3166521a-7b9b-4cb1-823a-8d5c744a1a5a',
            'x-ig-android-id': 'android-c8d66328d217a2fc',
            'x-ig-timezone-offset': '28800',
            'x-ig-nav-chain': 'DirectInboxFragment:direct_inbox:3:main_direct:1757070703.190:::1757071185.518,DirectThreadFragment:direct_thread:31:inbox:1757071190.890:::1757071190.890,DirectThreadFragment:direct_thread:32:button:1757071190.980:::1757071283.814',
            'x-ig-client-endpoint': 'DirectThreadFragment:direct_thread',
            'x-ig-salt-ids': '51052545',
            'x-fb-session-id': 'nid=2eJbz+yb7y36;nc=1;fc=3;bc=2;',
            'x-fb-session-private': 'm1FOzYvjwyGx',
            'x-fb-connection-type': 'WIFI',
            'x-ig-connection-type': 'WIFI',
            'x-fb-network-properties': 'Validated;LocalAddrs=/fe80::8efd:f0ff:fe12:517a,/192.168.232.2,/3ffe:501:ffff:100:8efd:f0ff:fe12:517a,/3ffe:501:ffff:100:1429:7e79:4386:e788,;',
            'x-ig-capabilities': '3brTv10=',
            'x-ig-app-id': '567067343352427',
            'user-agent': 'Instagram 361.0.0.46.88 Android (28/9; 239dpi; 1280x720; google; G011C; G011C; intel; en_US; 674674763)',
            'accept-language': 'en-US',
            'authorization': self.account_data['data']['IG-Set-Authorization'],
            'x-mid': 'aLf4qgABAAHh-qhyRy50Dxdn0T_-',
            'ig-u-ds-user-id': self.account_data['data']['pk_id'],
            'ig-u-rur': f'PRN,{self.account_data["data"]["pk_id"]},1788607255:01fea8c5a305387aad90733df57ccf2e83dc9470c00a0ccf09659de692f7fa96011966e3',
            'ig-intended-user-id': self.account_data['data']['pk_id'],
            'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'accept-encoding': 'zstd, gzip, deflate',
            'x-fb-http-engine': 'Liger',
            'x-fb-client-ip': 'True',
            'x-fb-server-cluster': 'True',
        }
        
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy != "no_proxy" else None
        response = requests.post(
            'https://i.instagram.com/api/v1/direct_v2/threads/broadcast/media_attachment_list/', 
            headers=send_headers, 
            data=data, 
            proxies=proxies
        )
        
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Send response status: {response.status_code}")
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Send response: {response.text[:200]}...")
        
        if response.status_code != 200:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ Video message send FAILED: {response.text}")
            raise Exception(f'Failed to send video message: {response.text}')
        
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ✅ Video message sent successfully to thread {thread_id}")
        return True

    def send_video_to_user_by_upload_ids(self, username, upload_ids):
        """
        Send videos to a specific user using pre-existing upload IDs
        Args:
            username: Instagram username (without @)
            upload_ids: List of upload IDs
        """
        # First, get all threads to find the user
        params = {
            'visual_message_return_type': 'unseen',
            'persistentBadging': 'true',
            'limit': '50',
            'is_prefetching': 'false',
            'selected_filter': 'all',
        }

        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy != "no_proxy" else None
        response = requests.get('https://i.instagram.com/api/v1/direct_v2/inbox/', params=params, headers=self.headers, proxies=proxies)
        time.sleep(random.randint(3, 10))
        if response.status_code != 200:
            raise Exception(f'Failed to get direct threads: {response.text}')
        
        data = json.loads(response.text)
        
        if not data['inbox']['threads']:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: No threads found.")
            return False

        # Find the specific user
        target_thread_id = None
        for thread in data['inbox']['threads']:
            if thread['users'][0]['username'].lower() == username.lower():
                target_thread_id = thread['thread_id']
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Found user @{username} with thread ID: {target_thread_id}")
                break
        
        if not target_thread_id:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: User @{username} not found in threads.")
            return False
        
        # Send videos using upload IDs
        try:
            self.send_video_with_upload_ids(target_thread_id, upload_ids)
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ✅ Video sent successfully to @{username}")
            return True
        except Exception as e:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: ❌ Failed to send video to @{username}: {e}")
            return False

    def send_videos_in_batches(self, thread_id, video_paths, batch_size=10):
        """Send videos to a thread in batches of up to 10. Delete each file after successful send.
        Returns total number of videos sent. If media is blocked (invitation not accepted), sends a fallback text and stops.
        """
        if isinstance(video_paths, str):
            video_paths = [video_paths]
        vids = [p for p in video_paths if os.path.exists(p)]
        if not vids:
            return 0
        total_sent = 0
        for i in range(0, len(vids), max(1, int(batch_size))):
            batch = vids[i:i+batch_size]
            try:
                self.send_video_message(thread_id, batch)
                total_sent += len(batch)
                # delete after successful send to prevent duplicates
                for p in batch:
                    try:
                        os.remove(p)
                    except Exception:
                        pass
            except Exception as e:
                msg = str(e)
                # Media blocked until invitation accepted
                if '1545121' in msg or "can't be delivered" in msg or 'status_code":"403' in msg:
                    fallback_text = "Hi! Please accept the chat request so I can send videos."
                    try:
                        self.send_message(thread_id, fallback_text)
                    except Exception:
                        pass
                    break
                else:
                    raise
        return total_sent
    
    def get_split_videos(self, count=None):
        """
        Get random video files from the split directory
        Args:
            count: Number of videos to return (None for all)
        Returns:
            List of video file paths from split directory
        """
        # Get the split directory path
        split_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'split')
        
        # Find all mp4 files in split directory
        video_patterns = [
            os.path.join(split_dir, '*.mp4'),
            os.path.join(split_dir, '*.MP4'),
            os.path.join(split_dir, '*.avi'),
            os.path.join(split_dir, '*.mov')
        ]
        
        all_videos = []
        for pattern in video_patterns:
            all_videos.extend(glob.glob(pattern))
        
        if not all_videos:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: No videos found in split directory: {split_dir}")
            return []
        
        # Shuffle videos for random selection
        random.shuffle(all_videos)
        
        # Return requested count or all videos
        if count is None:
            selected_videos = all_videos
        else:
            selected_videos = all_videos[:count]
        
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Found {len(all_videos)} videos in split directory, selected {len(selected_videos)}")
        return selected_videos
    
    def send_random_split_videos(self, thread_id, video_count=2):
        """
        Send random videos from split directory to a thread
        Args:
            thread_id: Instagram thread ID
            video_count: Number of videos to send (default: 2)
        """
        videos = self.get_split_videos(video_count)
        if videos:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: Sending {len(videos)} random videos from split directory...")
            self.send_video_message(thread_id, videos)
            return True
        else:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}: No videos available in split directory")
            return False
