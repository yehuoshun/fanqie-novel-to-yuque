# -*- coding: utf-8 -*-
"""
fanqie_tools.py — 番茄小说增强工具（简介/元数据获取）
========================================================
番茄 reader/book 页面简介被字体加密 + 反爬挡死，但第三方 API 的搜索端点
`/api/search?key={书名}` 直接返回**明文**书籍信息（含简介 abstract）。

用法：
    meta = fetch_book_meta(book_id, search_key="书名")
    # -> {"book_name":..., "author":..., "abstract":..., "cover":..., "word_count":...}
"""
import json
import re
import subprocess
import sys
import time

API_BASE = "http://101.35.133.34:5000"


def curl_get(url, timeout=15):
    """HTTP GET 返回文本"""
    result = subprocess.run(
        ['curl', '-s', '-m', str(timeout), url],
        capture_output=True, text=True, timeout=timeout + 5
    )
    return result.stdout


def _walk_books(obj):
    """递归遍历搜索响应，产出所有书籍 dict"""
    if isinstance(obj, dict):
        if 'book_data' in obj and isinstance(obj['book_data'], list):
            for b in obj['book_data']:
                if isinstance(b, dict):
                    yield b
        for v in obj.values():
            yield from _walk_books(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_books(v)


def fetch_book_meta_from_page(book_id, timeout=20):
    """
    直接从番茄书籍页 HTML 提取元数据（明文，无需搜索接口/字体解码）。
    页面 __INITIAL_STATE__ 里带 bookName/author/abstract 明文字段。
    """
    url = f"https://fanqienovel.com/page/{book_id}"
    html = curl_get(url, timeout=timeout)
    if not html:
        return None

    def _extract(pattern):
        m = re.search(pattern, html)
        return m.group(1) if m else ''

    book_name = _extract(r'"bookName":"([^"]*)"')
    author = _extract(r'"authorName":"([^"]*)"')
    if not author:
        author = _extract(r'"author":"([^"]*)"')
    abstract = _extract(r'"abstract":"((?:[^"\\]|\\.)*)"')
    if abstract:
        # JSON 转义还原（\n 等）
        abstract = abstract.replace('\\n', ' ').replace('\\r', ' ').replace('\\t', ' ').strip()

    if not book_name:
        return None

    return {
        'book_name': book_name,
        'author': author,
        'abstract': abstract,
        'cover': _extract(r'"thumbUri":"([^"]*)"') or _extract(r'"thumb_url":"([^"]*)"'),
        'word_count': 0,
        'read_count': 0,
        'creation_status': None,
    }


def fetch_book_meta(book_id, search_key=None, retries=3):
    """
    获取番茄书籍元数据。优先直抓页面 HTML（快且稳），失败后回退搜索接口。
    """
    # 优先：页面直抓（无第三方依赖）
    meta = fetch_book_meta_from_page(book_id)
    if meta:
        return meta

    # 回退：搜索接口
    key = search_key or str(book_id)
    for attempt in range(1, retries + 1):
        url = f"{API_BASE}/api/search?key={key}"
        raw = curl_get(url, timeout=20)
        if not raw:
            print(f"⚠️ 搜索接口无响应（第 {attempt}/{retries} 次）", file=sys.stderr)
            time.sleep(1)
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            print(f"⚠️ 搜索接口返回非 JSON（第 {attempt}/{retries} 次）", file=sys.stderr)
            time.sleep(1)
            continue
        target = str(book_id)
        for book in _walk_books(payload):
            if str(book.get('book_id', '')) == target:
                return {
                    'book_name': book.get('book_name', ''),
                    'author': book.get('author', ''),
                    'abstract': (book.get('abstract') or book.get('book_abstract') or '').replace('\n', ' ').strip(),
                    'cover': book.get('thumb_url') or book.get('thumb_uri') or '',
                    'word_count': book.get('word_count', 0),
                    'read_count': book.get('read_count', 0),
                    'creation_status': book.get('creation_status'),
                }
        # 未匹配到目标书
        return None
    return None


def auto_fill_meta(book_id, title, author='', description=''):
    """
    自动补全书籍元数据：已有值保留，缺失值自动补（页面直抓优先）。

    :return: (title, author, description) 三元组
    """
    # 作者和简介都已提供时，跳过抓取，避免浪费时间
    if author and description:
        return title, author, description
    meta = fetch_book_meta(book_id, search_key=title)
    if not meta:
        print("ℹ️ 未获取到该书元数据，保持手动传入值")
        return title, author, description
    if not author:
        author = meta['author']
        print(f"✅ 自动获取作者: {author}")
    if not description and meta['abstract']:
        description = meta['abstract']
        print(f"✅ 自动获取简介: {description[:60]}...")
    if not title:
        title = meta['book_name']
        print(f"✅ 自动获取书名: {title}")
    return title, author, description


if __name__ == '__main__':
    # 自测：python3 fanqie_tools.py 7457108578311097369 "玄幻：提取万物词条，弟子全是妖孽！"
    if len(sys.argv) < 2:
        print("用法: python3 fanqie_tools.py <book_id> [search_key]")
        sys.exit(1)
    bid = sys.argv[1]
    key = sys.argv[2] if len(sys.argv) > 2 else bid
    m = fetch_book_meta(bid, search_key=key)
    if m:
        print(json.dumps(m, ensure_ascii=False, indent=2))
    else:
        print("未获取到元数据")
