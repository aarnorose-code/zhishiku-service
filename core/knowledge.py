"""
知识库高级操作模块
整合向量搜索、GitHub 同步和自动修订引擎，提供统一的知识操作接口。
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from core import github_sync, vector_store
from core.revisor import judge_revision

logger = logging.getLogger(__name__)


def _sanitize_filename(title: str) -> str:
    """将标题转为安全的文件名。"""
    # 保留中文、字母、数字，其余替换为连字符
    name = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title)
    name = name.strip("-").lower()
    if not name:
        name = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{name}.md"


async def search_knowledge(
    query: str,
    top_k: int = 5,
    tags: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """
    搜索知识库。结合语义搜索返回最相关的文档。

    参数:
        query: 搜索查询文本
        top_k: 返回结果数量
        tags: 可选的标签过滤

    返回:
        匹配的文档列表，包含相似度分数
    """
    # 构建过滤条件
    filters = {}
    if tags:
        filters["tags"] = tags

    results = await vector_store.search_similar(
        query=query,
        top_k=top_k,
        filter_conditions=filters if filters else None,
    )

    # 精简返回内容（不返回完整嵌入向量）
    cleaned = []
    for doc in results:
        cleaned.append({
            "doc_id": doc.get("doc_id", ""),
            "title": doc.get("title", ""),
            "tags": doc.get("tags", []),
            "score": doc.get("score", 0),
            "content": doc.get("content", "")[:2000],  # 截断过长内容
            "updated_at": doc.get("updated_at", ""),
        })

    return cleaned


async def read_document(doc_id: str) -> Optional[dict[str, Any]]:
    """
    读取指定文档的完整内容。

    参数:
        doc_id: 文档ID（通常是文件路径）

    返回:
        文档的完整信息，包括元数据和正文
    """
    try:
        doc = github_sync.read_file(doc_id)
        if doc:
            return {
                "doc_id": doc["path"],
                "title": doc["metadata"].get("title", ""),
                "tags": doc["metadata"].get("tags", []),
                "body": doc["body"],
                "metadata": doc["metadata"],
                "sha": doc["sha"],
            }
        return None
    except Exception as e:
        logger.error(f"读取文档失败: {doc_id}, 错误: {e}")
        return None


async def list_documents() -> list[dict[str, Any]]:
    """
    列出知识库中的所有文档。
    优先从 GitHub 获取（包含实时信息），回退到向量库。
    """
    try:
        files = github_sync.list_files()
        documents = []
        for f in files:
            doc = github_sync.read_file(f["path"])
            if doc:
                documents.append({
                    "doc_id": doc["path"],
                    "title": doc["metadata"].get("title", doc["path"]),
                    "tags": doc["metadata"].get("tags", []),
                    "created_at": doc["metadata"].get("created_at", ""),
                    "updated_at": doc["metadata"].get("updated_at", ""),
                })
        return documents
    except Exception as e:
        logger.warning(f"从 GitHub 列出文档失败: {e}，回退到向量库")
        try:
            return await vector_store.list_all_documents()
        except Exception as e2:
            logger.error(f"从向量库列出文档也失败: {e2}")
            return []


async def upsert_knowledge(
    title: str,
    content: str,
    tags: Optional[list[str]] = None,
    auto_revision: bool = True,
    force_new: bool = False,
) -> dict[str, Any]:
    """
    新增或更新知识。核心操作流程：

    1. 如果启用自动修订，先搜索相似文档
    2. 调用 LLM 判断应该如何处理（补充/更新/新建）
    3. 执行对应的操作（合并到现有文档 或 创建新文档）
    4. 同步到 GitHub
    5. 更新向量索引

    参数:
        title: 知识标题
        content: 知识正文
        tags: 标签列表
        auto_revision: 是否启用自动修订引擎
        force_new: 是否强制创建新文档（跳过修订引擎）

    返回:
        操作结果信息
    """
    tags = tags or []

    # ── 步骤 1: 自动修订判断 ──
    if auto_revision and not force_new:
        try:
            # 搜索最相似的 top-3 文档
            similar_docs = await vector_store.search_similar(
                query=f"{title}\n{content}",
                top_k=3,
                score_threshold=0.4,
            )

            if similar_docs:
                # 调用 LLM 修订引擎
                revision = await judge_revision(title, content, similar_docs)
                action = revision["action"]
                merged_title = revision.get("merged_title", title)
                merged_body = revision.get("merged_body", content)
                merged_tags = revision.get("merged_tags", tags) or tags
                revision_note = revision.get("revision_note", "")

                if action in ("supplement", "update") and revision.get("target_doc_id"):
                    # 更新现有文档
                    target_id = revision["target_doc_id"]
                    existing = github_sync.read_file(target_id)

                    if existing:
                        result = github_sync.save_document(
                            filename=target_id.split("/")[-1],
                            title=merged_title,
                            body=merged_body,
                            tags=merged_tags,
                            existing_metadata=existing["metadata"],
                            sha=existing["sha"],
                            revision_note=revision_note,
                        )

                        # 更新向量索引
                        await vector_store.upsert_document(
                            doc_id=target_id,
                            content=merged_body,
                            metadata={
                                "title": merged_title,
                                "tags": merged_tags,
                                "updated_at": datetime.now(timezone.utc).strftime(
                                    "%Y-%m-%dT%H:%M:%SZ"
                                ),
                            },
                        )

                        return {
                            "status": "updated",
                            "action": action,
                            "doc_id": target_id,
                            "title": merged_title,
                            "reason": revision.get("reason", ""),
                            "revision_note": revision_note,
                            "commit_sha": result.get("commit_sha", ""),
                        }
                    else:
                        logger.warning(
                            f"修订目标文档不存在: {target_id}，将创建新文档"
                        )
                        # 下面会走新建流程

                # action == "new" 或回退到新建
                title = merged_title
                content = merged_body
                tags = merged_tags
            else:
                logger.info("无相似文档，将创建新文档")

        except Exception as e:
            logger.error(f"自动修订引擎出错: {e}，回退到直接创建新文档")

    # ── 步骤 2: 创建新文档 ──
    filename = _sanitize_filename(title)

    result = github_sync.save_document(
        filename=filename,
        title=title,
        body=content,
        tags=tags,
        revision_note="初始创建",
    )

    doc_id = result["path"]

    # 更新向量索引
    await vector_store.upsert_document(
        doc_id=doc_id,
        content=content,
        metadata={
            "title": title,
            "tags": tags,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )

    return {
        "status": "created",
        "action": "new",
        "doc_id": doc_id,
        "title": title,
        "commit_sha": result.get("commit_sha", ""),
    }


async def sync_from_github() -> dict[str, Any]:
    """
    从 GitHub 同步所有文档到向量数据库。
    用于初始化或手动触发全量同步。
    """
    try:
        documents = github_sync.read_all_documents()
        synced = 0
        errors = 0

        for doc in documents:
            try:
                metadata = doc["metadata"]
                await vector_store.upsert_document(
                    doc_id=doc["path"],
                    content=doc["body"],
                    metadata={
                        "title": metadata.get("title", ""),
                        "tags": metadata.get("tags", []),
                        "created_at": metadata.get("created_at", ""),
                        "updated_at": metadata.get("updated_at", ""),
                    },
                )
                synced += 1
            except Exception as e:
                logger.error(f"同步文档失败: {doc['path']}, 错误: {e}")
                errors += 1

        result = {
            "status": "completed",
            "total": len(documents),
            "synced": synced,
            "errors": errors,
        }
        logger.info(f"GitHub 同步完成: {result}")
        return result

    except Exception as e:
        logger.error(f"GitHub 同步失败: {e}")
        return {
            "status": "failed",
            "error": str(e),
        }
