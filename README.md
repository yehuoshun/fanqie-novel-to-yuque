# TXT 小说 → 语雀 导入工具

本地小说 **txt 文件** → 解析章节 → 自动创建语雀知识库 + 批量导入 + TOC 排序修复。

> ~~之前的版本依赖番茄小说第三方抓取 API，已全部失效。现在改为纯本地文件解析，零网络依赖。~~
> 废弃的抓取脚本已归档到 `legacy/`。

## 核心思路

1. 用户提供本地 `.txt` 文件（从任何来源获取的完整小说文本）
2. 脚本自动按中文章节标题格式（`第X章`、`楔子`、`番外` 等）切分章节
3. 通过 `mcporter` 调 `yuque-mcp` 创建知识库 → 批量创建文档 → 修复 TOC 顺序

## 依赖

- **mcporter**：MCP 调用工具（已预装）
- **yuque-mcp**：语雀 MCP 服务器（OpenClaw 管理）
- **第三方 Python 包**：不需要（纯标准库）

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

# 导入到已有知识库（读 config.json 的 yuque_repo_id）
python3 txt_import.py --txt novel.txt

# 分批导入（大文件防超时）
python3 txt_import.py --txt novel.txt --start 1 --end 200

# 创建新知识库 + 导入
python3 txt_import.py --txt novel.txt --create --title "书名" --author "作者"

# 不修 TOC（导入完成后文档顺序可能不对）
python3 txt_import.py --txt novel.txt --no-toc-fix
```

### 章节标题识别规则

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
| `txt_import.py` | **核心脚本**：解析 txt + 上传语雀 + 进度管理 + 分批导入 |
| `yuque_import_workflow.py` | 工作流入口壳（转发到 `txt_import.py`） |
| `reorder_toc.py` | TOC 章节顺序修复（从后往前修正错位文档） |
| `config.json` | 配置文件（`yuque_repo_id` 和 `yuque_config.user_login`） |
| `progress/` | 进度文件目录（断点续传） |
| `legacy/` | 废弃的番茄抓取脚本（`batch_import_final_v2.py`、`fanqie_tools.py`、`font_decoder.py`） |

## 注意事项

- 章节切分基于正则匹配标题行，**确保 txt 中每章标题独占一行**
- 默认每 0.5 秒上传一章（防限流），可通过 `--interval` 调整
- 进度文件 `progress/txt_progress.json`，自动断点续传
- 同一知识库导入第二本小说前，**需先手动清空进度文件**（或使用 `--start` 指定起始章）
- TOC 修复只在全部章节导入完成后自动执行

## 常见问题

**Q: 解析不到章节？**
A: 检查标题格式是否符合 `第X章` / `楔子` / `番外` 等。如果自定义格式，需要修改 `_TITLE_RE` 正则。

**Q: 导入到一半断了怎么办？**
A: 重新跑同样的命令即可，脚本会读取进度文件跳过已导入的章节。上传阶段幂等。

**Q: 书太多分几次导入？**
A: 用 `--start 1 --end 100` 只导前 100 章，下次 `--start 101 --end 200` 续。

## 迁移说明（2026-09-20）

原版依赖番茄小说第三方抓取 API，目前所有公共接口均失效（仅存私有源不公开）。

改造内容：
- `legacy/` 遗留的抓取脚本不再使用
- 移除 `curl_cffi`、`fonttools`、`pillow`、`numpy` 依赖
- 编码自动探测不依赖 `charset.json`（现逐文件 auto-detect utf-8/gb18030/big5）