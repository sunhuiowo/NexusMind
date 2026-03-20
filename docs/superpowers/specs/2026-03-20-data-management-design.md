# 数据管理功能设计

## 概述

为 Personal AI Memory 系统新增数据管理 API，包括导出、导入、清理旧记忆、重置配置、清空记忆等功能。

## 背景

前端 Settings 页面已完成 UI 重构，新增了数据管理、关于、危险操作等分区。其中「导出记忆」「导入记忆」「清理旧记忆」「重置所有配置」「清空所有记忆」五个按钮需要后端 API 支持。

## 用户决策

- **导入重复处理**：覆盖（用导入版本替换）
- **清理旧记忆条件**：仅按时间（超过 N 天未访问）
- **重置配置范围**：全部重置，包含 API Key
- **导出数据**：完整数据（包含所有元数据字段）

## API 设计

### 1. 导出记忆
- **端点**：`GET /memories/export`
- **认证**：需要用户登录
- **Query 参数**：无
- **响应**：JSON 文件下载
  ```json
  {
    "version": "1.0",
    "exported_at": "2026-03-20T10:00:00Z",
    "user_id": "user_xxx",
    "memories": [
      {
        "platform": "youtube",
        "platform_name": "YouTube",
        "platform_id": "abc123",
        "title": "视频标题",
        "summary": "视频摘要",
        "tags": ["tag1", "tag2"],
        "source_url": "https://youtube.com/...",
        "bookmarked_at": "2026-01-01T00:00:00Z",
        "importance": 0.85,
        "query_count": 5,
        "media_type": "video",
        "author": "UP主名称",
        "thumbnail_url": "https://example.com/thumb.jpg"
      }
    ]
  }
  ```
- **Content-Type**：`application/json`
- **文件名**：`memories_export_20260320_100000.json`
- **大文件处理**：若记忆数量超过 10000 条，分批查询并流式写入 JSON，避免内存峰值

### 2. 导入记忆
- **端点**：`POST /memories/import`
- **认证**：需要用户登录
- **请求体**：multipart/form-data，字段名 `file`
- **导入逻辑**：
  1. 解析上传的 JSON 文件
  2. 校验 version 字段（仅支持 "1.0"）
  3. 遍历 memories：
     - 如果 `platform + platform_id` 已存在 → 覆盖更新（保留 id 和 `last_accessed_at`，更新其他字段）
     - 如果不存在 → 新增，`last_accessed_at` 初始化为当前时间
  4. 批量写入 SQLite + FAISS
- **响应**：
  ```json
  {
    "success": true,
    "imported": 10,
    "updated": 5,
    "failed": 0,
    "errors": []
  }
  ```
- **错误处理**：
  - version 不匹配：返回 400
  - JSON 解析失败：返回 400
  - `bookmarked_at` 格式无效：使用当前时间作为默认值
  - 部分失败时返回成功但包含错误列表，错误格式为 `{"index": 5, "platform_id": "abc", "error": "错误描述"}`

### 3. 清理旧记忆
- **端点**：`DELETE /memories/old`
- **认证**：需要用户登录
- **Query 参数**：`days`（默认 180）
- **删除条件**：`last_accessed_at < (now - days)`，同时清理 `last_accessed_at` 为 NULL 或空字符串的孤立记录
- **响应**：
  ```json
  {
    "success": true,
    "deleted_count": 42
  }
  ```

### 4. 重置所有配置
- **端点**：`POST /config/reset`
- **认证**：需要用户登录
- **行为**：
  - 清空 `runtime_config.json` 文件
  - 所有配置恢复为默认值（从环境变量和硬编码默认值读取）
  - 包含 API Key 等敏感凭证
- **响应**：
  ```json
  {
    "success": true
  }
  ```

### 5. 清空所有记忆
- **端点**：`DELETE /memories/all`
- **认证**：需要用户登录
- **Query 参数**：`confirm=true`（必填，防止误操作）
- **行为**：
  - 删除当前用户的 SQLite 数据
  - 重建空 FAISS 索引
  - 不影响其他用户数据
- **响应**：
  ```json
  {
    "success": true,
    "deleted_count": 128
  }
  ```
- **错误**：若 `confirm` 不为小写 `"true"`（大小写不敏感），返回 400

## 路由文件

新建 `backend/routers/data_management.py`，包含以上 5 个端点。

## 数据模型

### ImportMemory（导入数据结构）
```python
class ImportMemory(BaseModel):
    platform: str
    platform_name: str
    platform_id: str
    title: str
    summary: str
    tags: List[str] = []
    source_url: str
    bookmarked_at: str  # ISO format
    importance: float = 0.5
    query_count: int = 0
    media_type: str = "text"
    author: str = ""
    thumbnail_url: str = ""
```

### ExportData（导出数据结构）
```python
class ExportData(BaseModel):
    version: str = "1.0"
    exported_at: str
    user_id: str
    memories: List[ImportMemory]
```

## 实现要点

1. **用户隔离**：所有操作均需通过 `user_id` 参数隔离用户数据
2. **批量处理**：导入使用 `add_batch` 提升性能
3. **去重逻辑**：基于 `platform + platform_id` 判断重复
4. **FAISS 重建**：清空记忆后需要重建空索引而非删除文件
5. **安全防护**：`confirm` 参数防止误操作

## 测试计划

1. 导出后重新导入验证数据完整性
2. 导入覆盖重复数据验证更新行为
3. 清理旧记忆验证条件正确
4. 重置配置后验证 API Key 被清空
5. 清空记忆后验证其他用户数据不受影响

## 文件变更

- 新建：`backend/routers/data_management.py`
- 修改：`backend/main.py`（注册新路由）
