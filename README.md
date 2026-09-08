# 番茄小说 → 语雀 导入工具

将番茄小说（fanqienovel.com）完整章节内容导入语雀知识库，支持正文 + 番外全量导入。

## 解决的问题

- **番茄小说反爬**：自定义字体加密，直接抓取是乱码
- **内容预览限制**：网页只显示 200 字预览，完整内容需登录/VIP
- **第三方 API**：通过 `http://101.35.133.34:5000/api/raw_full` 获取完整纯文本章节内容（无需字体解码）

## 工具链

### 1. 章节列表获取
调第三方 API `/api/book?bookId={book_id}` 获取全部 768 个 item_id（按发布顺序），再爬页面匹配标题，保留完整章节列表（正文 750 章 + 番外 18 篇）。

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
    --book-id 7220383810771225655 \
    --title "穿越三年，你就给我这个破系统？" \
    --alias "不对劲！我这修仙系统有毒！" \
    --author "暗影玩具车" \
    --description "作品简介原文"
```

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
| `config.json` | 配置文件（`book_id` 为语雀知识库 ID，非番茄 book_id） |

## 注意事项

- 第三方 API 可能有调用频率限制，脚本内置 0.5s 间隔 + 自动重试
- 进度文件：`/tmp/novel_v2_progress.json`（支持断点续传）
- 章节列表：`/tmp/chapter_list.json`
- `config.json` 的 `book_id` 是**语雀知识库 ID**（数字），不是番茄小说的 book_id。番茄 book_id 通过环境变量 `BOOK_ID` 传入
- 支持环境变量覆盖：`BOOK_ID=xxx` `API_BASE=xxx`，优先级高于 `config.json`
- 导入完成后自动检查并修复 TOC 章节顺序