# 用户隔离系统设计文档

**日期**: 2026-03-19
**主题**: 多用户隔离认证与数据隔离系统

---

## 1. 概述

### 目标
实现完整的多用户隔离系统，确保：
- 每个注册用户有独立的认证、记忆库、平台凭证
- 只有认证用户才能访问系统
- 管理员可管理所有用户

### 架构概览

```
前端 → 后端API → SessionMiddleware → 用户上下文 → 隔离执行
         ↓
    SQLite: users + sessions 表
    TokenStore: auth/{user_id}/
    MemoryStore: memories_{user_id}.db + faiss/{user_id}/
```

---

## 2. 数据库设计

### 存储位置
`data/users.db`

### 表结构

#### users 表
```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,           -- user_xxx 格式
    username TEXT UNIQUE NOT NULL, -- 用户名
    password_hash TEXT NOT NULL,   -- bcrypt 哈希
    is_admin INTEGER DEFAULT 0,    -- 是否管理员
    created_at TEXT NOT NULL       -- ISO 8601 时间戳
);
```

#### sessions 表
```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,   -- 随机 UUID
    user_id TEXT NOT NULL,         -- 关联 users.id
    created_at TEXT NOT NULL,      -- 创建时间
    expires_at TEXT NOT NULL,      -- 过期时间
    FOREIGN KEY (user_id) REFERENCES users(id)
);
```

---

## 3. API 设计

### 认证端点

| 端点 | 方法 | 说明 | 认证要求 |
|---|---|---|---|
| `/auth/register` | POST | 注册新用户 | 无 |
| `/auth/login` | POST | 登录 | 无 |
| `/auth/logout` | POST | 登出 | 需要 |
| `/auth/me` | GET | 获取当前用户信息 | 需要 |

### 请求/响应格式

#### POST /auth/register
```json
// Request
{ "username": "string", "password": "string" }

// Response 201
{ "success": true, "user_id": "user_xxx", "username": "xxx" }

// Response 400
{ "success": false, "error": "用户名已存在" }
```

#### POST /auth/login
```json
// Request
{ "username": "string", "password": "string" }

// Response 200
{
  "success": true,
  "session_id": "uuid",
  "user_id": "user_xxx",
  "username": "xxx",
  "is_admin": false
}

// Response 401
{ "success": false, "error": "用户名或密码错误" }
```

#### GET /auth/me
```json
// Response 200
{ "user_id": "user_xxx", "username": "xxx", "is_admin": false }

// Response 401
{ "error": "未登录" }
```

### 管理员端点

| 端点 | 方法 | 说明 | 认证要求 |
|---|---|---|---|
| `/admin/users` | GET | 用户列表 | 管理员 |
| `/admin/users/{id}` | DELETE | 删除用户 | 管理员 |

#### GET /admin/users
```json
// Response 200
{
  "users": [
    { "id": "user_xxx", "username": "xxx", "is_admin": false, "created_at": "..." },
    ...
  ]
}
```

#### DELETE /admin/users/{id}
```json
// Response 200
{ "success": true }

// Response 400
{ "success": false, "error": "无法删除管理员账户" }
```

---

## 4. 会话管理

### Session 中间件流程

```
1. 请求进入
2. 检查是否需要认证（白名单：/auth/register, /auth/login, /health）
3. 获取 session_id（从 header X-Session-Id 或 Cookie）
4. 查询 sessions 表验证
5. 验证失败 → 返回 401
6. 验证成功 → 设置 user_id 到 ContextVar
7. 调用下一个处理器
8. 请求结束后清理上下文
```

### Session 过期
- 默认 7 天过期
- 每次有效请求刷新过期时间

---

## 5. 数据隔离

### 存储路径结构

```
data/
├── users.db                    # 用户和会话数据
├── memories.db                # (向后兼容) 默认用户数据
├── faiss_index.index           # (向后兼容) 默认向量索引
└── auth/
    ├── youtube_tokens.enc      # (向后兼容) 默认凭证
    └── {user_id}/
        ├── memories_{user_id}.db
        ├── faiss/
        │   └── {user_id}/
        │       └── index.faiss
        └── {platform}_tokens.enc
```

### 各模块隔离

| 模块 | 隔离方式 |
|---|---|
| MemoryStore | `get_memory_store(user_id)` → 独立 DB + FAISS |
| TokenStore | `get_token_store(user_id)` → 独立加密文件 |
| 会话 | sessions 表按 user_id 索引 |

---

## 6. 修改现有代码

### 6.1 新增文件

- `backend/auth/user_store.py` - 用户和会话管理
- `backend/auth/session_middleware.py` - Session 验证中间件

### 6.2 修改文件

| 文件 | 修改内容 |
|---|---|
| `backend/main.py` | 替换 UserIsolationMiddleware 为 SessionMiddleware |
| `backend/auth/token_store.py` | 确保 get_token_store(user_id) 正确工作 |
| `backend/tools/mcp_tools.py` | sync_platform 增加 user_id 参数 |
| `frontend/src/api/apiClient.ts` | 移除 X-User-Id，改为 X-Session-Id |
| `frontend/src/store/index.ts` | Auth store 改为调用后端 API |

### 6.3 删除/废弃

- `UserIsolationMiddleware` 中的 X-User-Id header 解析逻辑

---

## 7. 错误处理

| 场景 | 响应 |
|---|---|
| 未登录访问受保护资源 | 401 `{ "error": "请先登录" }` |
| Session 过期 | 401 `{ "error": "会话已过期，请重新登录" }` |
| 无权限（管理员操作） | 403 `{ "error": "需要管理员权限" }` |
| 用户不存在 | 404 `{ "error": "用户不存在" }` |

---

## 8. 实施步骤

### Phase 1: 基础架构
1. 创建 `user_store.py` - 用户注册、登录、session 管理
2. 创建 `session_middleware.py` - 会话验证中间件
3. 修改 `main.py` - 集成新中间件和 API

### Phase 2: 前端集成
1. 修改 `apiClient.ts` - 使用 session_id
2. 修改 Auth store - 调用后端 API
3. 添加注册/登录页面

### Phase 3: 完善隔离
1. 确保所有 API 正确传递 session
2. 修改 MCP 工具支持 user_id
3. 后台任务正确传递用户上下文

### Phase 4: 管理员功能
1. 添加 `/admin/*` 端点
2. 前端管理员界面（可选）

---

## 9. 向后兼容

- 没有 user_id 的请求默认使用 `_default` 用户
- CLI 命令继续使用默认存储
- 现有数据不受影响
