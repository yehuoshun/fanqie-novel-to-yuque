#!/usr/bin/env python3
"""Final import: fetch full novel chapters via API, upload to Yuque"""
import json
import subprocess
import re
import sys
import os
import time
import base64

# --- 配置加载 ---
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        cfg = json.load(f)
    # 环境变量覆盖（优先级最高）
    if os.environ.get('BOOK_ID'):
        cfg['book_id'] = os.environ['BOOK_ID']
    if os.environ.get('API_BASE'):
        cfg['api_base'] = os.environ['API_BASE']
    return cfg

CONFIG = load_config()
API_BASE = CONFIG['api_base']
BOOK_ID = CONFIG['book_id']
PROGRESS_FILE = CONFIG['progress_file']
MCP_CLIENT = CONFIG['mcp_client']
CHAPTER_LIST = CONFIG['chapter_list']
MIN_CONTENT_LEN = CONFIG.get('min_content_length', 500)
WARN_CONTENT_LEN = CONFIG.get('warning_content_length', 1000)
API_INTERVAL = CONFIG.get('api_interval', 0.5)

def fetch_text(url, timeout=15):
    """Fetch plain text from a URL"""
    result = subprocess.run(
        ['curl', '-s', url, '--max-time', str(timeout)],
        capture_output=True, text=True, timeout=timeout+5
    )
    return result.stdout

def get_chapter_content(item_id):
    """Get full chapter content from the API"""
    raw = fetch_text(f"{API_BASE}/api/raw_full?item_id={item_id}")
    try:
        data = json.loads(raw)
        content = data['data']['content']
        # Extract text from HTML
        texts = re.findall(r'<p[^>]*>(.*?)</p>', content, re.DOTALL)
        # Add tab indentation (2 spaces per paragraph)
        lines = []
        for t in texts:
            t = re.sub(r'<[^>]+>', '', t)
            t = re.sub(r'&nbsp;', ' ', t)
            t = re.sub(r'&lt;', '<', t)
            t = re.sub(r'&gt;', '>', t)
            t = re.sub(r'&amp;', '&', t)
            t = t.strip()
            if t:
                lines.append(f"&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;{t}")
            else:
                lines.append("")
        return '\n'.join(lines)
    except Exception as e:
        return None

def create_yuque_doc(title, body):
    payload = {
        "book_id": BOOK_ID,
        "title": title,
        "body": body,
        "format": "markdown",
        "public": 0
    }
    b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode('utf-8')).decode()
    result = subprocess.run(
        ['node', MCP_CLIENT, b64],
        capture_output=True, text=True, timeout=30
    )
    output = result.stdout.strip()
    if not output:
        output = result.stderr.strip()
    try:
        data = json.loads(output)
        if isinstance(data, dict) and data.get('id'):
            return data.get('id'), None
        return None, str(data)[:100]
    except json.JSONDecodeError as e:
        return None, f"JSON: {output[:200]}"

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {"completed": [], "failed": []}

def save_progress(progress):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f)

def main():
    with open(CHAPTER_LIST, 'r', encoding='utf-8') as f:
        chapters = json.load(f)
    
    real_chapters = [(t, u) for t, u in chapters if t.startswith('第') and '章' in t]
    total = len(real_chapters)
    
    progress = load_progress()
    completed_set = set(progress.get("completed", []))
    failed_set = set(progress.get("failed", []))
    
    print(f"共 {total} 章，已导入 {len(completed_set)} 章，失败 {len(failed_set)} 章", flush=True)
    print(f"开始批量导入...", flush=True)
    
    start_time = time.time()
    new_success = 0
    new_failed = 0
    
    for i, (title, url) in enumerate(real_chapters, 1):
        if title in completed_set:
            continue
        
        print(f"[{i}/{total}] {title}...", end=' ', flush=True)
        
        # Extract item_id from URL
        item_id = url.split('/reader/')[-1]
        
        try:
            text = get_chapter_content(item_id)
        except Exception as e:
            print(f"❌", flush=True)
            failed_set.add(title)
            new_failed += 1
            save_progress({"completed": list(completed_set), "failed": list(failed_set)})
            continue
        
        if not text or len(text) < MIN_CONTENT_LEN:
            print(f"❌ 内容过短 ({len(text) if text else 0}字)", flush=True)
            failed_set.add(title)
            new_failed += 1
            save_progress({"completed": list(completed_set), "failed": list(failed_set)})
            continue
        
        # Verify content completeness: expected ~2000+ chars per chapter
        content_len = len(text)
        if content_len < WARN_CONTENT_LEN:
            print(f"⚠️ 字数偏少 ({content_len}字)", flush=True)
        elif content_len < 1500:
            print(f"📏 字数略少 ({content_len}字)", end=' ', flush=True)
        
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
            new_success += 1
        else:
            err_msg = err[:60] if err else 'unknown'
            print(f"❌ {err_msg}", flush=True)
            failed_set.add(title)
            new_failed += 1
        
        if (new_success + new_failed) % 5 == 0:
            save_progress({"completed": list(completed_set), "failed": list(failed_set)})
        
        time.sleep(API_INTERVAL)
    
    save_progress({"completed": list(completed_set), "failed": list(failed_set)})
    
    elapsed = time.time() - start_time
    print(f"\n完成！新成功: {new_success}, 新失败: {new_failed}", flush=True)
    print(f"总成功: {len(completed_set)}, 总失败: {len(failed_set)}", flush=True)
    print(f"耗时: {elapsed:.0f}s", flush=True)

if __name__ == '__main__':
    main()