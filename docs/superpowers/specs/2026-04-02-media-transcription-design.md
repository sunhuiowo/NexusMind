# 音视频转录知识库设计

**日期**: 2026-04-02
**状态**: Approved

## 1. 背景与目标

**问题**:
- 当前收藏知识库只存储文本内容，视频/音频（如 Bilibili/YouTube）中的语音信息无法被检索
- 用户需要在查询时能问答视频内容，但实时转录响应慢

**目标**:
- 同步收藏夹时自动转录音视频内容，存储 transcript 到知识库
- 查询时直接用已有 transcript，响应快
- 支持多平台（Bilibili、YouTube、Douyin等），可扩展

## 2. 核心设计

### 2.1 统一音视频解析层架构

```
Platform → Connector → CollectorAgent
                           │
                    ┌──────▼──────┐
                    │ MediaRouter │
                    └──────┬──────┘
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         TextParser   VideoParser  AudioParser
              │            │            │
              └────────────┼────────────┘
                           ▼
                    UnifiedMediaParser
                    (subtitle → ASR)
```

### 2.2 核心组件

#### ASRService (`backend/tools/asr_service.py`)

统一 ASR 调用服务，整合现有 ASR 能力：

```python
class ASRService:
    """统一 ASR 服务，支持 qwen 和 whisper provider"""

    def transcribe(self, audio_source: str | Path, platform: str) -> str:
        """
        转录音频
        audio_source: 音频文件路径 或 音频URL
        platform: 平台标识
        返回: 转录文本
        """

    def extract_audio_from_video(self, video_url: str, output_path: Path) -> Path:
        """从视频URL提取音频，返回音频文件路径"""

    def _call_asr(self, audio_path: Path) -> str:
        """内部调用实际的ASR provider"""
```

**Provider 支持**:
- `qwen`: 调用 qwen3-asr-1.7b (vLLM API)
- `whisper`: 本地 Whisper 推理

#### MediaParser Protocol

```python
from typing import Protocol, Optional
from dataclasses import dataclass

@dataclass
class ParsedMediaContent:
    transcript: str           # 转录文本
    source: str               # "subtitle" | "asr" | "description"
    media_type: str           # "video" | "audio"
    language: Optional[str]   # 音频语言，用于ASR

class MediaParser(Protocol):
    """音视频解析器接口"""

    def supports(self, url: str) -> bool:
        """判断是否支持此URL"""

    def parse(self, url: str, media_type: str, credentials: dict = None) -> Optional[ParsedMediaContent]:
        """
        解析音视频
        策略: subtitle → ASR
        """

    def get_audio_url(self, url: str, credentials: dict = None) -> Optional[str]:
        """获取音频URL（用于ASR）"""
```

#### MediaRouter (`backend/parsers/media_router.py`)

路由层，根据 URL 和 media_type 分发到对应 Parser：

```python
class MediaRouter:
    """音视频解析路由"""

    def __init__(self):
        self._parsers: list[MediaParser] = []

    def register(self, parser: MediaParser):
        """注册parser"""

    def route(self, content: RawContent) -> Optional[ParsedMediaContent]:
        """
        路由并解析
        - 纯文本平台(GitHub) → 直接返回 None，跳过
        - 音视频平台 → 找到对应parser解析
        """
```

#### 平台 Parser 实现

| Parser | 文件 | 说明 |
|--------|------|------|
| `BilibiliMediaParser` | `backend/parsers/bilibili_parser.py` | 改造现有逻辑，使用 ASRService |
| `YouTubeMediaParser` | `backend/parsers/youtube_parser.py` | 新建，支持字幕 + ASR |
| `DouyinMediaParser` | `backend/parsers/douyin_parser.py` | 新建（可选） |
| `AudioMediaParser` | `backend/parsers/audio_parser.py` | 通用音频，直接 ASR |

### 2.3 配置项

新增配置（`backend/config.py` + Settings 前端）：

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `SYNC_ASR_ENABLED` | bool | true | 同步时是否启用ASR |
| `SYNC_RECENT_WINDOW_DAYS` | int | 90 | 只ASR最近N天内的收藏（用户可调） |
| `ASR_PROVIDER` | str | "qwen" | ASR provider: qwen / whisper |
| `BILIBILI_ASR_ENABLED` | bool | true | Bilibili ASR开关 |
| `YOUTUBE_ASR_ENABLED` | bool | true | YouTube ASR开关 |

### 2.4 数据流

```
CollectorAgent.sync_single_platform()
   │
   ▼
Connector.fetch_all_with_content()
   │  返回: List[RawContent]
   ▼
MediaRouter.route(content)
   │
   ├─ media_type == "text" → 直接存储
   │
   └─ media_type in ("video", "audio") → UnifiedMediaParser
                                        │
                                  ┌─────▼─────┐
                                  │ subtitle?  │
                                  └─────┬─────┘
                                   有    │    没有
                                   ▼         ▼
                              提取字幕    ASRService.transcribe()
                                   │         │
                                   └────┬────┘
                                        ▼
                                   transcript
                                        │
                                        ▼
                              content.raw_content = transcript
                                        │
                                        ▼
                              MemoryBuilder.build_memory_from_content()
                                        │
                                        ▼
                              MemoryStore.add() → FAISS + SQLite
```

### 2.5 YouTube Parser 详细设计

```python
class YouTubeMediaParser:
    """YouTube 音视频解析器"""

    BASE_URL = "https://www.youtube.com"

    def supports(self, url: str) -> bool:
        return "youtube.com" in url or "youtu.be" in url

    def parse(self, url: str, media_type: str, credentials: dict = None) -> Optional[ParsedMediaContent]:
        # 1. 获取视频信息 (ytdl 或 YouTube API)
        # 2. 优先下载字幕 (自动字幕或手动字幕)
        # 3. 无字幕 → 获取音频URL → ASRService.transcribe()
        # 4. 返回 ParsedMediaContent
```

**字幕获取策略**:
1. 请求 `youtube.com/api/timedtext` 获取手动字幕
2. 无手动字幕 → 请求 `api/timedtext?type=asr` 获取自动字幕
3. 无字幕 → ASR

**音频获取**:
- 通过 `ytdl` 或 `yt-dlp` 获取音频流 URL
- 传给 ASRService

## 3. 前端配置

Settings 页面新增 ASR 配置区块：

```
┌─────────────────────────────────────┐
│ 音视频转录设置                          │
├─────────────────────────────────────┤
│ [✓] 同步时自动转录                      │
│                                     │
│ 转录范围: [____90____] 天内的收藏       │
│ (留空或0表示全部)                       │
│                                     │
│ ASR Provider: (●) Qwen  ( ) Whisper │
│                                     │
│ [✓] Bilibili  [✓] YouTube           │
└─────────────────────────────────────┘
```

## 4. 关键文件修改

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/tools/asr_service.py` | 新建 | 统一ASR服务 |
| `backend/parsers/media_router.py` | 新建 | 路由层 |
| `backend/parsers/bilibili_parser.py` | 改造 | 实现MediaParser protocol |
| `backend/parsers/youtube_parser.py` | 新建 | YouTube解析器 |
| `backend/parsers/audio_parser.py` | 改造 | 实现MediaParser protocol |
| `backend/parsers/douyin_parser.py` | 可选新建 | Douyin解析器 |
| `backend/config.py` | 改造 | 新增ASR配置项 |
| `backend/agents/collector_agent.py` | 改造 | 集成MediaRouter |
| `backend/tools/mcp_tools.py` | 改造 | ASR配置MCP工具 |
| `frontend/src/pages/Settings.tsx` | 改造 | ASR配置UI |

## 5. 可扩展性

未来添加新平台只需：

1. 实现 `MediaParser` protocol
2. 在 `MediaRouter` 注册
3. 在 connector 返回正确的 `media_type`

```
新平台 → 继承 MediaParser → register到MediaRouter → 自动路由
```

## 6. 错误处理

| 场景 | 处理 |
|------|------|
| 字幕下载失败 | 回退到 ASR |
| ASR 服务不可用 | 记录日志，标记 `source: "error"`，不阻塞同步 |
| 音频URL获取失败 | 使用 description 作为 fallback |
| 视频无音频流 | 跳过ASR，直接存储 |
| ASR 超时 | 重试1次，还失败则跳过 |

## 7. 验证方案

1. **单元测试**: 各个 Parser 的 subtitle/ASR 分支
2. **集成测试**: 完整同步流程（mock ASR）
3. **手动验证**:
   - Bilibili 视频（有字幕/无字幕）
   - YouTube 视频
   - GitHub 纯文本（确认不触发ASR）
