#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
txt_import.py — 小说 TXT → 语雀 导入工具（本地文件版）
========================================================
不依赖任何抓取接口。老板上传小说 txt，本脚本解析章节 → 创建知识库 → 批量导入语雀 → 修复 TOC。

用法:
  # 创建新知识库并导入
  python3 txt_import.py --txt /path/to/novel.txt \
      --title "书名" --author "作者" --description "简介"

  # 导入到已有知识库（读 config.json 的 yuque_repo_id）
  python3 txt_import.py --txt /path/to/novel.txt

  # 分批导入（大文件防超时，进度自动续传）
  python3 txt_import.py --txt novel.txt --start 1 --end 200

  # 只解析不导入（预览章节列表）
  python3 txt_import.py --txt novel.txt --dry-run

依赖: 无第三方库，走 mcporter 调 yuque-mcp
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, 'config.json')
MCP_WORKDIR = '/home/admin/.openclaw/workspace'
CHAPTER_LIST = '/tmp/chapter_list.json'
PROGRESS_FILE = os.path.join(PROJECT_DIR, 'progress', 'txt_progress.json')

# ---------------------------------------------------------------- 编码读取
def read_txt(path):
    """自动探测编码读取 txt（中文小说常见 utf-8 / gb18030 / gbk）"""
    if not os.path.exists(path):
        print(f"❌ 文件不存在: {path}")
        sys.exit(1)
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'big5'):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode('utf-8', errors='replace')

# ---------------------------------------------------------------- 章节解析
_TITLE_RE = re.compile(
    r'^\s*(?:'
    r'第\s*[0-9零一二三四五六七八九十百千万两〇]+\s*[章回节卷集话篇][^\n]{0,40}'
    r'|(?:楔子|序章|序言|前言|引子|尾声|终章|后记|完结感言|上架感言|公告)[^\n]{0,30}'
    r'|(?:番外|外传)[^\n]{0,40}'
    r')\s*$'
)


def parse_chapters(text):
    """按章节标题切分，返回 [(title, [line, ...]), ...]"""
    chapters = []
    cur_title = None
    cur_lines = []

    def flush():
        nonlocal cur_title, cur_lines
        if cur_title is not None:
            body = '\n'.join(cur_lines).strip()
            if body:  # 跳过空章节
                chapters.append((cur_title, cur_lines))
        cur_title, cur_lines = None, []

    for ln in text.split('\n'):
        s = ln.strip()
        if s and len(s) <= 50 and _TITLE_RE.match(s):
            flush()
            cur_title = s
        elif cur_title is not None:
            cur_lines.append(ln)
    flush()
    return chapters


def fmt_body(title, lines):
    """章节 → 语雀 markdown（段首缩进 + 空行分段）"""
    paras = []
    for ln in lines:
        t = ln.strip()
        if t:
            paras.append(f"&emsp;&emsp;{t}")
        else:
            paras.append('')
    body = '\n'.join(paras).strip('\n')
    return f"# {title}\n\n{body}"

# ---------------------------------------------------------------- 语雀操作
def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def mcporter_call(tool, args_dict, timeout=60):
    """统一调 yuque-mcp，返回解析后的 JSON"""
    args = json.dumps(args_dict, ensure_ascii=False)
    result = subprocess.run(
        ['mcporter', 'call', f'yuque-mcp.{tool}', '--args', args],
        capture_output=True, text=True, timeout=timeout,
        cwd=MCP_WORKDIR
    )
    output = result.stdout.strip() or result.stderr.strip()
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        m = re.search(r'(\{.*\}|\[.*\])', output, re.S)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return None


def create_repo(name, description):
    """创建语雀知识库，放入小说分组（stack_id 固定）"""
    cfg = load_config()
    login = cfg.get('yuque_config', {}).get('user_login', 'yehuoshun')
    data = mcporter_call('yuque_create_repo', {
        'login': login,
        'name': name,
        'description': description,
        'type': 'Book',
        'public': 0,
        'stack_id': 26774009,
    })
    repo_id = data.get('id') if isinstance(data, dict) else None
    if not repo_id:
        print(f"❌ 创建知识库失败: {str(data)[:200]}")
        return None
    print(f"✅ 知识库已创建: id={repo_id}")
    return repo_id


def create_doc(book_id, title, body):
    """创建语雀文档，返回 (doc_id, err)"""
    data = mcporter_call('yuque_create_doc', {
        'book_id': book_id, 'title': title, 'body': body,
        'format': 'markdown', 'public': 0,
    })
    if isinstance(data, dict) and data.get('id'):
        return data['id'], None
    return None, str(data)[:100]

# ---------------------------------------------------------------- 进度
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"completed": [], "failed": []}


def save_progress(p):
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(p, f, ensure_ascii=False)

# ---------------------------------------------------------------- 主流程
def main():
    ap = argparse.ArgumentParser(description='TXT 小说导入语雀')
    ap.add_argument('--txt', required=True, help='小说 txt 路径')
    ap.add_argument('--book-id', default='', help='语雀知识库 ID（缺省读 config.json）')
    ap.add_argument('--title', default='', help='书名（创建新库时必填）')
    ap.add_argument('--author', default='', help='作者名')
    ap.add_argument('--description', default='', help='作品简介')
    ap.add_argument('--create', action='store_true', help='创建新知识库')
    ap.add_argument('--start', type=int, default=1)
    ap.add_argument('--end', type=int, default=0)
    ap.add_argument('--dry-run', action='store_true', help='只解析预览，不导入')
    ap.add_argument('--interval', type=float, default=0.5, help='章节间隔秒数')
    ap.add_argument('--no-toc-fix', action='store_true', help='导入完不修 TOC 顺序')
    args = ap.parse_args()

    # 1. 解析章节
    text = read_txt(args.txt)
    chapters = parse_chapters(text)
    if not chapters:
        print("❌ 未解析到任何章节，请确认 txt 章节标题格式（如「第1章 xxx」）")
        sys.exit(1)
    total_all = len(chapters)
    print(f"📖 解析到 {total_all} 章")
    print(f"   首章: {chapters[0][0]}")
    print(f"   末章: {chapters[-1][0]}")

    # 写章节列表（兼容 reorder_toc）
    with open(CHAPTER_LIST, 'w', encoding='utf-8') as f:
        json.dump([[t, ''] for t, _ in chapters], f, ensure_ascii=False)

    if args.dry_run:
        print("\n预览章节标题（前 20）:")
        for t, _ in chapters[:20]:
            print(f"   {t}")
        sys.exit(0)

    # 2. 确定知识库
    cfg = load_config()
    login = cfg.get('yuque_config', {}).get('user_login', 'yehuoshun')
    if args.create:
        if not args.title:
            print("❌ --create 需要 --title")
            sys.exit(1)
        name = f"《{args.title}》" + (f" — {args.author}" if args.author else "")
        book_id = create_repo(name, args.description)
        if not book_id:
            sys.exit(1)
        cfg['yuque_repo_id'] = str(book_id)
        save_config(cfg)
        print(f"✅ config.json yuque_repo_id 已更新为 {book_id}")
    else:
        book_id = args.book_id or cfg.get('yuque_repo_id', '')
        if not book_id:
            print("❌ 未指定知识库。用 --create --title 创建，或 --book-id 指定已有库")
            sys.exit(1)

    # 3. 分批上传
    start_idx = args.start - 1
    end_idx = args.end if args.end > 0 else total_all
    rng = chapters[start_idx:end_idx]
    progress = load_progress()
    completed = set(progress.get('completed', []))
    failed = set(progress.get('failed', []))

    print(f"\n🚀 导入 {start_idx + 1}-{end_idx} 章（共 {total_all} 章，已完成 {len(completed)}）")
    new_ok = new_fail = 0
    for abs_i, (title, lines) in enumerate(rng, args.start):
        if title in completed:
            continue
        body = fmt_body(title, lines)
        try:
            doc_id, err = create_doc(book_id, title, body)
        except Exception as e:
            print(f"[{abs_i}/{total_all}] {title} ❌ {e}", flush=True)
            failed.add(title)
            new_fail += 1
            save_progress({"completed": list(completed), "failed": list(failed)})
            continue
        if doc_id:
            print(f"[{abs_i}/{total_all}] {title} ✅", flush=True)
            completed.add(title)
            failed.discard(title)
            new_ok += 1
        else:
            print(f"[{abs_i}/{total_all}] {title} ❌ {err[:60] if err else 'unknown'}", flush=True)
            failed.add(title)
            new_fail += 1
        save_progress({"completed": list(completed), "failed": list(failed)})
        time.sleep(args.interval)

    save_progress({"completed": list(completed), "failed": list(failed)})
    print(f"\n完成！新成功 {new_ok}，新失败 {new_fail}，累计成功 {len(completed)} / {total_all}")

    # 4. 全部导入完再修 TOC
    if args.no_toc_fix:
        print("\nℹ️ 跳过 TOC 修复 (--no-toc-fix)")
    elif new_ok > 0 and len(completed) >= total_all:
        print("\n🔧 校验并修复 TOC 顺序...")
        from reorder_toc import reorder
        reorder(book_id, CHAPTER_LIST)
    else:
        print(f"\nℹ️ 尚有 {total_all - len(completed)} 章未完成，跳过 TOC 修复")

    print(f"\n📍 知识库地址: https://www.yuque.com/{login}/{book_id}")


if __name__ == '__main__':
    main()
