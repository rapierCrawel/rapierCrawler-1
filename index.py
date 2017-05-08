import json
import time
import random
import pymongo

from urllib import parse
from urllib import error
from urllib import request
from datetime import datetime
from http.client import IncompleteRead
from socket import timeout as socket_timeout
from time import sleep

from bs4 import BeautifulSoup


def _get_query_string(data):
    """
    将查询参数编码为 url，例如：
    data = {
            'offset': offset,
            'format': 'json',
            'keyword': '人民的名义',
            'autoload': 'true',
            'count': 20,
            '_': 1480675595492
    }
    则返回的值为：
    ?offset=20&format=json&keyword=%E4%BA%BA%E6%B0%91%E7%9A%84%E5%90%8D%E4%B9%89&autoload=true&count=20&_=1480675595492"
    """
    return parse.urlencode(data)

def _get_timestamp():
    """
    向 http://www.toutiao.com/search_content/ 发送的请求的参数包含一个时间戳，
    该函数获取当前时间戳，并格式化成头条接收的格式。格式为 datetime.today() 返回
    的值去掉小数点后取第一位到倒数第三位的数字。
    """
    row_timestamp = str(datetime.timestamp(datetime.today()))
    return row_timestamp.replace('.', '')[:-3]

def get_article_urls(req, timeout=10):
    with request.urlopen(req, timeout=timeout) as res:
        d = json.loads(res.read().decode()).get('data')

        if d is None:
            print("数据全部请求完毕...")
            return

        urls = [article.get('article_url') for article in d if article.get('article_url')]
        return urls


def get_contents(req, timeout=10):
    with request.urlopen(req, timeout=timeout) as res:
        # 这里 decode 默认为 utf-8 编码，但返回的内容中含有部分非 utf-8 的内容，会导致解码失败
        # 所以我们使用 ignore 忽略这部分内容
        soup = BeautifulSoup(res.read().decode(errors='ignore'), 'html.parser')
        article_main = soup.find('div', id='article-main')

        if not article_main:
            print("无法定位到文章主体...")
            return

        heading = article_main.h1.string

        if '人民的名义' not in heading:
            print("这不是《人民的名义》的文章！！！")
            return

        content_list = [content.string for content in article_main.find_all('p') if content.string]

        for content in article_main.find_all('p'):
            if (content.find('img') is None):
                content_list.append(content.contents[0].string)
            else :
                text = content.contents[0].string
                image = content.find('img').get('src')
                imagewidth = content.find('img').get('img_width')
                imageHeight = content.find('img').get('img_height')
                content_list.append(text)
                content_list.append("imageUrl:" + image + ";width=" + imagewidth + ";height=" + imageHeight)

        return heading, content_list


def save_article(a_content, hearding, db, timeout=10):

    article = db.article.find_one({"title":hearding})

    if article is None:
        article = {"title":hearding,
                   "content":[a_content]}
        db.article.insert(article)
        return

    db.article.update({"title":hearding},{"$push":{"content":a_content}})


if __name__ == '__main__':
    ongoing = True
    offset = 0  # 请求的偏移量，每次累加 20
    request_headers = {
        'Referer': 'http://www.toutiao.com/search/?keyword=%E4%BA%BA%E6%B0%91%E7%9A%84%E5%90%8D%E4%B9%89',
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_4) AppleWebKit/537.36 '
                      '(KHTML, like Gecko) Chrome/57.0.2987.133 Safari/537.36'
    }
    uri = "mongodb://localhost:27017"
    client = pymongo.MongoClient(uri)
    db = client.guyan

    while ongoing:
        query_data = {
            'offset': offset,
            'format': 'json',
            'keyword': '人民的名义',
            'autoload': 'true',
            'count': 20,  # 每次返回 20 篇文章
            'cur_tab': 1
        }
        query_url = 'http://www.toutiao.com/search_content/' + '?' + _get_query_string(query_data)
        article_req = request.Request(query_url, headers=request_headers)
        article_urls = get_article_urls(article_req)

        # 如果不再返回数据，说明全部数据已经请求完毕，跳出循环
        if article_urls is None:
            break

        # 开始向每篇文章发送请求
        for a_url in article_urls:
            # 请求文章时可能返回两个异常，一个是连接超时 socket_timeout，
            # 另一个是 HTTPError，例如页面不存在
            # 连接超时我们便休息一下，HTTPError 便直接跳过。
            try:
                article_req = request.Request(a_url, headers=request_headers)
                article_contents = get_contents(article_req)

                # 文章中没有正文？跳到下一篇文章
                if article_contents is None:
                    continue

                article_heading, article_contents = article_contents

                # 开始保存文章正文
                for a_content in article_contents:
                    # 由于数据以分段形式返回，在接收数据时可能抛出 IncompleteRead 异常
                    try:
                        save_article(a_content, article_heading, db)
                    except IncompleteRead as e:
                        print(e)
                        continue
            except socket_timeout:
                print("连接超时了，休息一下...")
                time.sleep(random.randint(15, 25))
                continue
            except error.HTTPError:
                continue

        # 一次请求处理完毕，将偏移量加 20，继续获取新的 20 篇文章。
        offset += 20
        sleep(20)