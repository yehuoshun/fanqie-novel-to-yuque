#!/usr/bin/env python3
"""
番茄小说 → 语雀 完整导入工作流

用法:
  python3 yuque_import_workflow.py --book-id 7220383810771225655 \\
      --title "穿越三年，你就给我这个破系统？" \\
      --alias "不对劲！我这修仙系统有毒！" \\
      --author "暗影玩具车" \\
      --description "作品简介原文"

依赖:
  pip install requests
"""

import json
import os
import subprocess
import sys
import time
import argparse
import requests

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
YUQUE_MCP_CONFIG = os.path.expanduser('~/.openclaw/workspace/skills/yuque-ai-mcp/config/config.json')
API_BASE = "https://www.yuque.com/api/v2"
MINE_BASE = "https://www.yuque.com/api/mine"


def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)


def load_yuque_config():
    with open(YUQUE_MCP_CONFIG, 'r') as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def create_repo(token, login, name, description):
    """创建语雀知识库（v2 API）"""
    url = f"{API_BASE}/users/{login}/repos"
    headers = {
        "X-Auth-Token": token,
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    payload = {
        "name": name,
        "description": description,
        "public": 0
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=10)
    if resp.status_code not in (200, 201):
        print(f"❌ 创建知识库失败 [{resp.status_code}]: {resp.text[:200]}")
        return None
    data = resp.json().get('data', {})
    repo_id = data.get('id')
    print(f"✅ 知识库已创建: id={repo_id}, name={data.get('name','')}")
    return repo_id


def move_to_stack(cookie, ctoken, book_id, stack_id):
    """移动知识库到指定分组（mine API，Cookie认证）"""
    url = f"{MINE_BASE}/book_stack/move"
    headers = {
        "Cookie": cookie,
        "x-csrf-token": ctoken,
        "Referer": "https://www.yuque.com/dashboard/books",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }
    payload = {
        "targetStackId": stack_id,
        "targetBookIds": [book_id]
    }
    resp = requests.put(url, headers=headers, json=payload, timeout=30)
    if resp.status_code != 200:
        print(f"⚠️ 移动到分组失败 [{resp.status_code}]: {resp.text[:200]}")
        return False
    print(f"✅ 已移动到分组 (stack_id={stack_id})")
    return True


def generate_chapter_list(book_id):
    """获取章节列表：API 返回 item_id 顺序，页面匹配标题，保留全部 768 章（含番外）"""
    import re
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
    api_base = "http://101.35.133.34:5000"

    # 1. 调 API 拿 allItemIds（按发布顺序排列，包含番外）
    api_url = f"{api_base}/api/book?bookId={book_id}"
    try:
        resp = requests.get(api_url, timeout=15)
        api_data = resp.json()
        all_ids = api_data['data']['data']['allItemIds']
    except Exception as e:
        print(f"❌ API 获取章节列表失败: {e}")
        return None

    print(f"📖 API 返回 {len(all_ids)} 个 item_id")

    # 2. 爬页面拿标题 → item_id 映射
    page_url = f"https://fanqienovel.com/page/{book_id}"
    try:
        resp = requests.get(page_url, headers=headers, timeout=15)
        html = resp.text
    except Exception as e:
        print(f"❌ 获取书籍页面失败: {e}")
        return None

    title_map = {}  # item_id → title
    for m in re.finditer(r'href="/reader/(\d+)"[^>]*class="chapter-item-title"[^>]*>([^<]+)</a>', html):
        item_id = m.group(1)
        title = m.group(2).strip()
        title_map[item_id] = title

    if not title_map:
        print("❌ 页面未提取到章节标题（可能需 JS 渲染）")
        return None

    # 3. 按 API 顺序组装章节列表（保留全部，含番外）
    chapters = []
    missing_titles = 0
    for item_id in all_ids:
        title = title_map.get(item_id, f"[未命名-{item_id}]")
        if not title_map.get(item_id):
            missing_titles += 1
        url = f"https://fanqienovel.com/reader/{item_id}"
        chapters.append([title, url])

    if missing_titles:
        print(f"⚠️ {missing_titles} 个章节在页面未找到标题（可能已隐藏）")

    # 4. 统计
    regular = sum(1 for t, _ in chapters if t.startswith('第') and '章' in t)
    extras = len(chapters) - regular
    print(f"  正文: {regular} 章 | 番外: {extras} 章")

    chapter_path = '/tmp/chapter_list.json'
    with open(chapter_path, 'w', encoding='utf-8') as f:
        json.dump(chapters, f, ensure_ascii=False)
    print(f"✅ 共 {len(chapters)} 章 → {chapter_path}")
    return chapter_path


def run_import():
    """运行批量导入脚本"""
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'batch_import_final_v2.py')
    result = subprocess.run(['python3', script], capture_output=True, text=True, timeout=600)
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description='番茄小说 → 语雀 完整导入工作流')
    parser.add_argument('--book-id', required=True, help='番茄小说 book_id（数字）')
    parser.add_argument('--title', required=True, help='主书名')
    parser.add_argument('--alias', default='', help='别名/又名（可选）')
    parser.add_argument('--author', required=True, help='作者名')
    parser.add_argument('--description', default='', help='作品简介')
    parser.add_argument('--skip-create', action='store_true', help='跳过创建知识库（仅导入）')
    parser.add_argument('--skip-import', action='store_true', help='跳过导入（仅创建知识库）')
    args = parser.parse_args()

    # 拼知识库名称
    if args.alias:
        repo_name = f"《{args.title}》又名《{args.alias}》 — {args.author}"
    else:
        repo_name = f"《{args.title}》 — {args.author}"

    print(f"📚 {repo_name}")
    print(f"   book_id: {args.book_id}")
    print()

    cfg = load_config()
    yuque_cfg = load_yuque_config()

    token = yuque_cfg.get('token', '')
    cookie = yuque_cfg.get('cookie', '')
    ctoken = yuque_cfg.get('ctoken', '')
    login = cfg.get('yuque_config', {}).get('user_login', 'yehuoshun')
    stack_id = cfg.get('yuque_config', {}).get('stack_id', 26774009)

    # Step 1: 创建知识库
    if not args.skip_create:
        if not token:
            print("❌ 缺少 yuque token，跳过创建知识库")
        else:
            repo_id = create_repo(token, login, repo_name, args.description)
            if repo_id:
                # 更新 config 的 book_id
                cfg['book_id'] = str(repo_id)
                save_config(cfg)
                print(f"✅ config.json book_id 已更新为 {repo_id}")

                # 移动到小说分组
                if cookie and ctoken:
                    move_to_stack(cookie, ctoken, repo_id, stack_id)
                else:
                    print("⚠️ 缺少 cookie/ctoken，请手动将知识库移到小说分组")
    else:
        # 跳过创建时，用当前 config 的 book_id
        repo_id = cfg.get('book_id')
        print(f"ℹ️ 跳过创建，使用 config 中的 book_id: {repo_id}")

    # Step 2: 生成章节列表
    chapter_path = generate_chapter_list(args.book_id)
    if not chapter_path:
        sys.exit(1)

    # Step 3: 导入章节
    if not args.skip_import:
        print()
        print("🚀 开始批量导入...")
        success = run_import()
        if success:
            print("✅ 全部导入完成！")
        else:
            print("⚠️ 导入过程有异常，请检查日志")
    else:
        print("ℹ️ 跳过导入")

    print()
    print("📍 知识库地址:")
    print(f"   https://www.yuque.com/{login}/repo-{cfg.get('book_id', '')}")


if __name__ == '__main__':
    main()