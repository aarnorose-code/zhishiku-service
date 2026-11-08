"""
REST API 路由模块
提供知识库的 HTTP REST API，自动生成 OpenAPI 文档。
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from core.auth import verify_token
from core.knowledge import (
    list_documents,
    read_document,
    search_knowledge,
    sync_from_github,
    upsert_knowledge,
)

logger = logging.getLogger(__name__)

# 创建 API 路由器
router = APIRouter(prefix="/api", tags=["知识库"])


# ── 请求/响应模型 ──


class SearchRequest(BaseModel):
    """搜索请求"""

    query: str = Field(..., description="搜索查询文本", min_length=1)
    top_k: int = Field(5, description="返回结果数量", ge=1, le=50)
    tags: Optional[list[str]] = Field(None, description="标签过滤")


class SearchResult(BaseModel):
    """搜索结果项"""

    doc_id: str = Field(..., description="文档ID")
    title: str = Field("", description="文档标题")
    tags: list[str] = Field(default_factory=list, description="标签")
    score: float = Field(0, description="相似度分数")
    content: str = Field("", description="内容摘要")
    updated_at: str = Field("", description="更新时间")


class SearchResponse(BaseModel):
    """搜索响应"""

    results: list[SearchResult] = Field(default_factory=list)
    total: int = Field(0, description="结果总数")


class ReadResponse(BaseModel):
    """文档读取响应"""

    doc_id: str = Field(..., description="文档ID")
    title: str = Field("", description="文档标题")
    tags: list[str] = Field(default_factory=list, description="标签")
    body: str = Field("", description="文档正文")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


class UpsertRequest(BaseModel):
    """知识写入请求"""

    title: str = Field(..., description="知识标题", min_length=1)
    content: str = Field(..., description="知识正文（Markdown 格式）", min_length=1)
    tags: Optional[list[str]] = Field(None, description="标签列表")
    auto_revision: bool = Field(True, description="是否启用自动修订引擎")
    force_new: bool = Field(False, description="是否强制创建新文档")


class UpsertResponse(BaseModel):
    """知识写入响应"""

    status: str = Field(..., description="操作状态: created/updated")
    action: str = Field(..., description="执行的动作: new/supplement/update")
    doc_id: str = Field(..., description="文档ID")
    title: str = Field("", description="文档标题")
    reason: str = Field("", description="修订理由")
    revision_note: str = Field("", description="修订说明")
    commit_sha: str = Field("", description="Git commit SHA")


class DocumentSummary(BaseModel):
    """文档摘要"""

    doc_id: str = Field(..., description="文档ID")
    title: str = Field("", description="文档标题")
    tags: list[str] = Field(default_factory=list, description="标签")
    created_at: str = Field("", description="创建时间")
    updated_at: str = Field("", description="更新时间")


class ListResponse(BaseModel):
    """文档列表响应"""

    documents: list[DocumentSummary] = Field(default_factory=list)
    total: int = Field(0, description="文档总数")


class SyncResponse(BaseModel):
    """同步响应"""

    status: str = Field(..., description="同步状态")
    total: int = Field(0, description="文档总数")
    synced: int = Field(0, description="成功同步数")
    errors: int = Field(0, description="同步失败数")
    error: str = Field("", description="错误信息")


class HealthResponse(BaseModel):
    """健康检查响应"""

    status: str = "ok"
    service: str = "zhishiku"
    version: str = "1.0.0"


# ── API 端点 ──


@router.post(
    "/search",
    response_model=SearchResponse,
    summary="搜索知识库",
    description="根据查询文本在知识库中进行语义搜索，返回最相关的文档列表。",
)
async def api_search(
    request: SearchRequest,
    _token: str = Depends(verify_token),
) -> SearchResponse:
    """搜索知识库。"""
    results = await search_knowledge(
        query=request.query,
        top_k=request.top_k,
        tags=request.tags,
    )
    return SearchResponse(
        results=[SearchResult(**r) for r in results],
        total=len(results),
    )


@router.get(
    "/read/{doc_id:path}",
    response_model=ReadResponse,
    summary="读取文档",
    description="读取指定文档的完整内容，包括正文和元数据。",
)
async def api_read(
    doc_id: str,
    _token: str = Depends(verify_token),
) -> ReadResponse:
    """读取指定文档。"""
    doc = await read_document(doc_id)
    if doc is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"文档不存在: {doc_id}")
    return ReadResponse(**doc)


@router.post(
    "/upsert",
    response_model=UpsertResponse,
    summary="新增或更新知识",
    description=(
        "向知识库提交一条知识。系统会使用自动修订引擎分析新内容与现有知识的关系，"
        "智能判断是补充已有文档、更新已有文档还是创建新文档。"
    ),
)
async def api_upsert(
    request: UpsertRequest,
    _token: str = Depends(verify_token),
) -> UpsertResponse:
    """新增或更新知识。"""
    result = await upsert_knowledge(
        title=request.title,
        content=request.content,
        tags=request.tags,
        auto_revision=request.auto_revision,
        force_new=request.force_new,
    )
    return UpsertResponse(**result)


@router.get(
    "/documents",
    response_model=ListResponse,
    summary="列出所有文档",
    description="获取知识库中所有文档的列表，包含基本元数据。",
)
async def api_list_documents(
    _token: str = Depends(verify_token),
) -> ListResponse:
    """列出所有文档。"""
    docs = await list_documents()
    return ListResponse(
        documents=[DocumentSummary(**d) for d in docs],
        total=len(docs),
    )


@router.post(
    "/sync",
    response_model=SyncResponse,
    summary="同步 GitHub 知识库",
    description="从 GitHub 仓库同步所有知识文档到向量数据库。用于初始化或手动触发全量同步。",
)
async def api_sync(
    _token: str = Depends(verify_token),
) -> SyncResponse:
    """触发 GitHub 到向量库的全量同步。"""
    result = await sync_from_github()
    return SyncResponse(**result)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    description="检查服务运行状态。",
)
async def api_health() -> HealthResponse:
    """健康检查端点（无需认证）。"""
    return HealthResponse()
