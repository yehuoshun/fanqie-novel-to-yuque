#!/usr/bin/env python3
"""Final import: fetch full novel chapters via direct fanqie scraping + charset decode, upload to Yuque"""
import json
import subprocess
import re
import sys
import os
import time

# --- 配置加载 ---
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        cfg = json.load(f)
    if os.environ.get('BOOK_ID'):
        cfg['yuque_repo_id'] = os.environ['BOOK_ID']
    return cfg

CONFIG = load_config()
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
BOOK_ID = CONFIG['yuque_repo_id']
PROGRESS_FILE = os.path.join(PROJECT_DIR, CONFIG['progress_file'])
CHAPTER_LIST = CONFIG['chapter_list']
MIN_CONTENT_LEN = CONFIG.get('min_content_length', 500)
WARN_CONTENT_LEN = CONFIG.get('warning_content_length', 1000)
API_INTERVAL = CONFIG.get('api_interval', 0.5)

# --- charset 解码 ---
_FONT_DIR = os.path.join(PROJECT_DIR, 'fonts')
_CHARSET_CACHE = None

def _load_charset():
    global _CHARSET_CACHE
    if _CHARSET_CACHE:
        return _CHARSET_CACHE
    charset_path = os.path.join(PROJECT_DIR, 'charset.json')
    if not os.path.exists(charset_path):
        # 备用：从 fanqie-server 目录获取
        alt = os.path.join(os.path.dirname(PROJECT_DIR), 'fanqie-server', 'charset.json')
        if os.path.exists(alt):
            charset_path = alt
        else:
            print("❌ charset.json 未找到，请从 code/fanqie-server/ 复制过来")
            sys.exit(1)
    with open(charset_path, 'r', encoding='utf-8-sig') as f:
        _raw = json.load(f)
    CS = _raw if isinstance(_raw, list) else _raw.get('charset', [])
    CODE = [[58344, 58715], [58345, 58716]]
    _CHARSET_CACHE = (CS, CODE)
    return _CHARSET_CACHE

def decode_text(text):
    CS, CODE = _load_charset()
    result = []
    for ch in text:
        cp = ord(ch)
        decoded = False
        for i, (lo, hi) in enumerate(CODE):
            if lo <= cp <= hi:
                idx = cp - lo
                result.append(CS[i][idx] if idx < len(CS[i]) else ch)
                decoded = True
                break
        if not decoded:
            result.append(ch)
    return ''.join(result)

# --- mcporter 调用 ---
MCP_WORKDIR = '/home/admin/.openclaw/workspace'

def create_yuque_doc(title, body):
    """通过 mcporter 调 yuque-mcp 创建文档"""
    args = json.dumps({
        "book_id": BOOK_ID, "title": title, "body": body,
        "format": "markdown", "public": 0
    }, ensure_ascii=False)
    result = subprocess.run(
        ['mcporter', 'call', 'yuque-mcp.yuque_create_doc', '--args', args],
        capture_output=True, text=True, timeout=30, cwd=MCP_WORKDIR
    )
    output = result.stdout.strip() or result.stderr.strip()
    try:
        data = json.loads(output)
        if isinstance(data, dict) and data.get('id'):
            return data['id'], None
        return None, str(data)[:100]
    except json.JSONDecodeError:
        return None, f"parse: {output[:200]}"

# --- 内容获取 ---
def get_chapter_content(item_id, max_retries=3):
    """从 reader 页获取全文，charset 解码"""
    for attempt in range(1, max_retries + 1):
        html = subprocess.run([
            'curl', '-s', '-m', '15',
            '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            '-H', 'Referer: https://fanqienovel.com/',
            f"https://fanqienovel.com/reader/{item_id}"
        ], capture_output=True, text=True, timeout=20).stdout

        if not html:
            if attempt < max_retries:
                print(f"重试第{attempt}次(空)...", end='', flush=True)
                time.sleep(2)
                continue
            return None

        m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\});', html, re.DOTALL)
        if not m:
            if attempt < max_retries:
                print(f"重试第{attempt}次(无数据)...", end='', flush=True)
                time.sleep(2)
                continue
            return None

        try:
            data = json.loads(m.group(1))
            cd = data.get('reader', {}).get('chapterData', {})
            content = cd.get('content', '')
            # 提取 <p> 段落并解码
            paragraphs = re.findall(r'<p>(.*?)</p>', content, re.DOTALL)
            lines = []
            for p in paragraphs:
                t = decode_text(p.strip())
                if t:
                    lines.append(f"&emsp;&emsp;{t}")
                else:
                    lines.append("")
            result = '\n'.join(lines)
            if len(result) >= MIN_CONTENT_LEN:
                return result
            if attempt < max_retries:
                print(f"重试第{attempt}次({len(result)}字)...", end='', flush=True)
                time.sleep(2)
        except Exception as e:
            if attempt < max_retries:
                print(f"重试第{attempt}次({e})...", end='', flush=True)
                time.sleep(2)
    return None

# --- 进度管理 ---
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {"completed": [], "failed": []}

def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)

def _is_progress_contaminated(chapters, progress):
    completed = progress.get("completed", [])
    if not completed:
        return False
    current_titles = {t for t, _ in chapters}
    matches = sum(1 for t in completed[:10] if t in current_titles)
    return matches == 0

# --- main ---
def main():
    import argparse
    from reorder_toc import reorder
    parser = argparse.ArgumentParser(description='批量导入番茄小说到语雀')
    parser.add_argument('--start', type=int, default=1)
    parser.add_argument('--end', type=int, default=0)
    args = parser.parse_args()

    with open(CHAPTER_LIST, 'r', encoding='utf-8') as f:
        chapters = json.load(f)

    total_all = len(chapters)
    start_idx = args.start - 1
    end_idx = args.end if args.end > 0 else total_all
    chapters_range = chapters[start_idx:end_idx]
    total = len(chapters_range)

    progress = load_progress()
    if _is_progress_contaminated(chapters, progress):
        print(f"🧹 进度文件被旧数据污染，已清空（旧记录 {len(progress.get('completed', []))} 条）")
        progress = {"completed": [], "failed": []}
        save_progress(progress)
    completed_set = set(progress.get("completed", []))
    failed_set = set(progress.get("failed", []))

    print(f"共 {total_all} 章，范围 {args.start}-{end_idx} ({total} 章)，已导入 {len(completed_set)} 章，失败 {len(failed_set)} 章", flush=True)
    start_time = time.time()
    new_success = 0
    new_failed = 0

    for abs_i, (title, url) in enumerate(chapters_range, args.start):
        if title in completed_set:
            continue
        print(f"[{abs_i}/{total_all}] {title}...", end=' ', flush=True)

        item_id = url.split('/reader/')[-1]
        try:
            text = get_chapter_content(item_id)
        except Exception as e:
            print(f"❌ {e}", flush=True)
            failed_set.add(title)
            new_failed += 1
            save_progress({"completed": list(completed_set), "failed": list(failed_set)})
            continue

        if not text or len(text) < MIN_CONTENT_LEN:
            print(f"❌ 内容过短({len(text) if text else 0}字)", flush=True)
            failed_set.add(title)
            new_failed += 1
            save_progress({"completed": list(completed_set), "failed": list(failed_set)})
            continue

        content_len = len(text)
        if content_len < WARN_CONTENT_LEN:
            print(f"⚠️ 字数偏少({content_len}字)", flush=True)
        elif content_len < 1500:
            print(f"📏 字数略少({content_len}字)", end=' ', flush=True)

        body = f"# {title}\n\n{text}"
        try:
            doc_id, err = create_yuque_doc(title, body)
        except Exception as e:
            print(f"❌ {e}", flush=True)
            failed_set.add(title)
            new_failed += 1
            save_progress({"completed": list(completed_set), "failed": list(failed_set)})
            continue

        if doc_id:
            print(f"✅", flush=True)
            completed_set.add(title)
            failed_set.discard(title)
            new_success += 1
        else:
            print(f"❌ {err[:60] if err else 'unknown'}", flush=True)
            failed_set.add(title)
            new_failed += 1

        save_progress({"completed": list(completed_set), "failed": list(failed_set)})
        time.sleep(API_INTERVAL)

    save_progress({"completed": list(completed_set), "failed": list(failed_set)})
    elapsed = time.time() - start_time
    print(f"\n完成！新成功: {new_success}, 新失败: {new_failed}")
    print(f"总成功: {len(completed_set)}, 总失败: {len(failed_set)}")
    print(f"耗时: {elapsed:.0f}s")

    if new_success > 0:
        print("\n🔧 校验并修复 TOC 顺序...")
        reorder(BOOK_ID, CHAPTER_LIST)
    else:
        print("\nℹ️ 本次无新增导入，跳过 TOC 校验")

if __name__ == '__main__':
    main()