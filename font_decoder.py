# -*- coding: utf-8 -*-
"""
font_decoder.py — 番茄小说混淆字体解码器（自实现）
==================================================
背景：番茄页面/接口把部分字符替换为 PUA 码点（U+E000~U+F8FF），由一个随机
命名的思源黑体子集字体映射回正确字形。字形是**重绘**的（不是简单 unicode
映射），因此无法靠 cmap 表直接还原。

解码原理（参考开源社区方案，思路自实现）：
  混淆字体与完整思源黑体（SourceHanSansSC）同源、度量一致。把每个 PUA 字形
  与候选字符集在相同位置渲染成位图，逐候选计算 IoU（交并比），得分最高的
  即为真实字符。全量 362 字形实测 top1 稳定还原。

依赖（懒加载，缺失时给出提示）：
  pip install fonttools pillow numpy

参考字体：SourceHanSansSC-Normal.otf（~16MB），首次使用时自动下载到
  `~/.cache/fanqie/`，也可用 FANQIE_REF_FONT 环境变量指定本地路径。

用法：
    from font_decoder import build_pua_map, decode_text
    mapping = build_pua_map("obf.woff2")          # {PUA码点: 真实字符}
    text = decode_text("灵武宗。\\ue655\\ue4b5", mapping)
"""
import os
import sys
import urllib.request

REF_FONT_URL = ("https://cdn.jsdelivr.net/gh/adobe-fonts/source-han-sans@release/"
                "OTF/SimplifiedChinese/SourceHanSansSC-Normal.otf")
# raw.githubusercontent.com 国内直连不通时的备选（ghproxy 类镜像可自行替换）
REF_FONT_URL_FALLBACK = ("https://raw.githubusercontent.com/adobe-fonts/source-han-sans/"
                         "release/OTF/SimplifiedChinese/SourceHanSansSC-Normal.otf")
REF_FONT_DEFAULT = os.path.expanduser("~/.cache/fanqie/SourceHanSansSC-Normal.otf")

SIZE = 40          # 渲染字号
CANVAS = SIZE * 2  # 画布尺寸
POS = SIZE // 2    # 文本起点（两字体度量一致，同一位置即可对齐）

# 候选字符集：ASCII 可见字符 + 常用标点 + CJK 统一表意文字 + 全角符号
CANDIDATES = (
    [chr(cp) for cp in range(0x20, 0x7F)]
    + [chr(cp) for cp in range(0x3000, 0x303F)]
    + [chr(cp) for cp in range(0x4E00, 0x9FFF)]
    + [chr(cp) for cp in range(0xFF00, 0xFFEF)]
)

_DEPS = None


def _ensure_deps():
    """懒加载第三方依赖，缺失时给出安装提示"""
    global _DEPS
    if _DEPS is not None:
        return _DEPS
    try:
        import numpy as np
        from PIL import Image, ImageDraw, ImageFont
        from fontTools.ttLib import TTFont
    except ImportError as e:
        print("❌ font_decoder 依赖缺失: %s" % e, file=sys.stderr)
        print("   安装: pip install fonttools pillow numpy", file=sys.stderr)
        _DEPS = None
        return None
    _DEPS = (np, Image, ImageDraw, ImageFont, TTFont)
    return _DEPS


def _ensure_ref_font():
    """返回参考字体路径，缺失时自动下载"""
    env = os.environ.get("FANQIE_REF_FONT")
    if env and os.path.exists(env):
        return env
    if os.path.exists(REF_FONT_DEFAULT):
        return REF_FONT_DEFAULT
    os.makedirs(os.path.dirname(REF_FONT_DEFAULT), exist_ok=True)
    print(f"⬇️  下载参考字体 SourceHanSansSC-Normal.otf (~16MB)...", file=sys.stderr)
    try:
        urllib.request.urlretrieve(REF_FONT_URL, REF_FONT_DEFAULT + ".part")
    except Exception:
        try:
            urllib.request.urlretrieve(REF_FONT_URL_FALLBACK, REF_FONT_DEFAULT + ".part")
        except Exception as e:
            print(f"❌ 参考字体下载失败: {e}", file=sys.stderr)
            print(f"   请手动下载后设置 FANQIE_REF_FONT 指向该文件", file=sys.stderr)
            return None
    os.rename(REF_FONT_DEFAULT + ".part", REF_FONT_DEFAULT)
    print(f"✅ 参考字体就绪: {REF_FONT_DEFAULT}", file=sys.stderr)
    return REF_FONT_DEFAULT


class ObfuscatedFontDecoder:
    """混淆字体解码器：渲染位图 + IoU 匹配还原真实字符"""

    def __init__(self, font_path):
        deps = _ensure_deps()
        if deps is None:
            raise RuntimeError("依赖缺失，无法初始化解码器")
        self._np, self._Image, self._ImageDraw, self._ImageFont, self._TTFont = deps
        self._tmp = None
        self._ref_cache = None

        ref = _ensure_ref_font()
        if not ref:
            raise RuntimeError("参考字体不可用")

        # 字体统一转 TTF（woff/woff2 用 fontTools 转存）
        self.obf_path = self._to_ttf(font_path)
        self.obf_font = self._ImageFont.truetype(self.obf_path, SIZE)
        self.ref_font = self._ImageFont.truetype(ref, SIZE)
        self.cmap = self._TTFont(self.obf_path).getBestCmap()

    def _to_ttf(self, path):
        if path.lower().endswith(('.woff', '.woff2')):
            out = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_obf_decoded.ttf')
            self._TTFont(path).save(out)
            self._tmp = out
            return out
        return path

    def _render(self, font, ch):
        img = self._Image.new("L", (CANVAS, CANVAS), 0)
        d = self._ImageDraw.Draw(img)
        try:
            d.text((POS, POS), ch, font=font, fill=255)
        except Exception:
            return None
        return self._np.asarray(img) > 100

    def _pack(self, mask):
        flat = mask.ravel().astype('uint64')
        n = (len(flat) + 63) // 64
        out = self._np.zeros(n, dtype='uint64')
        for i in range(n):
            chunk = flat[i * 64:(i + 1) * 64]
            v = 0
            for j, b in enumerate(chunk):
                v |= b << j
            out[i] = v
        return out

    def _popcount(self, x):
        return int(self._np.bitwise_count(x).sum())

    def _build_refs(self):
        """构建候选字符参考位图缓存: (chars列表, packed数组)"""
        if self._ref_cache:
            return self._ref_cache
        packed_list, kept = [], []
        for ch in CANDIDATES:
            m = self._render(self.ref_font, ch)
            if m is None or not m.any():
                continue
            packed_list.append(self._pack(m))
            kept.append(ch)
        self._ref_cache = (kept, self._np.stack(packed_list))
        return self._ref_cache

    def build_map(self, top1_min=0.60, margin_min=0.02):
        """
        返回 {PUA码点: 真实字符}
        判据：top1 得分 ≥ top1_min 且与第二名分差 ≥ margin_min
        """
        np = self._np
        kept, refs = self._build_refs()
        mapping, rejected = {}, []
        for cp in self.cmap:
            if not (0xE000 <= cp <= 0xF8FF):
                continue
            m = self._render(self.obf_font, chr(cp))
            if m is None or not m.any():
                continue
            q = self._pack(m)
            inter = np.array([self._popcount(refs[i] & q) for i in range(len(refs))], dtype='float64')
            union = np.array([self._popcount(refs[i] | q) for i in range(len(refs))], dtype='float64')
            sim = inter / np.maximum(union, 1)
            order = np.argsort(sim)[::-1]
            top1, top2 = float(sim[order[0]]), float(sim[order[1]])
            if top1 >= top1_min and (top1 - top2) >= margin_min:
                mapping[cp] = kept[order[0]]
            else:
                rejected.append((hex(cp), kept[order[0]], round(top1, 3)))
        if rejected:
            print(f"⚠️ {len(rejected)} 个字形未通过判据: {rejected[:10]}", file=sys.stderr)
        return mapping

    def decode(self, text, mapping):
        return "".join(mapping.get(ord(ch), ch) for ch in text)

    def __del__(self):
        if self._tmp and os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except OSError:
                pass


def build_pua_map(font_path):
    """便捷入口：给定混淆字体路径，返回 {PUA码点: 真实字符}"""
    decoder = ObfuscatedFontDecoder(font_path)
    return decoder.build_map()


def decode_text(text, mapping):
    """便捷入口：按映射解码 PUA 文本"""
    return "".join(mapping.get(ord(ch), ch) for ch in text)


if __name__ == '__main__':
    import json
    if len(sys.argv) < 2:
        print("用法: python3 font_decoder.py <混淆字体.woff2|.otf> [PUA文本...]")
        sys.exit(1)
    path = sys.argv[1]
    m = build_pua_map(path)
    print(f"mapping: {len(m)} 码点")
    if len(sys.argv) > 2:
        print("decode:", decode_text(sys.argv[2], m))
    else:
        json.dump({f'{k:04x}': v for k, v in m.items()},
                  open('/tmp/pua_map.json', 'w'), ensure_ascii=False, indent=1)
        print("映射已存 /tmp/pua_map.json")
