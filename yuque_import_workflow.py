#!/usr/bin/env python3
"""
番茄小说 → 语雀 完整导入工作流

用法:
  python3 yuque_import_workflow.py --book-id 7220383810771225655 \
      --title "穿越三年，你就给我这个破系统？" \
      --alias "不对劲！我这修仙系统有毒！" \
      --author "暗影玩具车" \
      --description "作品简介原文"

依赖: 无需 pip install，走 mcporter 调 yuque-mcp
"""

import json
import os
import subprocess
import sys
import time
import argparse
import re

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

# mcporter 需要从 workspace 根目录调用才能找到 yuque-mcp 配置
MCP_WORKDIR = '/home/admin/.openclaw/workspace'
API_BASE = "http://101.35.133.34:5000"


def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def mcporter_call(tool, args_dict):
    """统一调 mcporter，返回解析后的 JSON 响应"""
    args = json.dumps(args_dict, ensure_ascii=False)
    result = subprocess.run(
        ['mcporter', 'call', f'yuque-mcp.{tool}', '--args', args],
        capture_output=True, text=True, timeout=30,
        cwd=MCP_WORKDIR
    )
    output = result.stdout.strip()
    if not output:
        output = result.stderr.strip()
    return json.loads(output) if output else {}


def create_repo(name, description):
    """通过 MCP 创建语雀知识库，直接放入小说分组"""
    cfg = load_config()
    login = cfg.get('yuque_config', {}).get('user_login', 'yehuoshun')

    payload = {
        'login': login,
        'name': name,
        'description': description,
        'type': 'Book',
        'public': 0,
        'stack_id': 26774009,  # 小说分组，固定值
    }

    data = mcporter_call('yuque_create_repo', payload)
    repo_id = data.get('id')
    if not repo_id:
        print(f"❌ 创建知识库失败: {str(data)[:200]}")
        return None
    print(f"✅ 知识库已创建: id={repo_id}, name={data.get('name','')}")
    return repo_id


def curl_get(url, timeout=15):
    """HTTP GET 返回文本"""
    result = subprocess.run(
        ['curl', '-s', '-m', str(timeout), url],
        capture_output=True, text=True, timeout=timeout + 5
    )
    return result.stdout


def generate_chapter_list(book_id):
    """获取章节列表：API 返回 item_id 顺序，页面匹配标题，保留全部 768 章（含番外）"""
    # 1. 调 API 拿 allItemIds（按发布顺序排列，包含番外）
    api_url = f"{API_BASE}/api/book?bookId={book_id}"
    raw = curl_get(api_url)
    try:
        api_data = json.loads(raw)
        all_ids = api_data['data']['data']['allItemIds']
    except Exception as e:
        print(f"❌ API 获取章节列表失败: {e}")
        return None

    print(f"📖 API 返回 {len(all_ids)} 个 item_id")

    # 2. 爬页面拿标题 → item_id 映射
    page_url = f"https://fanqienovel.com/page/{book_id}"
    html = curl_get(page_url, timeout=15)
    if not html:
        print("❌ 获取书籍页面失败")
        return None

    title_map = {}
    for m in re.finditer(r'href="/reader/(\d+)"[^>]*class="chapter-item-title"[^>]*>([^<]+)</a>', html):
        item_id = m.group(1)
        title = m.group(2).strip()
        title_map[item_id] = title

    if not title_map:
        print("❌ 页面未提取到章节标题（可能需 JS 渲染）")
        return None

    # 3. 按 API 顺序组装章节列表
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
    login = cfg.get('yuque_config', {}).get('user_login', 'yehuoshun')

    # Step 1: 创建知识库
    if not args.skip_create:
        repo_id = create_repo(repo_name, args.description)
        if repo_id:
            cfg['yuque_repo_id'] = str(repo_id)
            save_config(cfg)
            print(f"✅ config.json yuque_repo_id 已更新为 {repo_id}")
    else:
        repo_id = cfg.get('yuque_repo_id')
        print(f"ℹ️ 跳过创建，使用 config 中的 yuque_repo_id: {repo_id}")

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
    print(f"   https://www.yuque.com/{login}/{cfg.get('yuque_repo_id', '')}")


if __name__ == '__main__':
    main()