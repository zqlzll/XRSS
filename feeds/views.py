import asyncio
import datetime
import json
import pathlib
import re

import aiohttp
import feedparser
from django.shortcuts import render
from googletrans import Translator

CONFIG_DIR = "Data"

translator = Translator(service_urls=[
    'translate.google.com',
    'translate.google.co.kr',
])


async def translate_title(title):
    return await asyncio.to_thread(translator.translate, title, "zh-CN")


def get_category_from_url(feed_url):
    # 从URL中提取分类部分
    pattern = r'https://www.reddit.com/r/(.+)\.rss'
    match = re.match(pattern, feed_url)
    return match.group(1)


def get_config_path(feed_url):
    category = get_category_from_url(feed_url)
    return pathlib.Path(CONFIG_DIR) / f"{category}.json"


def load_config(feed_url):
    config_path = get_config_path(feed_url)
    print(f"---config_path:{config_path}")

    if not config_path.exists():
        print("----退出了吗？")
        return {}, (0, 0),

    with open(config_path, "r") as f:
        config = json.load(f)
        last_modified = config.get("last_modified")
        etag = config.get("etag")
        post_dict = config.get("post_dict", {})

    return post_dict, (last_modified, etag)


def save_config(feed_url, last_modified, etag, post_dict):
    config_path = get_config_path(feed_url)

    if not config_path.parent.exists():
        config_path.parent.mkdir(parents=True)

    with open(config_path, "w") as f:
        config = {"last_modified": last_modified,
                  "etag": etag,
                  "post_dict": post_dict}
        json.dump(config, f)


async def fetch_feed_data(feed_url, last_modified=None, etag=None):
    print("---run fetch_feed_data")
    headers = {}
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    if etag:
        headers["If-None-Match"] = etag

    async with aiohttp.ClientSession(trust_env=True) as session:
        async with session.get(feed_url, headers=headers) as response:
            print(f"---status:{response.status}")
            if response.status == 304:
                return (), last_modified, etag

            data = await response.text()
            new_last_modified = response.headers.get("Last-Modified")
            new_etag = response.headers.get("ETag")

            print(f"Modified:{new_last_modified}, etag:{new_etag}")

            return data, new_last_modified, new_etag


async def get_feed_data(feed_url):
    post_list = []
    post_dict = {}

    post_dict, (last_modified, etag) = load_config(feed_url)

    # 如果本地已缓存有post_dict, 直接返回
    if post_dict:
        return post_dict

    feed_data, new_last_modified, new_etag = await fetch_feed_data(
        feed_url, last_modified=last_modified, etag=etag
    )

    if not feed_data:
        return post_dict

    feed_data = feedparser.parse(feed_data)

    try:
        feed_label = "r/" + feed_data.feed.category
    except AttributeError:
        feed_label = "N/A"

    for entry in feed_data.entries:
        zh_title = entry.title
        if isinstance(zh_title, str):
            try:
                zh_title = await translate_title(entry.title)
                zh_title = zh_title.text
            except Exception as e:
                print(f"Error when translating: {e}")
                zh_title = entry.title
        else:
            print("Invalid title format!")

        dt = datetime.datetime.fromisoformat(entry.updated)
        formatted_date = dt.strftime("%Y/%m/%d %H:%M:%S")
        post_list.append({"title": zh_title, "updated": formatted_date, "link": entry.link})

    post_dict[feed_label] = post_list

    save_config(feed_url, new_last_modified, new_etag, post_dict)
    # print(f"----psot_dict:{post_dict}")
    return post_dict

async def get_all_feeds(urls):
    tasks = [get_feed_data(url) for url in urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    content_dict = {}
    for result in results:
        if isinstance(result, dict):
            content_dict.update(result)

    return content_dict


def async_to_sync(async_func):
    def wrapper(request, *args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(async_func(request, *args, **kwargs))
        loop.close()
        return result

    return wrapper

@async_to_sync
async def show_feeds(request):
    urls = ["https://www.reddit.com/r/todayilearned.rss", "https://www.reddit.com/r/LifeProTips.rss"]
    content_dict = await get_all_feeds(urls)
    LifeProTips = content_dict.get("r/LifeProTips", [])
    return render(request, "index.html", {"LifeProTips_dict": LifeProTips})

