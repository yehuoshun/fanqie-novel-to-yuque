# 小说（TXT / EPUB）→ 语雀 导入工具

本地小说 **txt / epub 文件** → 解析章节 → 自动创建语雀知识库 + 批量导入 + TOC 排序修复。

> ~~之前的版本依赖番茄小说第三方抓取 API，已全部失效。现在改为纯本地文件解析，零网络依赖。~~
> 废弃的抓取脚本已归档到 `legacy/`。

## 核心思路

1. 用户提供本地文件（`.txt` 或 `.epub`，按扩展名自动识别）
2. 脚本自动切分章节（txt 按中文章节标题正则；epub 按 spine + heading / 标题行）
3. 通过 `mcporter` 调 `yuque-mcp` 创建知识库 → 批量创建文档 → 修复 TOC 顺序

## 依赖

- **mcporter**：MCP 调用工具（已预装）
- **yuque-mcp**：语雀 MCP 服务器（OpenClaw 管理）
- **第三方 Python 包**：不需要（纯标准库，含 epub 解析）

## 使用方法

### 完整流程（推荐）

自动创建语雀知识库 → 放入小说分组 → 解析章节 → 批量导入 → 修复 TOC。

```bash
python3 yuque_import_workflow.py \
    --txt /path/to/novel.txt \
    --title "书名" \
    --author "作者" \
    --description "简介"
```

`yuque_import_workflow.py` 会自动调 `txt_import.py` 干活，本质是同一个入口。

### 分步操作

```bash
# 只解析不导入（预览章节列表）
python3 txt_import.py --txt novel.txt --dry-run

# EPUB 同理（--file 是 --txt 的别名，按扩展名自动识别）
python3 txt_import.py --file novel.epub --dry-run

# 导入到已有知识库（读 config.json 的 yuque_repo_id）
python3 txt_import.py --txt novel.txt

# 分批导入（大文件防超时）
python3 txt_import.py --txt novel.txt --start 1 --end 200

# 创建新知识库 + 导入（epub 的书名/作者/简介可从元数据自动带出）
python3 txt_import.py --file novel.epub --create --title "书名" --author "作者"

# 不修 TOC（导入完成后文档顺序可能不对）
python3 txt_import.py --txt novel.txt --no-toc-fix
```

### EPUB 支持（2026-09-27 新增）

`epub_reader.py` 纯标准库解析（zipfile + xml + html.parser），**零第三方依赖**。

- 按 OPF `spine` 阅读顺序取 xhtml；`dc:title` / `dc:creator` / `dc:description`
  自动作为 `--title` / `--author` / `--description` 的缺省值（命令行显式传参优先）
- 章节切分**逐 xhtml 判定**：

| epub 结构 | 切分方式 |
|-----------|----------|
| 该 xhtml 有 `h1`/`h2`/`h3` | 只按 heading 切（正文行不参与判定，防误切） |
| 该 xhtml 无 heading | 按章节标题行切（同 txt 规则） |
| 完全识别不到标题 | 兜底「每个 xhtml 一章」（标题取首个 heading 或文件名） |

- 标题之前的内容（封面/版权页）兜底为「前言」章，**不静默丢正文**
- 单独预览：`python3 epub_reader.py novel.epub`

### 章节标题识别规则（txt / epub 通用）

支持以下格式（一行内单独出现，不超过 50 字符）：

| 类型 | 示例 |
|------|------|
| 中文数字章节 | 第1章、第一章、第三十五回、第二集 |
| 特殊章节 | 楔子、序章、序言、前言、引子 |
| 结尾章节 | 尾声、终章、后记、完结感言 |
| 番外 | 番外、外传 |

## 文件说明

| 文件 | 用途 |
|------|------|
| `txt_import.py` | **核心脚本**：解析（txt/epub）+ 上传语雀 + 进度管理 + 分批导入 |
| `epub_reader.py` | EPUB 解析后端（container→OPF→spine→xhtml→章节，纯标准库） |
| `yuque_import_workflow.py` | 工作流入口壳（转发到 `txt_import.py`） |
| `reorder_toc.py` | TOC 章节顺序修复（从后往前修正错位文档） |
| `config.json` | 配置文件（`yuque_repo_id` 和 `yuque_config.user_login`） |
| `progress/` | 进度 + 章节列表目录（按知识库 ID 隔离：`progress_<book_id>.json` / `chapters_<book_id>.json`） |
| `legacy/` | 废弃的番茄抓取脚本（`batch_import_final_v2.py`、`fanqie_tools.py`、`font_decoder.py`） |

## 注意事项

- 章节切分基于正则匹配标题行，**确保 txt 中每章标题独占一行**
- EPUB 走 `spine` 顺序，不支持 DRM 加密的 epub（加密文件在 `META-INF/encryption.xml`）
- 默认每 0.5 秒上传一章（防限流），可通过 `--interval` 调整
- 进度文件按知识库 ID 隔离（`progress/progress_<book_id>.json`），**不同库/不同书互不干扰，无需手动清进度**
- 章节列表也按库隔离（`progress/chapters_<book_id>.json`），供 TOC 修复使用
- TOC 修复只在全部章节导入完成后自动执行

## 常见问题

**Q: 解析不到章节？**
A: 检查标题格式是否符合 `第X章` / `楔子` / `番外` 等。如果自定义格式，需要修改 `_TITLE_RE` 正则。

**Q: EPUB 解析出来章数不对？**
A: 先用 `python3 epub_reader.py novel.epub` 单独看切分结果。若书里用 `<p class="chapter">` 之类
样式而不是 heading，会走标签行规则；结构过于畸形（如 txt 粗转的 epub、回目被拆多行）时切分可能不准。

**Q: 导入到一半断了怎么办？**
A: 重新跑同样的命令即可，脚本会读取进度文件跳过已导入的章节。上传阶段幂等。

**Q: 书太多分几次导入？**
A: 用 `--start 1 --end 100` 只导前 100 章，下次 `--start 101 --end 200` 续。

## 更新记录

### 2026-10-04：进度/章节列表按知识库隔离 + MCP_WORKDIR 可配置

- 进度文件从单文件 `txt_progress.json` 改为按库隔离 `progress_<book_id>.json`，同一知识库导入多本书不再串章/漏章
- 章节列表从写死 `/tmp/chapter_list.json` 改为 `chapters_<book_id>.json`（`reorder_toc.py` 默认路径同步）
- `MCP_WORKDIR` 改为环境变量可覆盖（默认仍为 workspace），换环境不用改代码

### 2026-09-27：新增 EPUB 支持

- 新增 `epub_reader.py`（纯标准库，零新依赖）
- `txt_import.py` 按扩展名自动分发；`--file` 作为 `--txt` 别名
- EPUB 元数据自动带出书名/作者/简介；首页内容兜底「前言」不丢正文

## 迁移说明（2026-09-20）

原版依赖番茄小说第三方抓取 API，目前所有公共接口均失效（仅存私有源不公开）。

改造内容：
- `legacy/` 遗留的抓取脚本不再使用
- 移除 `curl_cffi`、`fonttools`、`pillow`、`numpy` 依赖
- 编码自动探测不依赖 `charset.json`（现逐文件 auto-detect utf-8/gb18030/big5）