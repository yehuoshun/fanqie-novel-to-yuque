#!/usr/bin/env python3
"""
TXT 小说 → 语雀 完整导入工作流
================================
包装 txt_import.py，提供更友好的 CLI（自动创建知识库 + 分批导入）。

用法:
  # 创建新知识库 + 全量导入
  python3 yuque_import_workflow.py --txt /path/to/novel.txt \
      --title "书名" --author "作者"

  # 导入到已有知识库
  python3 yuque_import_workflow.py --txt novel.txt --book-id 123456

  # 分批导入（大文件防超时）
  python3 yuque_import_workflow.py --txt novel.txt --start 1 --end 200

  # 只解析预览
  python3 yuque_import_workflow.py --txt novel.txt --dry-run
"""

import argparse
import sys
import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
TXT_IMPORT = os.path.join(PROJECT_DIR, 'txt_import.py')


def main():
    ap = argparse.ArgumentParser(
        description='TXT 小说 → 语雀 完整导入工作流',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument('--txt', required=True, help='小说 txt 路径')
    ap.add_argument('--book-id', default='', help='语雀知识库 ID（缺省读 config.json）')
    ap.add_argument('--title', default='', help='书名（创建新库时必填）')
    ap.add_argument('--author', default='', help='作者名')
    ap.add_argument('--description', default='', help='作品简介')
    ap.add_argument('--alias', default='', help='别名/又名，多个用 / 分隔')
    ap.add_argument('--create', action='store_true', help='创建新知识库（需要 --title）')
    ap.add_argument('--start', type=int, default=1, help='起始章节号')
    ap.add_argument('--end', type=int, default=0, help='结束章节号（0=全部）')
    ap.add_argument('--dry-run', action='store_true', help='只解析预览，不导入')
    ap.add_argument('--interval', type=float, default=0.5, help='章节间隔秒数')
    ap.add_argument('--no-toc-fix', action='store_true', help='导入完成不修 TOC 顺序')
    args = ap.parse_args()

    # 转发到 txt_import.py
    cmd = [
        'python3', TXT_IMPORT,
        '--txt', args.txt,
    ]
    if args.book_id:
        cmd += ['--book-id', args.book_id]
    if args.title:
        cmd += ['--title', args.title]
    if args.author:
        cmd += ['--author', args.author]
    if args.description:
        cmd += ['--description', args.description]
    if args.alias:
        cmd += ['--alias', args.alias]
    if args.create:
        cmd += ['--create']
    if args.start != 1:
        cmd += ['--start', str(args.start)]
    if args.end:
        cmd += ['--end', str(args.end)]
    if args.dry_run:
        cmd += ['--dry-run']
    cmd += ['--interval', str(args.interval)]
    if args.no_toc_fix:
        cmd += ['--no-toc-fix']

    print(f"🚀 {args.txt} → 语雀")
    print(f"   {' '.join(cmd)}")
    print()

    os.execvp('python3', cmd)


if __name__ == '__main__':
    main()