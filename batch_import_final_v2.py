#!/usr/bin/env python3
"""Final import: fetch full novel chapters via API, upload to Yuque"""
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
CHAPTER_LIST = CONFIG['chapter_list']
MIN_CONTENT_LEN = CONFIG.get('min_content_length', 500)
WARN_CONTENT_LEN = CONFIG.get('warning_content_length', 1000)
API_INTERVAL = CONFIG.get('api_interval', 0.5)

# mcporter 需要从 workspace 根目录调用才能找到 yuque-mcp 配置
MCP_WORKDIR = '/home/admin/.openclaw/workspace'

def fetch_text(url, timeout=15):
    """Fetch plain text from a URL"""
    result = subprocess.run(
        ['curl', '-s', url, '--max-time', str(timeout)],
        capture_output=True, text=True, timeout=timeout+5
    )
    return result.stdout

def get_chapter_content(item_id, max_retries=3):
    """Get full chapter content from the API，自动重试最多 3 次"""
    for attempt in range(1, max_retries + 1):
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
                    lines.append(f"&emsp;&emsp;{t}")
                else:
                    lines.append("")
            result = '\n'.join(lines)
            if result and len(result) >= MIN_CONTENT_LEN:
                return result
            # 内容为空或过短，重试
            if attempt < max_retries:
                print(f"重试第{attempt}次...", end='', flush=True)
                time.sleep(2)
        except Exception:
            if attempt < max_retries:
                print(f"重试第{attempt}次...", end='', flush=True)
                time.sleep(2)
    return None

def reorder_toc():
    """批量导入完成后检查并修复 TOC 顺序（正文章节按号递增，番外放末尾）"""
    print("\n检查 TOC 顺序...", end=' ', flush=True)

    # 获取当前 TOC
    result = subprocess.run(
        ['mcporter', 'call', 'yuque-mcp.yuque_get_toc', '--args',
         json.dumps({'login': 'yehuoshun', 'book_id': BOOK_ID}, ensure_ascii=False)],
        capture_output=True, text=True, timeout=30,
        cwd=MCP_WORKDIR
    )
    try:
        raw = json.loads(result.stdout.strip())
        items = raw.get('data', raw) if isinstance(raw, dict) else raw
    except (json.JSONDecodeError, KeyError):
        print("❌ 获取 TOC 失败")
        return

    if not isinstance(items, list) or len(items) < 2:
        print("跳过（TOC 条目不足）")
        return

    # 排序：正文章节按号递增，番外放末尾
    def sort_key(item):
        t = item['title']
        m = re.match(r'第(\d+)章', t)
        if m:
            return (0, int(m.group(1)))
        return (1, 0)

    sorted_items = sorted(items, key=sort_key)

    # 检查是否已有正确顺序
    already_ordered = all(
        sorted_items[i]['uuid'] == items[i]['uuid']
        for i in range(len(items))
    )
    if already_ordered:
        print("✅ 顺序已正确")
        return

    # 重建 TOC：先删所有节点，再按序追加
    print(f"修复中 ({len(items)} 条目)...", end=' ', flush=True)

    ops = []
    for item in items:
        ops.append({'action': 'removeNode', 'node_uuid': item['uuid']})
    for item in sorted_items:
        op = {
            'action': 'appendNode',
            'action_mode': 'child',
            'type': 'DOC',
            'title': item['title'],
            'visible': 1
        }
        if item.get('doc_id'):
            op['doc_ids'] = json.dumps([item['doc_id']])
        ops.append(op)

    # 分批执行（每批 100 个操作，避免超时）
    for batch_start in range(0, len(ops), 100):
        batch = ops[batch_start:batch_start + 100]
        batch_args = json.dumps({
            'book_id': BOOK_ID,
            'ops': json.dumps(batch),
            'confirm': 'RESTRUCTURE'
        }, ensure_ascii=False)
        subprocess.run(
            ['mcporter', 'call', 'yuque-mcp.yuque_batch_update_toc', '--args', batch_args],
            capture_output=True, text=True, timeout=120,
            cwd=MCP_WORKDIR
        )

    print("✅")


def create_yuque_doc(title, body):
    """通过 mcporter 调 yuque-mcp 创建文档，跳过脆弱的 JS 客户端管道"""
    full_body = f"# {title}\n\n{body}"
    args = json.dumps({
        "book_id": BOOK_ID,
        "title": title,
        "body": full_body,
        "format": "markdown",
        "public": 0
    }, ensure_ascii=False)
    result = subprocess.run(
        ['mcporter', 'call', 'yuque-mcp.yuque_create_doc', '--args', args],
        capture_output=True, text=True, timeout=30,
        cwd=MCP_WORKDIR
    )
    output = result.stdout.strip()
    if not output:
        output = result.stderr.strip()
    try:
        data = json.loads(output)
        if isinstance(data, dict) and data.get('id'):
            return data['id'], None
        if isinstance(data, dict) and data.get('error'):
            return None, str(data['error'])[:100]
        return None, str(data)[:100]
    except json.JSONDecodeError:
        return None, f"parse: {output[:200]}"

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
    
    # 不过滤，导入全部章节（含番外、女频等）
    total = len(chapters)
    
    progress = load_progress()
    completed_set = set(progress.get("completed", []))
    failed_set = set(progress.get("failed", []))
    
    print(f"共 {total} 章，已导入 {len(completed_set)} 章，失败 {len(failed_set)} 章", flush=True)
    print(f"开始批量导入...", flush=True)
    
    start_time = time.time()
    new_success = 0
    new_failed = 0
    
    for i, (title, url) in enumerate(chapters, 1):
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

    # 全部完成后修复 TOC 顺序
    reorder_toc()

if __name__ == '__main__':
    main()