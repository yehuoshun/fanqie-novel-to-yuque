# 番茄小说 → 语雀 导入工具

将番茄小说（fanqienovel.com）完整章节内容导入语雀知识库。

## 解决的问题

- **番茄小说反爬**：自定义字体加密，直接抓取是乱码，配合开源字体映射字典可解码
- **内容预览限制**：网页只显示 200 字预览，完整内容需登录/VIP
- **第三方 API**：通过 `http://101.35.133.34:5000/api/raw_full` 获取完整纯文本章节内容（无需字体解码）

## 工具链

### 1. 字体解码
- **来源**：[romcere/fanqienovel-decryptor](https://github.com/romcere/fanqienovel-decryptor) (⭐52)
- 提供字体映射字典 `dicts/font_map.py`，将私有 Unicode 字符映射回正常中文

### 2. 章节列表获取
直接从番茄小说书籍页面解析，提取 430 章 URL 和标题，去重保存为 JSON。

### 3. 内容获取
使用第三方 API 获取完整章节内容：
```
GET http://101.35.133.34:5000/api/raw_full?item_id={item_id}
```
返回纯文本 HTML，无需字体解码，无预览限制。

### 4. 语雀上传
- **`yuque_mcp_client.js`**：Node.js 脚本，直接连接 yuque-mcp MCP 服务器（JSON-RPC），绕过 shell 管道转义问题
- **`batch_import_final_v2.py`**：批量导入脚本，支持断点续传、重试、进度记录

## 使用流程

### 完整工作流（推荐）
自动创建语雀知识库 → 移动到小说分组 → 生成章节列表 → 批量导入

```bash
# 先安装依赖
无需额外安装，依赖 mcporter + yuque-mcp

# 执行完整流程
python3 yuque_import_workflow.py \
    --book-id 7220383810771225655 \
    --title "穿越三年，你就给我这个破系统？" \
    --alias "不对劲！我这修仙系统有毒！" \
    --author "暗影玩具车" \
    --description "作品简介原文"
```

### 仅导入已有知识库
```bash
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
| `batch_import_final_v2.py` | 批量导入主脚本（Python） |
| `yuque_import_workflow.py` | 完整工作流脚本（创建知识库+移动分组+导入章节） |
| `yuque_mcp_client.js` | MCP 客户端（Node.js，直接调用 yuque-mcp 服务器） |
| `yuque_pipe.sh` | Shell 管道包装器（备选方案） |
| `config.json` | 配置文件（`book_id`、`api_base`、`yuque_config` 等） |

## 注意事项

- 第三方 API 可能有调用频率限制，脚本内置 0.5s 间隔
- 进度文件：`/tmp/novel_final_progress.json`（支持断点续传）
- 章节列表：`/tmp/chapter_list.json`
- 语雀知识库 ID 在 `config.json` 中配置，修改 `book_id` 即可
- 支持环境变量覆盖：`BOOK_ID=xxx` `API_BASE=xxx`，优先级高于 `config.json`
