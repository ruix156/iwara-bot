import hashlib
import os
import random
import time

import requests

# import cloudscraper
# from requests_html import HTMLSession
# from bs4 import BeautifulSoup
# html_url = 'https://iwara.tv'

api_url = 'https://api.iwara.tv'
file_url = 'https://files.iwara.tv'

class BearerAuth(requests.auth.AuthBase):
    """Bearer Authentication"""
    def __init__(self, token):
        self.token = token

    def __call__(self, r):
        r.headers['Authorization'] = 'Bearer ' + self.token
        return r

class ApiClient:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/93.0.4577.82 Safari/537.36',
            'Connection': 'Keep-Alive'
        })  # 设置请求头,启用HTTP持久连接
        self.request_delay = (5, 10)  # 设置请求间隔时间范围(秒)
        self.video_cache = {}  # 创建一个字典用于缓存视频数据
        # self.headers = {
        # 'User-Agent': 'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/66.0.3359.181 Safari/537.36',
        # 'X-Version': 's'
        # }

        # API
        self.api_url = api_url
        self.file_url = file_url
        self.timeout = 30
        # self.max_retries = 5
        self.download_timeout = 300
        self.token = None

        # HTML
        # self.html_url = html_url

        # Cloudscraper
        # self.scraper = cloudscraper.create_scraper(browser={'browser': 'firefox','platform': 'windows','mobile': False}, 
        #                                         #    interpreter = 'nodejs'
        #                                         )
        # Requests-html
        # self.session = HTMLSession()

    def login(self) -> requests.Response:
        url = self.api_url + '/user/login'
        json = {'email': self.email, 'password': self.password}
        r = requests.post(url, json=json, timeout=self.timeout)
        try:
            self.token = r.json()['token']
            print('API Login success')
        except:
            print('API Login failed')

        # try:
        #     # Cloudscraper
        #     # r = self.scraper.post(url, json=json, headers=self.headers, timeout=self.timeout)

        #     # Requests-html
        #     r = self.session.post(url, json=json, headers=self.headers, timeout=self.timeout)
        # except:
        #     print('BS4 Login failed')

        return r
    def _make_request(self, method, url, **kwargs):
        time.sleep(random.uniform(*self.request_delay))  # 在发送请求前添加随机延时
        return self.session.request(method, url, **kwargs)
    
    # limit query is not working
    def get_videos(self, sort = 'date', rating = 'all', page = 0, limit = 32, subscribed = False) -> requests.Response:
        """# Get new videos from iwara.tv
        - sort: date, trending, popularity, views, likes
        - rating: all, general, ecchi
        """
        url = self.api_url + '/videos'
        params = {'sort': sort, 
                  'rating': rating, 
                  'page': page, 
                  'limit': limit,
                  'subscribed': 'true' if subscribed else 'false',
                  }
        if self.token is None:
            r = requests.get(url, params=params, timeout=self.timeout)
        else:

            # Verbose Debug
            # request = requests.Request('GET', url, params=params, auth=BearerAuth(self.token))
            # print(request.prepare().method, request.prepare().url, request.prepare().headers, request.prepare().body, sep='\n')
            # r = requests.Session().send(request.prepare())

            r = requests.get(url, params=params, auth=BearerAuth(self.token), timeout=self.timeout)

        #Debug
        print("[DEBUG] get_videos response:", r)

        return r
    
    def get_video(self, video_id) -> requests.Response:
        if video_id in self.video_cache:
            print(f"Video {video_id} found in cache, using cached data.")
            return self.video_cache[video_id]
        
        url = self.api_url + '/video/' + video_id

        if self.token is None:
            r = self._make_request('GET', url, timeout=self.timeout)
        else:
            r = self._make_request('GET', url, auth=BearerAuth(self.token), timeout=self.timeout)

        self.video_cache[video_id] = r  # 将请求结果存入缓存
        return r
    
    def download_video_thumbnail(self, video_id) -> str:
        """# Download video thumbnail from iwara.tv
        """
        video = self.get_video(video_id).json()

        file_id = video['file']['id']
        thumbnail_id = video['thumbnail']
        
        url = self.file_url + '/image/original/' + file_id + '/thumbnail-{:02d}.jpg'.format(thumbnail_id)

        thumbnail_file_name = video_id + '.jpg'

        if (os.path.exists(thumbnail_file_name)):
            print(f"Video ID {video_id} thumbnail already downloaded, skipped downloading. ")
            return thumbnail_file_name
        
        print(f"Downloading thumbnail for video ID: {video_id} ...")
        with open(thumbnail_file_name, "wb") as f:
            for chunk in requests.get(url).iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
                    f.flush()

        return thumbnail_file_name

    def download_video(self, video_id) -> str:
        """# Download video from iwara.tv
        """

        # html
        # url = self.html_url + '/video/' + video_id

        # Cloudscraer
        # html = self.scraper.get(url, auth=BearerAuth(self.token), timeout=self.timeout).text

        # Requests-html
        # html = self.session.get(url, auth=BearerAuth(self.token), timeout=self.timeout).text

        # print(html)
        # html = BeautifulSoup(, 'html.parser')
        # downloadLink = html.find('div', class_='dropdown_content')
        # print(downloadLink)

        # API
        try:
            video = self.get_video(video_id).json()
        except Exception as e:
            raise Exception(f"Failed to get video info for video ID: {video_id}, error: {e}")

        #Debug
        print(video)

        url = video['fileUrl']
        file_id = video['file']['id']
        expires = url.split('/')[4].split('?')[1].split('&')[0].split('=')[1]

        # IMPORTANT: This might change in the future.
        SHA_postfix = "_5nFp9kmbNnHdAFhaqMvt"

        SHA_key = file_id + "_" + expires + SHA_postfix
        hash = hashlib.sha1(SHA_key.encode('utf-8')).hexdigest()

        headers = {"X-Version": hash}

        resources = requests.get(url, headers=headers, auth=BearerAuth(self.token), timeout=self.timeout).json()
        
        #Debug
        print(resources)

        resources_by_quality = [None for i in range(10)]

        for resource in resources:
            if resource['name'] == 'Source':
                resources_by_quality[0] = resource
            # elif resource['name'] == '1080':
            #     resources_by_quality[1] = resource
            # elif resource['name'] == '720':
            #     resources_by_quality[2] = resource
            # elif resource['name'] == '480':
            #     resources_by_quality[3] = resource
            # elif resource['name'] == '540':
                # resources_by_quality[4] = resource
            # elif resource['name'] == '360':
                # resources_by_quality[5] = resource

        for resource in resources_by_quality:
            if resource is not None:
                #Debug
                print(resource)

                download_link = "https:" + resource['src']['download']
                file_type = resource['type'].split('/')[1]

                video_file_name = video_id + '.' + file_type

                if (os.path.exists(video_file_name)):
                    print(f"Video ID {video_id} Already downloaded, skipped downloading. ")
                    return video_file_name

                print(f"Downloading video ID: {video_id} ...")
                try:
                    with open(video_file_name, "wb") as f:
                        for chunk in requests.get(download_link).iter_content(chunk_size=1024):
                            if chunk:
                                f.write(chunk)
                                f.flush()
                    return video_file_name
                except Exception as e:
                    os.remove(video_file_name)
                    raise Exception(f"Failed to download video ID: {video_id}, error: {e}")

            
        raise Exception("No video with Source quality found")