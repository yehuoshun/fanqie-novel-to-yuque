# -*- coding: utf-8 -*-
"""
fanqie_tools.py — 番茄小说增强工具（简介/元数据获取）
========================================================
直接从番茄书籍页 HTML 提取元数据，无需第三方 API。
"""
import json
import re
import subprocess
import sys
import time


def curl_get(url, timeout=15):
    """HTTP GET 返回文本（带浏览器 UA）"""
    result = subprocess.run(
        ['curl', '-s', '-m', str(timeout),
         '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
         '-H', 'Referer: https://fanqienovel.com/',
         url],
        capture_output=True, text=True, timeout=timeout + 5
    )
    return result.stdout


def fetch_book_meta(book_id, search_key=None, retries=3):
    """
    直接从番茄书籍页 HTML 提取元数据（明文，无需字体解码）。
    页面 __INITIAL_STATE__ 里带 bookName/author/abstract 明文字段。
    """
    for attempt in range(1, retries + 1):
        html = curl_get(f"https://fanqienovel.com/page/{book_id}", timeout=20)
        if not html:
            print(f"⚠️ 页面无响应（第 {attempt}/{retries} 次）", file=sys.stderr)
            time.sleep(1)
            continue

        def _extract(p):
            m = re.search(p, html)
            return m.group(1) if m else ''

        book_name = _extract(r'"bookName":"([^"]*)"')
        author = _extract(r'"authorName":"([^"]*)"') or _extract(r'"author":"([^"]*)"')
        abstract = _extract(r'"abstract":"((?:[^"\\]|\\.)*)"')
        cover = _extract(r'"thumbUri":"([^"]*)"') or _extract(r'"thumb_url":"([^"]*)"')

        if book_name:
            if abstract:
                abstract = abstract.replace('\\n', ' ').replace('\\r', ' ').strip()
            return {
                'book_name': book_name,
                'author': author,
                'abstract': abstract,
                'cover': cover,
                'word_count': 0,
                'read_count': 0,
                'creation_status': None,
            }
        print(f"⚠️ 页面未解析到书名（第 {attempt}/{retries} 次）", file=sys.stderr)
    return None


def auto_fill_meta(book_id, title, author='', description=''):
    """
    自动补全书籍元数据：已有值保留，缺失值自动补（页面直抓）。
    """
    if author and description:
        return title, author, description
    meta = fetch_book_meta(book_id, search_key=title)
    if not meta:
        print("ℹ️ 未获取到该书元数据，保持手动传入值")
        return title, author, description
    if not author and meta.get('author'):
        author = meta['author']
        print(f"✅ 自动获取作者: {author}")
    if not description and meta.get('abstract'):
        description = meta['abstract']
        print(f"✅ 自动获取简介: {description[:60]}...")
    if not title and meta.get('book_name'):
        title = meta['book_name']
        print(f"✅ 自动获取书名: {title}")
    return title, author, description


if __name__ == '__main__':
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