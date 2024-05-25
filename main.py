
import json
import os
import sqlite3
import sys
import time
from datetime import datetime
from typing import List, Optional

import cv2
from api.api_client import ApiClient
from dateutil.relativedelta import relativedelta
from telegram.ext import Updater


class IwaraTgBot:
    def __init__(self, ecchi=False):
        self.rating = "ecchi" if ecchi else "general"
        self.authors = set()  # 用于存储所有作者
        self.author_tags_message_id = None  # 存储标签合集消息的ID
        self.authors_file = "authors.json"
        self.load_authors()  # 从文件加载作者列表
        self.author_tags_message_id_file = "author_tags_message_id.txt"
        self.load_author_tags_message_id()
        # Load Config
        self.config = json.load(open("config.json"))
        self.videoUrl = "https://iwara.tv/video"
        self.userUrl = "https://iwara.tv/profile"

        # Setup Iwara API Client
        self.client = ApiClient(
            self.config["user_info"]["user_name"], self.config["user_info"]["password"])

        # Init DB
        self.DBpath = "IwaraTgDB.db"

        # Setup telegram bot
        print("Connecting to telegram bot...")
        self.updater = Updater(
            self.config["telegram_info"]["token"], base_url=self.config["telegram_info"]["APIServer"])
        self.bot = self.updater.bot
        botInfo = self.bot.getMe()
        print("Connected to telegram bot: " + botInfo.first_name)

    def login(self) -> bool:
        """ Login to iwara.tv """

        # Login
        print("Logging in...")
        r = self.client.login()

        if r.status_code == 200:
            print("Login success")
            return True
        else:
            print("Login failed")
            return False

    def connect_DB(self):
        conn = sqlite3.connect(self.DBpath)
        c = conn.cursor()
        return c, conn

    def close_DB(self, conn):
        conn.commit()
        conn.close()

    def init_DB(self, tableName):
        c, conn = self.connect_DB()

        c.execute("""CREATE TABLE IF NOT EXISTS """ + tableName + """ (
            id TEXT PRIMARY KEY,
            title TEXT,
            user TEXT,
            user_display TEXT,
            date TEXT,
            chat_id INTEGER,
            views INTEGER,
            likes INTEGER
        )""")

        self.close_DB(conn)

    def update_author_tags(self, user_display):
       if user_display not in self.authors:
           self.authors.add(user_display)
           self.save_authors()  # 保存作者列表到文件
           self.send_author_tags()

    def load_authors(self):
        try:
            with open(self.authors_file, "r") as f:
                self.authors = set(json.load(f))
        except (FileNotFoundError, json.JSONDecodeError):
            self.authors = set()

    def save_authors(self):
        with open(self.authors_file, "w") as f:
            json.dump(list(self.authors), f, indent=4)

    def load_author_tags_message_id(self):
        try:
            with open(self.author_tags_message_id_file, "r") as f:
                self.author_tags_message_id = int(f.read().strip())
        except (FileNotFoundError, ValueError):
            self.author_tags_message_id = None

    def save_author_tags_message_id(self):
        with open(self.author_tags_message_id_file, "w") as f:
            f.write(str(self.author_tags_message_id))

    def update_author_tags(self, user_display):
        if user_display not in self.authors:
            self.authors.add(user_display)
            self.save_authors()  # 保存作者集合到文件
            self.send_author_tags()

    def send_author_tags(self):
        max_length = 120  # 每行的最大长度
        current_length = 0
        message = "作者:\n"

        for author in sorted(self.authors):
            tag = f"#{author.replace(' ', '_')}    "  # 在标签后添加4个空格

            if current_length + len(tag) > max_length:
                message += "\n"
                current_length = 0
            message += tag
            current_length += len(tag)

        if self.author_tags_message_id is None:
            msg = self.bot.send_message(chat_id=self.config["telegram_info"]["chat_id"],
                                        text=message)
            self.author_tags_message_id = msg.message_id
            self.save_author_tags_message_id()
        else:
            try:
                self.bot.edit_message_text(chat_id=self.config["telegram_info"]["chat_id"],
                                           message_id=self.author_tags_message_id,
                                           text=message)
            except telegram.error.BadRequest as e:
                if str(e).startswith("Message is not modified"):
                    print("Author tags message not modified, skipping edit.")
                else:
                    raise e

    def save_video_info(self, tableName, id, title=None, user=None, user_display=None, chat_id=None, views=None, likes=None):
        """
        Save video info to database.
        """
        c, conn = self.connect_DB()

        c.execute("""INSERT INTO """ + tableName + """ (id, title, user, user_display, date, chat_id, views, likes) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
                  (id, title, user, user_display, int(datetime.now().strftime("%Y%m%d")), chat_id, views, likes,))

        self.close_DB(conn)

    def is_video_exist(self, tableName, id):
        c, conn = self.connect_DB()

        c.execute("SELECT * FROM " + tableName + " WHERE id = ?", (id,))
        if c.fetchone() is None:
            result = False
        else:
            result = True

        self.close_DB(conn)

        return result

    def get_video_info(self, id):
        """# Extract video info from video object
        """

        try:
            video = self.client.get_video(id).json()
        except Exception as e:
            raise e

        title = video["title"]
        user = video["user"]['username']
        user_display = video["user"]['name']
        description = video['body']
        tags = [user_display]
        for tag in video["tags"]:
            tags.append(tag["id"])

        thumbFileName = video["id"] + ".jpg"

        return [title, user, user_display, description, tags, thumbFileName]

    def get_video_stat(self, video):
        """# Extract video stats from video object
        """

        likes = int(video['numLikes'])
        views = int(video['numViews'])

        return [likes, views]

    def find_videos(self, subscribed=False, num_pages=5) -> List:
        print("Finding videos... (rating: {}, subscribed: {})".format(
            self.rating, subscribed))

        if (subscribed and self.client.token == None):
            raise Exception("Not logged in!")

        videos = []

        for page in range(num_pages):
            try:
                videos += (self.client.get_videos(sort='date', rating=self.rating,
                           page=page, subscribed=subscribed).json()['results'])
            except Exception as e:
                print("Error: {}".format(e))

        return videos

    def download_video(self, id) -> Optional[str]:
        try:
            print("Downloading video {}...".format(id))
            return self.download_with_retry(self.client.download_video, id)
        except Exception as e:  # Download Failed
            print("Download Failed: {}".format(e))
            return None

    def download_video_thumbnail(self, id) -> Optional[str]:
        try:
            print("Downloading thumbnail for video {}...".format(id))
            return self.download_with_retry(self.client.download_video_thumbnail, id)
        except Exception as e:  # Download Failed
            print("Download Thumbnail Failed: {}".format(e))
            return None

    def download_with_retry(self, download_func, *args, max_retries=3, delay=1, **kwargs):
        for attempt in range(max_retries):
            try:
                return download_func(*args, **kwargs)
            except Exception as e:
                if attempt < max_retries - 1:
                    print(
                        f"Download failed: {e}. Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    print(
                        f"Download failed after {max_retries} attempts. Giving up.")
                    raise

    def get_youtube_link(self, video) -> Optional[str]:
        try:
            return video["embedUrl"]
        except:
            return None

    def send_yt_link(self, yt_link, id="", title="", user="", user_display="", description="", v_tags=[]):

        # yt_link = "https://www.youtube.com/watch?v=" + yt_id

        try:
            chat_ad = self.config["telegram_info"]["chat_ad"]
        except:
            chat_ad = ""

        caption = yt_link + """
<a href="{}/{}/">{}</a>
by: <a href="{}/{}/">{}</a>
{}
""".format(self.videoUrl, id, title, self.userUrl, user, user_display, chat_ad)
        for v_tag in v_tags:
            caption += " #" + v_tag

        msg = None

        try:
            msg = self.bot.send_message(
                chat_id=self.config["telegram_info"]["chat_id"], text=caption, parse_mode="HTML")
        except:
            msg = self.bot.send_message(
                chat_id=self.config["telegram_info"]["chat_id"], text=caption)

        return msg.message_id

    def send_video(self, path, id="", title="", user="", user_display="", description=None, v_tags=None, thumbPath=""):
        description = "" if description is None else description
        v_tags = [] if v_tags is None else v_tags
        # 定义黑名单列表
        blacklist = ["支付宝", "微信", "qq", "patreon", "paypal", "网址", "support", "支持", "群", "公告",
                     "永久", "QQ",  "定制", "高清", "4k", "视频", "fanbox", "链接", "Support"]  # 根据你的需求添加黑名单词汇

        # 检查描述是否包含黑名单中的词汇
        if any(word in description for word in blacklist):
            print(
                f"Video ID {id} contains blacklisted words in description. Removing description...")
            description = ""  # 如果描述中包含黑名单词汇,将描述设为空字符串

        # Sending video to telegram
        print("Sending video {} to telegram...".format(path))

        try:
            chat_ad = self.config["telegram_info"]["chat_ad"]
        except:
            chat_ad = ""

        try:
            cap = cv2.VideoCapture(path)
            height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            duration = frame_count / fps
        # 根据视频分辨率添加标签
            resolution_tag = ""
            if height >= 2160:
               resolution_tag = "4K"
            elif height >= 1080:
               resolution_tag = "1080p"
            elif height >= 720:
               resolution_tag = "720p"
        # 检查视频比例是否为竖屏
            orientation_tag = ""
            if height > width:
               orientation_tag = "PortraitScreen"

            caption = """
<a href="{}/{}/">{}</a>
by: <a href="{}/{}/">{}</a>
{}
""".format(self.videoUrl, id, title, self.userUrl, user, user_display, description)
            if description:
                caption += "\n\n" + description

                caption += "\n\n" + chat_ad

            if user_display:
                # 将作者名字中的空格替换为下划线,作为一个完整的标签
                caption += "\n#" + user_display.replace(" ", "_")

            if resolution_tag:
                caption += "\n#" + resolution_tag

            if orientation_tag:
                caption += "\n#" + orientation_tag

            msg = None

            try:
                msg = self.bot.send_video(chat_id=self.config["telegram_info"]["chat_id"],
                                          video=open(path, 'rb'),
                                          supports_streaming=True,
                                          timeout=300,
                                          height=height,
                                          width=width,
                                          duration=duration,
                                          caption=caption,
                                          # Thumbnail
                                          thumb=open(thumbPath, 'rb'),
                                          parse_mode="HTML")
            except:
                msg = self.bot.send_video(chat_id=self.config["telegram_info"]["chat_id"],
                                          video=open(path, 'rb'),
                                          supports_streaming=True,
                                          timeout=300,
                                          height=height,
                                          width=width,
                                          duration=duration,
                                          caption=caption,
                                          # Thumbnail
                                          thumb=open(thumbPath, 'rb'),
                                          )

            # Delete the video form server
            os.remove(thumbPath)
            os.remove(path)

            return msg.message_id

        except Exception as e:
            # Delete the video form server
            os.remove(thumbPath)
            os.remove(path)
            raise e

    def send_description(self, user, user_display, description):
        msg_t = self.bot.send_message(
            chat_id=self.config["telegram_info"]["chat_id_discuss"], text="Getting message ID...")
        self.bot.delete_message(
            chat_id=self.config["telegram_info"]["chat_id_discuss"], message_id=msg_t.message_id)

        msg_description = """
<a href="{}/{}/">{}</a> said:
""".format(self.userUrl, user, user_display) + ("" if (description == None) else description)

        try:
            self.bot.send_message(chat_id=self.config["telegram_info"]["chat_id_discuss"],
                                  text=msg_description, parse_mode="HTML", reply_to_message_id=msg_t.message_id - 1)
        except:
            self.bot.send_message(chat_id=self.config["telegram_info"]["chat_id_discuss"],
                                  text=msg_description, reply_to_message_id=msg_t.message_id - 1)

    def update_stat_after(self, date, tableName):
        c, conn = self.connect_DB()

        c.execute("""SELECT id FROM """ + tableName +
                  " WHERE date >= ?", (date,))
        entries = c.fetchall()

        for (id,) in entries:
            try:
                # Debug
                print("Updating video ID {}".format(id))

                video = self.client.get_video(id).json()

                # Debug
                print(video)

                (likes, views) = self.get_video_stat(video)

                # Debug
                print(id)
                print(likes, views)

                c.execute("""UPDATE """ + tableName +
                          " SET likes = ?, views = ? WHERE id = ?", (likes, views, id))
            except Exception as e:
                print("Error: {}".format(e))
                pass

        self.close_DB(conn)

    def download(self, subscribed=False):

        tableName = "videosNew" if subscribed == False else "videosSub"

        self.init_DB(tableName)

        if (not self.login()):
            print("Login Failed")
            return

        videos = self.find_videos(subscribed=subscribed)

        # Download videos
        for video in reversed(videos):

            id = video['id']

            print("Found video ID {}".format(id))

            if (self.is_video_exist(tableName, id)):
                print("Video ID {} Already sent, skipped. ".format(id))
                continue

            try:
                video_info = self.get_video_info(id)
            except Exception as e:
                print("Error in getting video info: {}".format(e))
                continue

            print("[DEBUG] Video ID {} Info: ".format(id))
            print(video_info)

            yt_link = self.get_youtube_link(video)

            title = video_info[0]
            user = video_info[1]
            user_display = video_info[2]
            description = video_info[3]
            v_tags = video_info[4]

            if (yt_link == None):
                videoFileName = self.download_video(id)

                if (videoFileName == None):
                    print("Video ID {} Download failed, skipped. ".format(id))
                    continue

                thumbFileName = self.download_video_thumbnail(id)

                if (thumbFileName == None):
                    print("Video ID {} Thumbnail Download failed, skipped. ".format(id))
                    continue

                try:
                    msg_id = self.send_video(
                        videoFileName, id, title, user, user_display, description, v_tags, thumbFileName)
                except Exception as e:
                    print("Error in sending video: {}".format(e))
                    continue
            else:

                msg_id = self.send_yt_link(
                    yt_link, id, title, user, user_display, description, v_tags)

            self.save_video_info(tableName, id, title,
                                 user, user_display, msg_id)
            user_display = video_info[2]
            self.update_author_tags(user_display)  # 直接使用user_display更新作者集合
            # Wait for telegram to forward the video to the group
            time.sleep(5)

            self.save_authors()  # 下载完成后保存作者列表
            if "chat_id_discuss" in self.config["telegram_info"]:
                self.send_description(
                    user=user, user_display=user_display, description=description)

    def send_ranking(self, title, entries):

        ranking_description = f"""#{title}
"""

        for i in range(1, len(entries)+1):
            (title, user_display, chat_id, likes, views, heats,) = entries[i-1]
            ranking_description += f"""
Top {i} ❤️{likes} 🔥{views}
<a href="https://t.me/iwara2/{chat_id}">{title}</a> by {user_display}"""

        try:
            self.bot.send_message(
                chat_id=self.config["telegram_info"]["ranking_id"], text=ranking_description, parse_mode="HTML")
        except:
            self.bot.send_message(
                chat_id=self.config["telegram_info"]["ranking_id"], text=ranking_description)

    def ranking(self, type="DAILY"):

        tableName = "videosNew"

        today = datetime.today()
        yesterday = today - relativedelta(days=1)
        oneweekago = today - relativedelta(days=7)
        onemonthago = today - relativedelta(months=1)
        oneyearago = today - relativedelta(years=1)

        date = None
        title = None
        if (type == "DAILY"):
            date = yesterday
            title = f"""Daily Ranking 每日排行榜
""" + today.strftime("%Y-%m-%d")
        elif (type == "WEEKLY"):
            date = oneweekago
            title = """Weekly Ranking 每周排行榜
""" + oneweekago.strftime("%Y-%m-%d") + " ~ " + today.strftime("%Y-%m-%d")
        elif (type == "MONTHLY"):
            date = onemonthago
            title = """Monthly Ranking 月度排行榜
""" + onemonthago.strftime("%Y-%m")
        elif (type == "YEARLY"):
            date = oneyearago
            title = """Annual Ranking 年度排行榜
""" + oneyearago.strftime("%Y")

        if (date != None):

            self.login()

            print("Fetching video stats...")

            self.update_stat_after(date.strftime("%Y%m%d"), tableName)

            c, conn = self.connect_DB()

            c.execute("""SELECT title, user_display, chat_id, likes, views, likes * 20 + views as heats FROM """ +
                      tableName + " WHERE date >= ? ORDER BY heats DESC", (date.strftime("%Y%m%d"),))
            entries = c.fetchmany(10)

            # c.execute("""SELECT title, user_display, chat_id, views FROM """ + tableName + " WHERE date >= ? ORDER BY views DESC", (date.strftime("%Y%m%d"),))
            # entries_views = c.fetchmany(5)

            self.close_DB(conn)

            self.send_ranking(title, entries)


if __name__ == '__main__':
    args = sys.argv

    def usage():
        print("""
Usage: python {} <mode> <option>
mode can be:
\t -n/normal: normal mode
\t -e/ecchi: ecchi mode (NSFW)
option can be:
\t dlsub: download the latest page of your subscription list
\t dlnew: download the latest page of the new videos
\t rank -d/-w/-m/-y: send daily/weekly/monthly/annually ranking of your database

        """.format(args[0]))
        exit(1)

    if (len(args) < 2 or len(args) > 4):
        usage()

    if (args[1] == "-n" or args[1] == "normal"):
        bot = IwaraTgBot()
    elif (args[1] == "-e" or args[1] == "ecchi"):
        bot = IwaraTgBot(ecchi=True)
    else:
        usage()

    if (args[2] == "dlsub"):
        bot.download(subscribed=True)
    elif (args[2] == "dlnew"):
        bot.download()
    elif (args[2] == "rank"):
        if (args[3] == "-d"):
            bot.ranking("DAILY")
        elif (args[3] == "-w"):
            bot.ranking("WEEKLY")
        elif (args[3] == "-m"):
            bot.ranking("MONTHLY")
        elif (args[3] == "-y"):
            bot.ranking("YEARLY")
        else:
            usage()
    else:
        usage()
