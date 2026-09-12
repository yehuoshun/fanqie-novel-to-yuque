#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
reorder_toc.py — 修复语雀知识库 TOC 章节顺序
============================================
背景：create_doc 不带位置参数，新文档追加到 TOC 末尾。
主流程逐章顺序创建没问题；但中途失败后补导的章节会被追加到末尾，
导致该章之后所有章节错位 1 位。

本脚本对比本地章节列表与语雀 TOC，从后往前把错位文档 moveNode 回正确位置。

用法：
    python3 reorder_toc.py                # 修复 config 中 yuque_repo_id 的 TOC
    python3 reorder_toc.py --dry-run      # 只检查不修改
    python3 reorder_toc.py --book-id 83437061 --chapter-list /tmp/chapter_list.json

可被 batch_import_final_v2.py 导入调用：from reorder_toc import reorder
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

MCP_WORKDIR = '/home/admin/.openclaw/workspace'
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PROJECT_DIR, 'config.json')


def load_config():
    with open(CONFIG_PATH, 'r') as f:
        cfg = json.load(f)
    if os.environ.get('BOOK_ID'):
        cfg['yuque_repo_id'] = os.environ['BOOK_ID']
    return cfg


def mcporter_call(tool, args_dict, timeout=60):
    """调 yuque-mcp 工具，返回解析后的 JSON（容忍 mcporter 输出前缀文本）"""
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
        print(f"⚠️ mcporter 输出解析失败: {output[:200]}")
        return None


def get_toc_docs(book_id):
    """拉取 TOC，返回 DOC 节点有序列表"""
    data = mcporter_call('yuque_get_toc', {'book_id': book_id})
    if data is None:
        return None
    if isinstance(data, dict) and data.get('error'):
        print(f"❌ 获取 TOC 失败: {str(data)[:200]}")
        return None
    return [t for t in data if t.get('type') == 'DOC']


def load_chapter_titles(chapter_list_path):
    """读取本地章节列表，返回有序标题列表（兼容 [title,url] 或 dict 结构）"""
    with open(chapter_list_path, 'r', encoding='utf-8') as f:
        chapters = json.load(f)
    titles = []
    for c in chapters:
        if isinstance(c, (list, tuple)):
            titles.append(c[0])
        elif isinstance(c, dict):
            titles.append(c.get('title') or c.get('name') or '')
    return titles


def reorder(book_id, chapter_list_path, dry_run=False, verbose=True):
    """
    校验并修复 TOC 顺序。幂等：顺序正确时零修改。
    返回 True=最终顺序一致；False=存在未修复问题。
    """
    target = load_chapter_titles(chapter_list_path)
    cur_nodes = get_toc_docs(book_id)
    if cur_nodes is None:
        return False

    cur_titles = [n['title'] for n in cur_nodes]

    if verbose:
        print(f"📖 本地章节: {len(target)} | 语雀文档: {len(cur_titles)}")

    if len(cur_titles) > len(target):
        extra = [t for t in cur_titles if t not in set(target)]
        print(f"⚠️ 语雀多出 {len(cur_titles) - len(target)} 个文档（不在本地列表）: {extra[:5]}")
        return False
    if len(cur_titles) < len(target):
        missing = [t for t in target if t not in set(cur_titles)]
        print(f"⚠️ 语雀缺少 {len(target) - len(cur_titles)} 个文档: {missing[:5]}")
        return False

    # title -> node（标题唯一；重复标题取第一个并警告）
    by_title = {}
    for n in cur_nodes:
        if n['title'] in by_title:
            print(f"⚠️ 重复标题: {n['title']}")
        else:
            by_title[n['title']] = n

    # 从后往前扫描，找错位节点并本地模拟移动
    moves = []
    sim = list(cur_nodes)
    for i in range(len(target) - 1, -1, -1):
        want = target[i]
        if i < len(sim) and sim[i]['title'] == want:
            continue
        node = by_title.get(want)
        if node is None:
            print(f"⚠️ 本地章节在语雀中不存在: {want}")
            continue
        j = next((k for k, n in enumerate(sim) if n['uuid'] == node['uuid']), None)
        if j is None or j <= i:
            continue
        if i == 0:
            anchor_uuid = sim[0]['uuid']
            pos = 'before'
        else:
            anchor_uuid = sim[i - 1]['uuid']
            pos = 'after'
        moves.append({
            'action': 'moveNode',
            'node_uuid': node['uuid'],
            'target_uuid': anchor_uuid,
            'position': pos,
            '_title': want,
        })
        sim.pop(j)
        sim.insert(i, node)

    if not moves:
        if verbose:
            print("✅ TOC 顺序正确，无需修复")
        return True

    print(f"🔧 发现 {len(moves)} 个错位文档:")
    for mv in moves:
        print(f"   - {mv['_title']} -> {mv['position']} {mv['target_uuid']}")

    if dry_run:
        print("(dry-run，未修改)")
        return False

    # 逐个提交 moveNode（节点移动有依赖，不批量）
    for mv in moves:
        ops = json.dumps([{k: v for k, v in mv.items() if not k.startswith('_')}], ensure_ascii=False)
        resp = mcporter_call('yuque_batch_update_toc', {
            'book_id': book_id, 'ops': ops, 'confirm': 'RESTRUCTURE'
        })
        ok = bool(resp) and resp.get('success') == 1
        print(f"   {'✅' if ok else '❌'} 移动: {mv['_title']}")
        if not ok:
            print(f"     响应: {str(resp)[:200]}")
            print("⛔ 移动失败，中止（剩余错位需人工处理）")
            return False
        time.sleep(0.5)

    # 全量复验
    final = get_toc_docs(book_id)
    if final is None:
        return False
    final_titles = [n['title'] for n in final]
    if final_titles == target:
        print("✅ 修复完成，TOC 顺序与本地列表完全一致")
        return True
    diff = [(i + 1, t, final_titles[i]) for i, t in enumerate(target) if i >= len(final_titles) or final_titles[i] != t]
    print(f"⚠️ 复验仍有 {len(diff)} 处不一致（首次前 10 处）:")
    for pos, t, c in diff[:10]:
        print(f"   [{pos}] 期望: {t} | 实际: {c}")
    return False


def main():
    parser = argparse.ArgumentParser(description='修复语雀 TOC 章节顺序')
    parser.add_argument('--book-id', default=None, help='语雀知识库 ID（默认读 config.json）')
    parser.add_argument('--chapter-list', default=None, help='本地章节列表 JSON（默认读 config.json）')
    parser.add_argument('--dry-run', action='store_true', help='只检查不修改')
    args = parser.parse_args()

    cfg = load_config()
    book_id = args.book_id or cfg['yuque_repo_id']
    chapter_list = args.chapter_list or cfg['chapter_list']

    if not os.path.exists(chapter_list):
        print(f"❌ 章节列表不存在: {chapter_list}")
        sys.exit(1)

    ok = reorder(book_id, chapter_list, dry_run=args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
