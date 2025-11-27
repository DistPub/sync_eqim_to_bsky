from argparse import ArgumentParser
from datetime import datetime, timedelta
import json
import random
import os
from urllib.parse import quote, quote_plus, urlencode

from atproto import Client, client_utils, models
from atproto.exceptions import BadRequestError
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

import base64
import json
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

def decrypt_aes_base64(e: str,
                       key: str = "wenhePiCloudSecr",
                       iv:  str = "wenhePiCloudSecr"):
    """
    解密 AES-CBC-PKCS7，输入 Base64 密文，返回原文（能 JSON 则 dict，否则 str）
    """
    key_b = key.encode('utf-8')[:16]
    iv_b  = iv.encode('utf-8')[:16]

    cipher = AES.new(key_b, AES.MODE_CBC, iv_b)
    try:
        ct = base64.b64decode(e)
        pt = unpad(cipher.decrypt(ct), AES.block_size).decode('utf-8')
        return json.loads(pt)
    except Exception as exc:
        raise Exception(f'decode error: {exc}')


with open('oneday.json') as f:
    oneday = json.loads(f.read())


def action_in_progress(token):
    url = 'https://api.github.com/repos/DistPub/sync_eqim_to_bsky/actions/runs'
    path = 'update.yml'
    response = requests.get(url, headers={
        'Authorization': f'token {token}'
    }, params={'status': 'in_progress'})
    data = response.json()
    status_mismatch_ids = [
    ]
    runs = [item for item in data['workflow_runs'] if item['path'].endswith(path) and item['id'] not in status_mismatch_ids]
    if len(runs) < 2:
        return False

    return True


def git_commit():
    os.system('git config --global user.email "xiaopengyou@live.com"')
    os.system('git config --global user.name "robot auto"')
    os.system('git add .')
    os.system('git commit -m "update posted id"')


def git_push():
    os.system('git push')


def formatdate(strdate):
    return datetime.strptime(strdate, "%b %d, %Y %I:%M:%S %p").strftime("%Y-%m-%d %H:%M:%S")


def get_data(s, n=1):
    now = datetime.now()
    before = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    after = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    response = s.get((f'https://go.smitechow.com/www.fjdzj.gov.cn/api/home/obtain_earthquake_data?'
                      f'pageNum={n}&pageSize=30&'
                      f'timeRange={before},{after}'
                      f'&type=eqr'))
    response.raise_for_status()
    content = response.json()
    if content['code'] != 200:
        raise Exception(f'get data error: {content}')

    data = decrypt_aes_base64(content['msg'])
    data = data['list']

    if len(data) == 30:
        return data + get_data(s, n + 1)
    return data


def main(opts):
    if not opts.dev and action_in_progress(opts.gh_token):
        print(f'action in progress, skip')
        return
        
    s = requests.Session()
    retries = Retry(
        total=3,  # 总重试次数
        backoff_factor=1,  # 间隔时间因子，用于计算重试间隔时间
        status_forcelist=[101, 104],  # 遇到这些状态码时会触发重试
        allowed_methods=["GET"]  # 允许重试的方法
    )
    s.mount('https://', HTTPAdapter(max_retries=retries))
    data = get_data(s)

    new_id = []
    old_id = []
    for item in data:
        def val(name):
            return item[name]

        if val('id') in oneday:
            old_id.append(val('id'))
            continue

        if val('access_msg_type_text') != '正式报':
            cate = f'中国地震台网自动测定'
        else:
            cate = '中国地震台网正式测定'

        if val('lat')[0] == '-':
            weidu = f'南纬{val("lat")[1:]}度'
        else:
            weidu = f'北纬{val("lat")}度'

        if val('lng')[0] == '-':
            jingdu = f'西经{val("lng")[1:]}度'
        else:
            jingdu = f'东经{val("lng")}度'

        news = {
            'quakeTime': val('oritime'),
            'longitude': val('lng'),
            'latitude': val('lat'),
            'location': val('locname'),
            'focalDepth': val('s_depth'),
            'level': val('magnitude'),

            'id': val('id'),
            'title': f'{val("locname")}发生{val("magnitude")}级地震',
            'content': f'{cate}：{val("oritime")}，在{val("locname")}（{weidu},{jingdu}）发生{val("magnitude")}级地震，震源深度{val("s_depth")}千米。',
            'time': val('sendtime'),
            'source': f'国家地震科学数据中心',
            # 中国地震台网地震速报
            'tags': ['地震速报', cate, f'{val("locname")}地震'],
        }
        params = {
            'title': news['title'],
            'f_fzsj': news['quakeTime'],
            'f_jingdu': news['longitude'],
            'f_weidu': news['latitude'],
            'f_shendu': news['focalDepth'],
            'f_zhenji': news['level'],
            'f_didian': news['location']
        }
        news['url'] = f'https://data.earthquake.cn/datashare/sjfw/dzindex.jsp?{urlencode(params)}'
        news['post'] = client_utils.TextBuilder().text(news['content']).text(f'\n{news["time"]} ').tag(news['source'], news['source']).text('\n')

        for tag in news['tags']:
            news['post'].tag(f'#{tag}', tag).text(' ')
        new_id.append(news)

    if not new_id:
        print(f'skip, no news')
        return

    print(f'there are {len(new_id)} need to post')
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

    assert post_status_error == False


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("--service", help="PDS endpoint")
    parser.add_argument("--username", help="account username")
    parser.add_argument("--password", help="account password")
    parser.add_argument("--gh-token", help="gh token")
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    main(args)
