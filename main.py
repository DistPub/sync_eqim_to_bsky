from argparse import ArgumentParser
from datetime import datetime, timedelta
import json
import random
import os

from atproto import Client, client_utils, models
from atproto.exceptions import BadRequestError
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

with open('oneday.json') as f:
    oneday = json.loads(f.read())

def git_commit():
    os.system('git config --global user.email "xiaopengyou@live.com"')
    os.system('git config --global user.name "robot auto"')
    os.system('git add .')
    os.system('git commit -m "update pre news time"')


def git_push():
    os.system('git push')

def main(opts):
    response = requests.get('https://www.fjdzj.gov.cn/quakesearch.htm?time=oneday&sort=4,0')
    content = response.text
    idx_start = content.index("eval('[")
    idx_end = content.index("]');")
    json_str = content[idx_start+6:idx_end+1]
    print(json_str)
    data = json.loads(json_str)
    print(data)
    new_id = []
    old_id = []
    for item in data:
        if item['id'][0]['value'] in oneday:
            old_id.append(item['id'][0]['value'])
            continue

        if item['S_msgType'][0]['value'] == '0':
            cate = '中国地震台网自动测定'
        else:
            cate = '中国地震台网正式测定'

        news = {
            'id': item['id'][0]['value'],
            'title': item['title'][0]['value'],
            'content': item['content'][0]['value'],
            'tags': ['EQIM', cate, f'{item["province"][0]["value"]}地震'],
            'time': item['pubDate'][0]['value'],
            'source': f'福建省地震局',
            'url': f"https://www.fjdzj.gov.cn/ar/{item['id'][0]['value']}.htm"
        }

        news['post'] = client_utils.TextBuilder().text(news['content']).text(f'\n{news["time"]} ').tag(news['source'], news['source']).text('\n')

        for tag in news['tags']:
            news['post'].tag(f'#{tag}', tag).text(' ')
        new_id.append(news)

    client = Client(base_url=opts.service if opts.service != 'default' else None)
    client.login(opts.username, opts.password)
    post_status_error = False
    sended_id = []
    for post in new_id:
        embed = models.AppBskyEmbedExternal.Main(
            external=models.AppBskyEmbedExternal.External(
                title=post['title'],
                description=post['content'],
                uri=post['url'],
                thumb=None,
            )
        )
        try:
            client.send_post(post['post'], embed=embed, langs=['zh'])
            sended_id.append(post['id'])
        except Exception as error:
            post_status_error = True
            print(f'error: {error} when handle post: {post["title"]} {post["url"]}')

    with open('oneday.json', 'w') as f:
        json.dump(old_id + sended_id, f, indent=4)

    if not opts.dev:
        git_commit()
        git_push()


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("--service", help="PDS endpoint")
    parser.add_argument("--username", help="account username")
    parser.add_argument("--password", help="account password")
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    main(args)
