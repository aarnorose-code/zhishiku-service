"""
Qdrant 向量数据库操作模块
负责集合管理、向量写入和语义搜索。
"""

import logging
from typing import Any, Optional

from qdrant_client import AsyncQdrantClient, models

from core.config import settings
from core.embeddings import embed_text, embed_texts, get_embedding_provider

logger = logging.getLogger(__name__)

# 全局 Qdrant 客户端（延迟初始化）
_client: Optional[AsyncQdrantClient] = None


async def get_client() -> AsyncQdrantClient:
    """获取或创建 Qdrant 异步客户端。"""
    global _client
    if _client is None:
        _client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30.0,
            prefer_grpc=False,
        )
        logger.info(f"Qdrant 客户端已连接: {settings.qdrant_url}")
    return _client


async def ensure_collection() -> None:
    """确保向量集合存在，不存在则创建。"""
    client = await get_client()
    collection_name = settings.qdrant_collection
    dim = get_embedding_provider().dimension()

    try:
        collections = await client.get_collections()
        existing = [c.name for c in collections.collections]

        if collection_name in existing:
            info = await client.get_collection(collection_name)
            current_size = getattr(info.config.params.vectors, "size", None)
            if current_size and current_size != dim:
                logger.warning(f"集合维度不匹配 (当前={current_size}, 期望={dim})，自动重新对齐集合...")
                await client.delete_collection(collection_name)
                existing.remove(collection_name)

        if collection_name not in existing:
            await client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=dim,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(f"已创建 Qdrant 集合: {collection_name} (维度={dim})")
        else:
            logger.info(f"Qdrant 集合已存在: {collection_name} (维度={dim})")
    except Exception as e:
        logger.error(f"初始化 Qdrant 集合失败: {e}")
        raise


async def upsert_document(
    doc_id: str,
    content: str,
    metadata: dict[str, Any],
) -> None:
    """
    将文档写入向量数据库。
    doc_id: 文档唯一标识（通常是文件路径）
    content: 文档全文内容
    metadata: 附加元数据（标题、标签等）
    """
    client = await get_client()

    # 生成嵌入向量
    vector = await embed_text(content)

    # 使用确定性 ID（基于文档路径哈希）
    import hashlib
    point_id = hashlib.md5(doc_id.encode()).hexdigest()
    # Qdrant 需要 UUID 格式或整数 ID，这里用 UUID 格式
    point_uuid = f"{point_id[:8]}-{point_id[8:12]}-{point_id[12:16]}-{point_id[16:20]}-{point_id[20:32]}"

    # 构建 payload
    payload = {
        "doc_id": doc_id,
        "content": content,
        **metadata,
    }

    await client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            models.PointStruct(
                id=point_uuid,
                vector=vector,
                payload=payload,
            )
        ],
    )
    logger.info(f"文档已写入向量库: {doc_id}")


async def search_similar(
    query: str,
    top_k: int = 5,
    score_threshold: Optional[float] = None,
    filter_conditions: Optional[dict] = None,
) -> list[dict[str, Any]]:
    """
    语义搜索：根据查询文本查找最相似的文档。
    返回包含文档信息和相似度分数的列表。
    """
    client = await get_client()

    # 如果未提供 API Key（回退到本地哈希），不设过滤阈值；否则默认阈值 0.3
    if score_threshold is None:
        score_threshold = 0.3 if (settings.embedding_api_key and settings.embedding_provider != "local") else 0.0

    # 生成查询向量
    query_vector = await embed_text(query)

    # 构建过滤条件
    qdrant_filter = None
    if filter_conditions:
        must_conditions = []
        for key, value in filter_conditions.items():
            if isinstance(value, list):
                must_conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchAny(any=value),
                    )
                )
            else:
                must_conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    )
                )
        qdrant_filter = models.Filter(must=must_conditions)

    results = await client.query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        limit=top_k,
        score_threshold=score_threshold,
        query_filter=qdrant_filter,
        with_payload=True,
    )

    documents = []
    for point in results.points:
        doc = {
            "id": point.id,
            "score": point.score,
            **(point.payload or {}),
        }
        documents.append(doc)

    logger.info(f"语义搜索完成: query='{query[:50]}...', 找到 {len(documents)} 条结果")
    return documents


async def delete_document(doc_id: str) -> None:
    """从向量数据库中删除指定文档。"""
    client = await get_client()
    import hashlib
    point_id = hashlib.md5(doc_id.encode()).hexdigest()
    point_uuid = f"{point_id[:8]}-{point_id[8:12]}-{point_id[12:16]}-{point_id[16:20]}-{point_id[20:32]}"

    await client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.PointIdsList(points=[point_uuid]),
    )
    logger.info(f"文档已从向量库删除: {doc_id}")


async def list_all_documents() -> list[dict[str, Any]]:
    """列出向量数据库中的所有文档元数据。"""
    client = await get_client()

    documents = []
    offset = None

    while True:
        result = await client.scroll(
            collection_name=settings.qdrant_collection,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points, next_offset = result

        for point in points:
            payload = point.payload or {}
            doc = {
                "id": point.id,
                "doc_id": payload.get("doc_id", ""),
                "title": payload.get("title", ""),
                "tags": payload.get("tags", []),
                "updated_at": payload.get("updated_at", ""),
            }
            documents.append(doc)

        if next_offset is None:
            break
        offset = next_offset

    return documents


async def close_client() -> None:
    """关闭 Qdrant 客户端连接。"""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
        logger.info("Qdrant 客户端已关闭")
