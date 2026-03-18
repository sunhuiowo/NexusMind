# ChatGPT 风格多会话面板设计

**Date**: 2026-03-18
**Topic**: 垂直堆叠多会话面板

## 1. 概述

将现有的单会话聊天界面改为支持多个垂直堆叠的会话面板，每个面板独立运行、消息隔离，并实现并发控制防止同时发消息。

## 2. 目标

- 每个新建会话在主区域新增一个独立的 panel
- 每个 panel 有独立的标题栏、消息滚动区、输入框
- 消息完全隔离，通过 localStorage 持久化
- 当任一会话发消息时，其他会话输入框自动禁用并显示提示

## 3. UI/UX 设计

### 3.1 布局结构

```
┌─────────────┬─────────────────────────────────────┐
│   Sidebar   │  ┌─────────────────────────────┐   │
│             │  │ Session 1                    │   │
│  会话列表    │  │ ┌─────────────────────────┐ │   │
│  [+新建]    │  │ │ Messages...             │ │   │
│             │  │ └─────────────────────────┘ │   │
│             │  │ [Input..................] │   │
│             │  └─────────────────────────────┘   │
│             │  ┌─────────────────────────────┐   │
│             │  │ Session 2 (disabled)        │   │
│             │  │ ⚠️ 会话 1 正在查询中...     │   │
│             │  └─────────────────────────────┘   │
└─────────────┴─────────────────────────────────────┘
```

### 3.2 组件层级

- **Sidebar**: 保持不变，移除 URL 参数逻辑
- **Main Area**: 垂直排列多个 `ChatPanel` 组件
- **ChatPanel**: 独立会话面板，包含：
  - 标题栏（会话名 + 操作按钮）
  - 消息列表（可独立滚动）
  - 输入框（可独立禁用）

### 3.3 并发状态展示

- 禁用状态：输入框变灰，placeholder 显示 "等待中..."
- 提示信息：在输入框上方显示 "⚠️ 会话 [xxx] 正在查询中..."

## 4. 技术设计

### 4.1 Store 改动

**store/index.ts 新增**:
```typescript
interface GlobalState {
  isQuerying: boolean
  queryingSessionId: string | null
  setQuerying: (v: boolean, sessionId?: string) => void
}
```

### 4.2 组件拆分

| 文件 | 改动 |
|------|------|
| `App.tsx` | 渲染多个 `<ChatPanel />`，不再使用 Routes |
| `ChatPanel.tsx` (新建) | 从 Chat.tsx 提取的独立面板组件 |
| `Chat.tsx` | 保留但简化，仅作为 ChatPanel 包装器 |
| `store/index.ts` | 添加 isQuerying 状态 |

### 4.3 并发控制流程

```
用户提交查询
    ↓
setQuerying(true, sessionId)
    ↓
所有 ChatPanel 检测到 isQuerying=true
    ↓
当前会话输入框正常
其他会话输入框禁用 + 显示提示
    ↓
查询完成 (成功或失败)
    ↓
setQuerying(false)
    ↓
所有输入框恢复
```

### 4.4 数据流

```
Sidebar 点击新建会话
    ↓
useSessionStore.createSession()
    ↓
App 检测到 sessions 变化
    ↓
渲染新的 ChatPanel (sessionId)
    ↓
ChatPanel 加载对应 session 的 messages
```

## 5. 兼容性

- 保留现有的 localStorage 持久化机制
- 已有会话数据自动迁移
- 移除 URL 参数依赖 (`?session=xxx`)

## 6. 边界情况

- 无会话时：显示空白区域 + 提示新建会话
- 所有会话都空闲：正常交互
- 页面刷新：保持现有会话状态
