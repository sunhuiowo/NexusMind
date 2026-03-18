"""
main.py — v1.2.0
新增：GET /memories (真实列表+分页), GET/POST /config, 扫码认证, PAT/Cookie 设置
"""
import logging, sys, json
from pathlib import Path
from typing import Optional, List

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout),
              logging.FileHandler("personal_ai_memory.log", encoding="utf-8")])
logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

import config



def create_app():
    try:
        from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError:
        return None

    from agents.knowledge_agent import KnowledgeAgent
    from agents.collector_agent import CollectorAgent
    from tools.mcp_tools import (get_stats, delete_memory, update_importance,
        find_related, get_by_tags)
    from tools.llm import get_llm, get_embedder
    from memory.memory_store import get_memory_store
    from auth.oauth_handler import get_oauth_handler
    from auth.qrcode_auth import get_qrcode, poll_qrcode

    app = FastAPI(title="Personal AI Memory System", version="1.2.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    knowledge_agent = KnowledgeAgent()
    collector_agent = CollectorAgent()
    oauth_handler = get_oauth_handler()

    # ── Query ──────────────────────────────────────────────────────────────
    class QueryRequest(BaseModel):
        query: str
        voice: bool = False
        conversation_history: Optional[List[dict]] = None

    @app.post("/query")
    async def query_post(req: QueryRequest):
        result = knowledge_agent.query(req.query, conversation_history=req.conversation_history)
        if req.voice:
            knowledge_agent.format_response(result, voice=True)
        return result.to_dict()

    @app.get("/query")
    async def query_get(q: str, voice: bool = False):
        result = knowledge_agent.query(q)
        if voice:
            knowledge_agent.format_response(result, voice=True)
        return result.to_dict()

    # ── Memories list (真实分页+过滤) ──────────────────────────────────────
    @app.get("/memories")
    async def list_memories(
        platform: Optional[str] = None,
        media_type: Optional[str] = None,
        days: Optional[int] = None,
        tags: Optional[str] = None,
        query: Optional[str] = None,
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
        order_by: str = Query(default="bookmarked_at"),
    ):
        import sqlite3
        from memory.memory_schema import Memory, MemoryCard
        from datetime import datetime, timedelta

        store = get_memory_store()

        if query and query.strip():
            embedder = get_embedder()
            try:
                vec = embedder.embed(query.strip())
                results = store.search_by_vector(vec, top_k=page_size * 3,
                    platform_filter=platform, media_type_filter=media_type)
                items = []
                for m, score in results:
                    card = MemoryCard.from_memory(m, relevance_score=score)
                    d = card.__dict__.copy()
                    d["memory_id"] = m.id
                    items.append(d)
                return {"items": items, "total": len(items), "page": page,
                        "page_size": page_size, "has_more": False}
            except Exception as e:
                logger.warning(f"[API] vector search failed: {e}")
                return {"items": [], "total": 0, "page": page, "page_size": page_size, "has_more": False}

        db = config.METADATA_DB_PATH
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row

        conds, params = [], []
        if platform:
            conds.append("platform=?"); params.append(platform)
        if media_type:
            conds.append("media_type=?"); params.append(media_type)
        if days:
            cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
            conds.append("bookmarked_at >= ?"); params.append(cutoff)
        if tags:
            for tag in [t.strip() for t in tags.split(",") if t.strip()]:
                conds.append("tags LIKE ?"); params.append(f"%{tag}%")

        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        order_col = "importance DESC" if order_by == "importance" else "bookmarked_at DESC"
        total = conn.execute(f"SELECT COUNT(*) FROM memories {where}", params).fetchone()[0]
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"SELECT * FROM memories {where} ORDER BY {order_col} LIMIT ? OFFSET ?",
            params + [page_size, offset]
        ).fetchall()
        conn.close()

        items = []
        for row in rows:
            d = dict(row)
            d["tags"] = json.loads(d.get("tags") or "[]")
            d["related_ids"] = json.loads(d.get("related_ids") or "[]")
            d["embedding"] = []
            m = Memory.from_dict(d)
            card = MemoryCard.from_memory(m)
            cd = card.__dict__.copy()
            cd["memory_id"] = m.id
            items.append(cd)

        return {"items": items, "total": total, "page": page, "page_size": page_size,
                "has_more": (page * page_size) < total}

    @app.get("/memories/stats")
    async def stats_endpoint(platform: Optional[str] = None):
        return get_stats(platform_filter=platform)

    @app.get("/memories/{memory_id}")
    async def get_memory(memory_id: str):
        store = get_memory_store()
        m = store.get(memory_id)
        if not m:
            raise HTTPException(status_code=404, detail="记忆不存在")
        return m.to_dict()

    @app.get("/memories/{memory_id}/related")
    async def related_memories(memory_id: str, top_k: int = 5):
        return find_related(memory_id=memory_id, top_k=top_k).to_dict()

    class TagsRequest(BaseModel):
        tags: List[str]
        match_mode: str = "any"

    @app.post("/memories/search/tags")
    async def search_tags(req: TagsRequest):
        return get_by_tags(tags=req.tags, match_mode=req.match_mode).to_dict()

    @app.delete("/memories/{memory_id}")
    async def delete_endpoint(memory_id: str):
        if not delete_memory(memory_id):
            raise HTTPException(status_code=404, detail="记忆不存在")
        return {"success": True}

    class ImportanceUpdate(BaseModel):
        delta: Optional[float] = None
        set_value: Optional[float] = None

    @app.patch("/memories/{memory_id}/importance")
    async def update_imp(memory_id: str, body: ImportanceUpdate):
        return {"success": update_importance(memory_id=memory_id, delta=body.delta, set_value=body.set_value)}

    @app.post("/memories/{memory_id}/important")
    async def mark_important(memory_id: str):
        return {"success": update_importance(memory_id=memory_id, set_value=1.0)}

    # ── Sync ───────────────────────────────────────────────────────────────
    class SyncRequest(BaseModel):
        platform: Optional[str] = None
        full_sync: bool = False

    @app.post("/sync")
    async def sync_endpoint(req: SyncRequest, background_tasks: BackgroundTasks):
        if req.platform:
            background_tasks.add_task(collector_agent.sync_single_platform, req.platform, req.full_sync)
            return {"message": f"已启动 {req.platform} 同步"}
        background_tasks.add_task(collector_agent.sync_all_platforms, req.full_sync)
        return {"message": "已启动全平台同步"}

    class ResyncRequest(BaseModel):
        platform: Optional[str] = None

    @app.post("/resync")
    async def resync_endpoint(req: ResyncRequest, background_tasks: BackgroundTasks):
        """
        重新同步接口 - 先删除数据，再执行全量同步
        - 指定 platform: 仅重新同步该平台
        - 不指定 platform: 重新同步所有平台
        """
        if req.platform:
            background_tasks.add_task(collector_agent.resync_platform, req.platform)
            return {"message": f"已启动 {req.platform} 重新同步（先删除后全量同步）"}
        background_tasks.add_task(collector_agent.resync_all_platforms)
        return {"message": "已启动全平台重新同步（先删除后全量同步）"}

    # ── Auth ───────────────────────────────────────────────────────────────
    @app.get("/auth/status")
    async def auth_status():
        from auth.token_store import get_token_store
        store = get_token_store()
        return {p: store.get_status(p) for p in
                ["youtube","twitter","github","pocket","bilibili","wechat","douyin","xiaohongshu"]}

    @app.get("/auth/{platform}/connect")
    async def oauth_connect(platform: str):
        OAUTH_PLATFORMS = {"youtube", "twitter", "pocket"}
        if platform not in OAUTH_PLATFORMS:
            raise HTTPException(status_code=400, detail=f"{platform} 不使用标准 OAuth")
        try:
            auth_url, state = oauth_handler.get_auth_url(platform)
            return {"auth_url": auth_url, "state": state}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/auth/{platform}/qrcode")
    async def qrcode_start(platform: str):
        if platform not in {"bilibili", "douyin"}:
            raise HTTPException(status_code=400, detail=f"{platform} 不支持扫码")
        result = get_qrcode(platform)
        if "error" in result:
            raise HTTPException(status_code=502, detail=result["error"])
        return result

    @app.get("/auth/{platform}/qrcode/poll")
    async def qrcode_poll_endpoint(platform: str, qrcode_key: str):
        return poll_qrcode(platform, qrcode_key)

    @app.get("/auth/callback/{platform}")
    async def oauth_callback(platform: str, code: str, state: str):
        if oauth_handler.handle_callback(platform, code, state):
            return {"success": True}
        raise HTTPException(status_code=400, detail="授权失败")

    @app.delete("/auth/{platform}")
    async def revoke(platform: str):
        oauth_handler.revoke(platform)
        return {"success": True}

    class CookieBody(BaseModel):
        cookie: str

    @app.post("/auth/xiaohongshu/cookie")
    async def xhs_cookie(body: CookieBody):
        from platforms.xiaohongshu_connector import XiaohongshuConnector
        XiaohongshuConnector().save_cookie(body.cookie)
        return {"success": True}

    class WechatKeyBody(BaseModel):
        api_key: str

    @app.post("/auth/wechat/apikey")
    async def wechat_key(body: WechatKeyBody):
        from auth.token_store import get_token_store, TokenData
        from datetime import datetime
        get_token_store().save(TokenData(platform="wechat", auth_mode="apikey",
            api_key=body.api_key, status="connected",
            last_refresh=datetime.utcnow().isoformat()))
        return {"success": True}

    class PATBody(BaseModel):
        pat: str

    @app.post("/auth/github/pat")
    async def github_pat(body: PATBody):
        from auth.token_store import get_token_store, TokenData
        from datetime import datetime
        get_token_store().save(TokenData(platform="github", auth_mode="pat",
            access_token=body.pat, status="connected",
            last_refresh=datetime.utcnow().isoformat()))
        config.update_runtime({"GITHUB_PAT": body.pat})
        return {"success": True}

    class PocketTokenBody(BaseModel):
        access_token: str
        username: str = ""

    @app.post("/auth/pocket/token")
    async def pocket_token(body: PocketTokenBody):
        from auth.token_store import get_token_store, TokenData
        from datetime import datetime
        get_token_store().save(TokenData(platform="pocket", auth_mode="oauth2",
            access_token=body.access_token, status="connected",
            last_refresh=datetime.utcnow().isoformat(),
            extra={"username": body.username}))
        return {"success": True}

    # ── Config ─────────────────────────────────────────────────────────────
    @app.get("/config")
    async def get_config():
        return config.get_all_config()

    class ConfigBody(BaseModel):
        updates: dict

    @app.post("/config")
    async def post_config(body: ConfigBody):
        blocked = {"FAISS_INDEX_PATH", "METADATA_DB_PATH"}
        safe = {k: v for k, v in body.updates.items() if k not in blocked}
        config.update_runtime(safe)
        return {"success": True, "updated_keys": list(safe.keys())}

    @app.get("/config/test-llm")
    async def test_llm():
        return get_llm().test_connection()

    @app.get("/config/test-embedding")
    async def test_embedding():
        return get_embedder().test_connection()

    # ── Health ─────────────────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {"status": "ok", "version": "1.2.0",
                "total_memories": get_memory_store().get_stats().get("total", 0)}

    return app


def cli_main():
    import argparse
    parser = argparse.ArgumentParser(description="Personal AI Memory System")
    subs = parser.add_subparsers(dest="command")

    q = subs.add_parser("query"); q.add_argument("text")
    q.add_argument("--voice", action="store_true"); q.add_argument("--json", action="store_true")

    sy = subs.add_parser("sync")
    sy.add_argument("--platform"); sy.add_argument("--full", action="store_true")

    subs.add_parser("stats")

    srv = subs.add_parser("serve")
    srv.add_argument("--host", default=config.API_HOST)
    srv.add_argument("--port", type=int, default=config.API_PORT)

    subs.add_parser("interactive")
    args = parser.parse_args()

    if args.command == "query":
        from agents.knowledge_agent import KnowledgeAgent
        agent = KnowledgeAgent()
        result = agent.query(args.text)
        if getattr(args, "json", False):
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(agent.format_response(result, voice=getattr(args, "voice", False)))

    elif args.command == "sync":
        from agents.collector_agent import CollectorAgent
        agent = CollectorAgent()
        if args.platform:
            print(json.dumps(agent.sync_single_platform(args.platform, full_sync=args.full),
                             ensure_ascii=False, indent=2))
        else:
            for r in agent.sync_all_platforms(full_sync=args.full):
                print(f"{'✅' if r['success'] else '❌'} {r['platform']}: +{r.get('added',0)}")

    elif args.command == "stats":
        from tools.mcp_tools import get_stats
        s = get_stats()
        print(f"总计：{s.get('total',0)} 条")
        for p in s.get("by_platform", []):
            print(f"  {p['platform']}: {p['count']}")

    elif args.command == "serve":
        import uvicorn
        app = create_app()
        if app:
            print(f"\n🚀 http://{args.host}:{args.port}  文档: http://{args.host}:{args.port}/docs\n")
            uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "interactive":
        from agents.knowledge_agent import KnowledgeAgent
        agent = KnowledgeAgent()
        print("\n🧠 交互模式（输入 quit 退出）\n")
        while True:
            try:
                q = input("你：").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not q or q.lower() in ("quit","exit","退出"):
                break
            print("\n" + agent.format_response(agent.query(q)) + "\n")
    else:
        parser.print_help()


if __name__ == "__main__":
    cli_main()
