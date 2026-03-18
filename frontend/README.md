# Personal AI Memory — 前端

基于 React 18 + TypeScript + Tailwind CSS 构建的前端界面，与后端 FastAPI 服务前后端分离。

## 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18.x | UI 框架 |
| TypeScript | 5.x | 类型安全 |
| Vite | 5.x | 构建工具（含热重载） |
| Tailwind CSS | 3.x | 原子化样式 |
| Zustand | 4.x | 全局状态 |
| React Query | 5.x | 服务端状态 |
| Axios | 1.x | HTTP 请求 |
| React Router | 6.x | 路由 |

## 快速启动

```bash
# 1. 安装依赖
npm install

# 2. 启动开发服务器（自动代理 API 到 localhost:8000）
npm run dev
# → http://localhost:5173
```

> 确保后端已在 `http://localhost:8000` 运行

## 生产构建

```bash
npm run build
# 输出到 dist/ 目录，可用 nginx 等静态服务器托管
```

## 页面结构

| 路由 | 页面 | 说明 |
|------|------|------|
| `/` | Chat | 问答主页，和记忆库对话 |
| `/library` | Library | 浏览、搜索、管理所有收藏 |
| `/platforms` | Platforms | 管理各平台连接状态 |
| `/sync` | Sync | 触发同步、查看日志 |
| `/settings` | Settings | 配置 LLM、Whisper、同步参数等 |

## API 代理

开发环境下 Vite 自动代理：
```
/api/* → http://localhost:8000/*
```

生产环境需在 nginx 中配置反向代理，或将 `VITE_API_BASE` 环境变量指向后端地址。

## 目录结构

```
src/
├── api/
│   ├── apiClient.ts    # Axios 封装，所有接口
│   └── types.ts        # 与后端 schema 对应的 TS 类型
├── components/
│   ├── ChatInput.tsx   # 输入框（含语音输入）
│   ├── MemoryCard.tsx  # 单条记忆卡片
│   ├── PlatformCard.tsx# 平台连接卡片
│   └── QueryResultCard.tsx # 标准化问答结果
├── pages/
│   ├── Chat.tsx        # 问答页
│   ├── Library.tsx     # 记忆库
│   ├── Platforms.tsx   # 平台管理
│   ├── Sync.tsx        # 同步控制
│   └── Settings.tsx    # 系统设置
├── store/
│   └── index.ts        # Zustand stores
├── ui/
│   ├── Sidebar.tsx     # 侧边导航
│   └── Toast.tsx       # 通知组件
├── utils/
│   └── index.ts        # 工具函数、常量
├── App.tsx             # 路由 + 布局
├── main.tsx            # 入口
└── index.css           # 全局样式 + 设计系统
```
