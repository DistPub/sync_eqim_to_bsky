def main():
    response = requests.get('https://www.fjdzj.gov.cn/quakesearch.htm?time=oneday&sort=4,0')
    content = response.text()
    idx_start = content.index("eval('[")
    idx_end = content.index("]');")
    data = json.loads(content[idx_start:idx_end])
