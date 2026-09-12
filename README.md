# 番茄小说 → 语雀 导入工具

将番茄小说（fanqienovel.com）完整章节内容导入语雀知识库，支持正文 + 番外全量导入。

## 解决的问题

- **番茄小说反爬**：自定义字体加密，直接抓取是乱码
- **内容预览限制**：网页只显示 200 字预览，完整内容需登录/VIP
- **第三方 API**：通过 `http://101.35.133.34:5000/api/raw_full` 获取完整纯文本章节内容（无需字体解码）

## 工具链

### 1. 章节列表获取
调第三方 API `/api/book?bookId={book_id}` 获取全部 item_id（按发布顺序），标题直接取接口返回的 `chapterListWithVolume`（自带标题，页面反爬也不受影响），页面爬取仅作兜底。

### 2. 内容获取
调用第三方 API 获取章节内容：
```
GET http://101.35.133.34:5000/api/raw_full?item_id={item_id}
```
失败自动重试最多 3 次，返回纯文本，无需字体解码。

### 3. 语雀上传
通过 `mcporter` 调 `yuque-mcp` 的 MCP 工具，创建知识库、移动分组、创建文档全部走统一通道。

## 依赖

- **mcporter**：MCP 调用工具（已预装）
- **yuque-mcp**：语雀 MCP 服务器（OpenClaw 管理）
- 无需 `pip install`，不依赖 `requests`

## 使用流程

### 完整工作流（推荐）
自动创建语雀知识库 → 放入小说分组 → 生成章节列表 → 批量导入（含番外）

```bash
python3 yuque_import_workflow.py \
    --book-id 7457108578311097369 \
    --title "玄幻：提取万物词条，弟子全是妖孽！"
```

> `--author` / `--description` 可省略：会自动调搜索接口获取作者和明文简介（见下文「增强能力」）。

### 仅导入已有知识库
```bash
# 先配置 config.json 的 book_id 为语雀知识库 ID
python3 batch_import_final_v2.py
```

### 仅创建知识库
```bash
python3 yuque_import_workflow.py --book-id ... --title ... --author ... --skip-import
```

### 单章测试
```bash
curl -s "http://101.35.133.34:5000/api/raw_full?item_id=7423810901096006206"
```

## 文件说明

| 文件 | 用途 |
|------|------|
| `batch_import_final_v2.py` | 批量导入脚本（获取内容 + 创建文档 + 修复 TOC 顺序） |
| `yuque_import_workflow.py` | 完整工作流脚本（创建知识库 + 生成章节列表 + 导入） |
| `fanqie_tools.py` | 元数据/简介自动获取（搜索接口明文） |
| `font_decoder.py` | 混淆字体解码器（位图 IoU 匹配） |
| `config.json` | 配置文件（`yuque_repo_id` 为语雀知识库 ID，番茄 book_id 走环境变量 `BOOK_ID`） |

## 注意事项

- 第三方 API 可能有调用频率限制，脚本内置 0.5s 间隔 + 自动重试
- 进度文件：`progress/novel_v2_progress.json`（支持断点续传）
- 章节列表：`/tmp/chapter_list.json`
- `config.json` 的 `yuque_repo_id` 是**语雀知识库 ID**（数字），不是番茄小说的 book_id。番茄 book_id 通过环境变量 `BOOK_ID` 传入
- 支持环境变量覆盖：`BOOK_ID=xxx` `API_BASE=xxx`，优先级高于 `config.json`
- 导入完成后自动检查并修复 TOC 章节顺序

## 增强能力（2026-09-12）

### 1. 简介/元数据自动获取 — `fanqie_tools.py`
番茄页面简介被字体加密 + 反爬挡死，但第三方 API 搜索端点 `/api/search?key={书名}`
直接返回**明文**书籍信息（含简介 abstract）。

- `fetch_book_meta(book_id, search_key)` → 书名/作者/简介/封面/字数/在读人数
- `auto_fill_meta(book_id, title, author, description)` → workflow 集成：`--author`
  或 `--description` 缺省时自动补全

### 2. 混淆字体解码器 — `font_decoder.py`
番茄把字符替换为 PUA 码点（U+E000~U+F8FF），字形被**重绘**成目标汉字，
纯 cmap 映射解不开。解码原理：混淆字体与思源黑体同源度量一致，逐字形渲染
位图做 IoU 匹配还原真实字符（361/362 码点实测稳定）。

```python
from font_decoder import build_pua_map, decode_text
mapping = build_pua_map("obf.woff2")   # {PUA码点: 真实字符}
text = decode_text("加密文本", mapping)
```

- 依赖（懒加载）：`pip install fonttools pillow numpy`
- 参考字体 SourceHanSansSC-Normal.otf（~16MB）首次自动下载（jsdelivr CDN，
  raw.githubusercontent 直连不通时自动回退），可设 `FANQIE_REF_FONT` 指定本地路径