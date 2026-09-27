#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
epub_reader.py — EPUB 解析后端（纯标准库，零第三方依赖）
========================================================
EPUB 本质是 zip：META-INF/container.xml → OPF(manifest + spine) → 按阅读顺序的 xhtml

对外只暴露 read_epub(path)，返回与 txt_import.parse_chapters 同构的结果：
    {'meta': {'title', 'author', 'description'}, 'chapters': [(title, [line, ...]), ...]}

用法:
    from epub_reader import read_epub
    data = read_epub('/path/to/novel.epub')
    for title, lines in data['chapters']:
        print(title)
"""
import os
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser

NS_CONTAINER = 'urn:oasis:names:tc:opendocument:xmlns:container'
NS_OPF = 'http://www.idpf.org/2007/opf'
NS_DC = 'http://purl.org/dc/elements/1.1/'

# 与 txt_import 保持一致的章节标题识别规则
TITLE_RE = re.compile(
    r'^\s*(?:'
    r'第\s*[0-9零一二三四五六七八九十百千万两〇]+\s*[章回节卷集话篇][^\n]{0,40}'
    r'|(?:楔子|序章|序言|前言|引子|尾声|终章|后记|完结感言|上架感言|公告)[^\n]{0,30}'
    r'|(?:番外|外传)[^\n]{0,40}'
    r')\s*$'
)

_SKIP_TAGS = {'script', 'style', 'head', 'title', 'meta', 'link'}
_HEADING_TAGS = {'h1', 'h2', 'h3'}
_BLOCK_TAGS = {
    'p', 'div', 'br', 'li', 'tr', 'td', 'th', 'section', 'article',
    'blockquote', 'pre', 'hr', 'h4', 'h5', 'h6', 'figcaption',
}

HEADING_MARK = '\x01'  # 行前缀标记：该行来自 heading 标签


class HtmlLines(HTMLParser):
    """xhtml → 行列表（块级标签断行；heading 行加 HEADING_MARK 前缀）"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines = []
        self._buf = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _HEADING_TAGS:
            self._flush()
            self._buf.append(HEADING_MARK)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _HEADING_TAGS or tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._skip == 0:
            self._buf.append(data)

    def _flush(self):
        text = re.sub(r'\s+', ' ', ''.join(self._buf)).strip()
        self._buf = []
        if text:
            self.lines.append(text)

    def close(self):
        super().close()
        self._flush()


def _read_text(zf, name):
    """读 zip 内文本，按 XML 声明里的 encoding 探测编码（epub2 常见非 utf-8）"""
    raw = zf.read(name)
    enc = 'utf-8'
    m = re.search(rb'encoding=[\'"]([\w-]+)[\'"]', raw[:300])
    if m:
        enc = m.group(1).decode('ascii', 'ignore')
    return raw.decode(enc, errors='replace')


def _opf_path(zf):
    """从 META-INF/container.xml 取 OPF 相对路径"""
    if 'META-INF/container.xml' not in zf.namelist():
        return None
    root = ET.fromstring(_read_text(zf, 'META-INF/container.xml'))
    node = root.find(f'.//{{{NS_CONTAINER}}}rootfile')
    return node.get('full-path') if node is not None else None


def _spine_docs(zf, opf_path):
    """按 spine 阅读顺序返回 xhtml 相对路径列表"""
    root = ET.fromstring(_read_text(zf, opf_path))
    manifest = {}
    for item in root.iter(f'{{{NS_OPF}}}item'):
        manifest[item.get('id')] = (item.get('href') or '', item.get('media-type') or '')
    base = posixpath.dirname(opf_path)
    docs = []
    for ref in root.iter(f'{{{NS_OPF}}}itemref'):
        if ref.get('linear') == 'no':
            continue
        href, mtype = manifest.get(ref.get('idref'), ('', ''))
        if not href:
            continue
        if 'html' in mtype or href.lower().endswith(('.xhtml', '.html', '.htm')):
            docs.append(posixpath.normpath(posixpath.join(base, href)) if base else href)
    return docs


def _metadata(root):
    """取 OPF 的 dc:title / dc:creator / dc:description"""
    out = {}
    for key, tag in (('title', 'title'), ('author', 'creator'), ('description', 'description')):
        for el in root.iter(f'{{{NS_DC}}}{tag}'):
            if el.text and el.text.strip():
                out[key] = el.text.strip()
                break
    return out


def _split_chapters(blocks):
    """blocks=[(href, [line...])] → [(title, [line...])]

    逐 xhtml 判定切分模式：
      - 该 xhtml 含 h1/h2/h3 → 只按 heading 切（正文行不参与判定，防止误切）
      - 该 xhtml 无 heading   → 按章节标题行（第X章 / 番外 …）切
    最后兜底：完全识别不到标题时「每个 xhtml 一章」。
    标题之前的内容兜底为「前言」章，不静默丢弃。
    """
    if not blocks:
        return []
    chapters, title, buf = [], '', []

    def flush():
        nonlocal title, buf
        if any(x.strip() for x in buf):
            # 标题之前的内容（前言/版权页等）不丢弃，兜底标题「前言」
            chapters.append((title or '前言', buf))
        title, buf = '', []

    for _href, lines in blocks:
        block_has_heading = any(ln.startswith(HEADING_MARK) for ln in lines)
        for ln in lines:
            if ln.startswith(HEADING_MARK):
                text = ln.lstrip(HEADING_MARK).strip()
                if len(text) > 50:  # 超长 heading 当正文
                    buf.append(text)
                    continue
                flush()
                title = text
            elif block_has_heading:
                buf.append(ln)
            elif len(ln) <= 50 and TITLE_RE.match(ln):
                flush()
                title = ln
            else:
                buf.append(ln)
    flush()

    if not chapters:
        for href, lines in blocks:
            body = [ln.lstrip(HEADING_MARK) for ln in lines if ln.strip()]
            if not body:
                continue
            head = lines[0].lstrip(HEADING_MARK) if lines[0].startswith(HEADING_MARK) else ''
            name = head or os.path.splitext(posixpath.basename(href))[0]
            chapters.append((name, body))
    return chapters


def read_epub(path):
    """解析 epub → {'meta': {...}, 'chapters': [(title, [line, ...]), ...]}"""
    if not os.path.exists(path):
        raise FileNotFoundError(f'EPUB 不存在: {path}')
    with zipfile.ZipFile(path) as zf:
        opf_path = _opf_path(zf)
        if not opf_path:
            raise ValueError('EPUB 解析失败：META-INF/container.xml 缺失或无效')
        opf_root = ET.fromstring(_read_text(zf, opf_path))
        meta = _metadata(opf_root)
        blocks = []
        for href in _spine_docs(zf, opf_path):
            try:
                raw = _read_text(zf, href)
            except KeyError:
                continue
            parser = HtmlLines()
            parser.feed(raw)
            parser.close()
            blocks.append((href, parser.lines))
    if not blocks:
        raise ValueError('EPUB 解析失败：spine 里没有可读的 xhtml 章节')
    return {'meta': meta, 'chapters': _split_chapters(blocks)}

if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print('用法: python3 epub_reader.py novel.epub [--dry-run]')
        sys.exit(1)
    result = read_epub(sys.argv[1])
    meta = result['meta']
    print(f"📕 《{meta.get('title', '?')}》 — {meta.get('author', '?')}")
    print(f"📖 解析到 {len(result['chapters'])} 章")
    for i, (title, lines) in enumerate(result['chapters'][:20], 1):
        print(f"   [{i}] {title}  ({len(lines)} 行)")
