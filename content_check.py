# content_check.py — 正文内容合法校验（字数 / HTML 残留 / 乱码 / 章节报告）
# 纯标准库，零第三方依赖。被 txt_import.py 调用。
"""内容校验：章节字数统计、HTML 残留检测、乱码检测、汇总报告。"""
import re

# 乱码特征（命中即可疑，正则可读）
MOJIBAKE_PATTERNS = [
    ('replacement-char', r'\ufffd'),                       # U+FFFD 替换符
    ('gbk-mojibake', r'锟斤拷'),                            # GBK→UTF8 经典乱码
    ('stack-overflow', r'烫烫烫'),                          # 未初始化内存填充
    ('latin1-garbage', r'Ã[\x80-\xff]'),                   # latin1 误读 UTF8 字节
    ('utf8-as-latin1', r'â€[\x9c\x9d\x9e\x9f\xa0-\xff]'),  # UTF8 按 latin1 读
    ('control-noise', r'[\x00-\x08\x0b\x0c\x0e-\x1f]'),    # 控制字符混入
]
HTML_TAG_RE = re.compile(r'</?[a-zA-Z][^>]{0,60}>')
HTML_ENTITY_RE = re.compile(r'&(?:nbsp|amp|lt|gt|quot|#\d{2,5});')


def char_count(text):
    """去空白后的字符数（中文按字符计）"""
    return len(re.sub(r'\s+', '', text))


def html_residue(text):
    """检测 HTML 标签/实体残留，返回 [(type, sample)]，无则 []"""
    found = []
    m = HTML_TAG_RE.search(text)
    if m:
        found.append(('tag', m.group(0)[:40]))
    m = HTML_ENTITY_RE.search(text)
    if m:
        found.append(('entity', m.group(0)))
    return found


def mojibake(text):
    """乱码检测，返回命中的乱码类型列表，无则 []"""
    return [name for name, pat in MOJIBAKE_PATTERNS if re.search(pat, text)]


def analyze_chapters(chapters, min_chars=50):
    """逐章统计 → 报告 dict。chapters=[(title, [line,...])]"""
    rows = []
    for title, lines in chapters:
        text = '\n'.join(lines)
        n = char_count(text)
        rows.append({'title': title, 'chars': n, 'empty': n == 0,
                     'short': 0 < n <= min_chars,
                     'html': html_residue(text), 'moji': mojibake(text)})
    rows.sort(key=lambda r: r['chars'])
    return {
        'total': len(rows),
        'avg': round(sum(r['chars'] for r in rows) / len(rows)) if rows else 0,
        'empty': [r['title'] for r in rows if r['empty']],
        'short': [(r['title'], r['chars']) for r in rows if r['short']],
        'html': [(r['title'], r['html']) for r in rows if r['html']],
        'moji': [(r['title'], r['moji']) for r in rows if r['moji']],
        'shortest': [(r['title'], r['chars']) for r in rows[:10]],
    }


def format_report(rep):
    """报告 dict → 多行文本（无问题只出摘要）"""
    out = [f"📊 内容校验：{rep['total']} 章，平均 {rep['avg']} 字/章"]
    if rep['empty']:
        out.append(f"  ❌ 空章节 {len(rep['empty'])} 篇: {rep['empty'][:5]}")
    if rep['short']:
        out.append(f"  ⚠️ 超短章(≤50字) {len(rep['short'])} 篇: "
                   + '、'.join(f"{t}({n})" for t, n in rep['short'][:5]))
    if rep['html']:
        out.append(f"  ⚠️ HTML残留 {len(rep['html'])} 篇: {rep['html'][:3]}")
    if rep['moji']:
        out.append(f"  ⚠️ 疑似乱码 {len(rep['moji'])} 篇: {rep['moji'][:3]}")
    out.append("  最短 10 章: "
               + '、'.join(f"{t}({n})" for t, n in rep['shortest']))
    return '\n'.join(out)
