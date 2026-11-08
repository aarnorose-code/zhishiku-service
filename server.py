"""
知识库服务主入口
整合 FastAPI REST API 和 MCP SSE 服务器，在同一端口上提供双协议访问。

启动方式:
    python server.py
    或
    uvicorn server:app --host 0.0.0.0 --port 8000
"""

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.routing import Mount

from mcp.server.sse import SseServerTransport

from api_routes import router as api_router
from core.config import settings
from core.vector_store import close_client, ensure_collection
from mcp_tools import mcp_server

# ── 日志配置 ──

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("zhishiku")


# ── 生命周期管理 ──


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化资源，关闭时清理。"""
    # 启动阶段
    logger.info("=" * 60)
    logger.info("  知识库服务 (ZhiShiKu) 正在启动...")
    logger.info("=" * 60)

    # 验证配置
    warnings = settings.validate()
    for w in warnings:
        logger.warning(f"  ⚠ {w}")

    # 初始化 Qdrant 集合
    try:
        await ensure_collection()
        logger.info("  ✓ Qdrant 向量数据库已连接")
    except Exception as e:
        logger.error(f"  ✗ Qdrant 初始化失败: {e}")
        logger.error("    向量搜索功能将不可用，请检查 QDRANT_URL 配置")

    logger.info(f"  ✓ 嵌入提供商: {settings.embedding_provider}")
    logger.info(f"  ✓ LLM 提供商: {settings.llm_provider} ({settings.llm_model})")
    logger.info(f"  ✓ GitHub 仓库: {settings.github_repo or '未配置'}")
    logger.info(f"  ✓ 认证保护: {'已启用' if settings.auth_token else '未启用（开发模式）'}")
    logger.info("")
    logger.info(f"  REST API:  http://{settings.host}:{settings.port}/api/docs")
    logger.info(f"  MCP SSE:   http://{settings.host}:{settings.port}/mcp/sse")
    logger.info(f"  健康检查:  http://{settings.host}:{settings.port}/api/health")
    logger.info("=" * 60)

    yield

    # 关闭阶段
    logger.info("知识库服务正在关闭...")
    await close_client()
    logger.info("知识库服务已关闭")


# ── FastAPI 应用 ──

app = FastAPI(
    title="知识库 (ZhiShiKu)",
    description=(
        "智能知识库服务，支持语义搜索、自动修订和 GitHub 同步。\n\n"
        "## 功能特点\n"
        "- 🔍 **语义搜索**: 基于向量相似度的智能搜索\n"
        "- 🤖 **自动修订**: LLM 驱动的知识合并与更新\n"
        "- 📁 **GitHub 同步**: 知识文件自动同步到 GitHub 仓库\n"
        "- 🔐 **认证保护**: Bearer Token 认证\n"
        "- 🔌 **双协议**: 同时支持 REST API 和 MCP SSE"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS 中间件（允许跨域访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 REST API 路由
app.include_router(api_router)


# ── MCP SSE 端点挂载 ──

# 创建 SSE 传输层
sse_transport = SseServerTransport("/mcp/messages/")


@app.get("/mcp/sse")
async def handle_sse(request: Request):
    """MCP SSE 连接端点。客户端通过此端点建立 SSE 连接。"""
    # 可选：验证认证令牌
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        from core.auth import verify_token_raw
        if not verify_token_raw(token):
            return JSONResponse(
                status_code=403,
                content={"error": "无效的认证令牌"},
            )

    async with sse_transport.connect_sse(
        request.scope, request.receive, request._send  # type: ignore
    ) as streams:
        await mcp_server.run(
            streams[0],
            streams[1],
            mcp_server.create_initialization_options(),
        )


# 挂载 MCP 消息处理端点
app.mount("/mcp/messages/", app=sse_transport.handle_post_message)


# ── 全局异常处理 ──


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器。"""
    logger.exception(f"未捕获的异常: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "服务器内部错误", "detail": str(exc)},
    )


# ── 根路径 ──


@app.get("/", tags=["系统"])
async def root():
    """服务根路径，返回基本信息。"""
    return {
        "service": "知识库 (ZhiShiKu)",
        "version": "1.0.0",
        "endpoints": {
            "rest_api": "/api/docs",
            "mcp_sse": "/mcp/sse",
            "health": "/api/health",
            "openapi": "/api/openapi.json",
        },
    }


# ── 直接启动 ──

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=False,
    )
