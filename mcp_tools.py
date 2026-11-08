"""
MCP 工具定义模块
使用 mcp SDK 定义知识库操作工具，通过 SSE 传输协议提供远程访问。

提供的工具:
- search_knowledge: 语义搜索知识库
- read_document: 读取指定文档
- upsert_knowledge: 新增或更新知识（带自动修订引擎）
- list_documents: 列出所有文档
"""

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from core.auth import verify_token_raw
from core.knowledge import (
    list_documents,
    read_document,
    search_knowledge,
    upsert_knowledge,
)

logger = logging.getLogger(__name__)

# 创建 MCP 服务器实例
mcp_server = Server("zhishiku")


# ── 工具定义 ──


@mcp_server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """返回所有可用的 MCP 工具。"""
    return [
        Tool(
            name="search_knowledge",
            description=(
                "在知识库中进行语义搜索。根据查询文本找到最相关的知识文档。"
                "支持通过标签过滤结果。返回匹配文档的标题、摘要和相似度分数。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索查询文本，描述你想要找的知识内容",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "返回结果数量，默认 5",
                        "default": 5,
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可选的标签过滤，只返回包含指定标签的文档",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="read_document",
            description=(
                "读取知识库中指定文档的完整内容。"
                "需要提供文档ID（通常是文件路径，可从搜索结果中获取）。"
                "返回文档的完整正文、元数据和标签。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "doc_id": {
                        "type": "string",
                        "description": "文档ID（文件路径），可从 search_knowledge 或 list_documents 结果中获取",
                    },
                },
                "required": ["doc_id"],
            },
        ),
        Tool(
            name="upsert_knowledge",
            description=(
                "向知识库新增或更新一条知识。系统会自动分析新内容与现有知识的关系："
                "如果是对已有知识的补充或更新，会智能合并到已有文档中；"
                "如果是全新的主题，则创建新文档。所有变更会自动提交到 GitHub 并更新索引。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "知识标题",
                    },
                    "content": {
                        "type": "string",
                        "description": "知识正文内容（Markdown 格式）",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "知识标签，用于分类和过滤",
                    },
                    "auto_revision": {
                        "type": "boolean",
                        "description": "是否启用自动修订引擎（默认 true），会智能判断合并或新建",
                        "default": True,
                    },
                    "force_new": {
                        "type": "boolean",
                        "description": "是否强制创建新文档（默认 false），跳过修订引擎",
                        "default": False,
                    },
                },
                "required": ["title", "content"],
            },
        ),
        Tool(
            name="list_documents",
            description="列出知识库中的所有文档。返回每个文档的ID、标题、标签和时间信息。",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@mcp_server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """处理 MCP 工具调用。"""
    logger.info(f"MCP 工具调用: {name}, 参数: {json.dumps(arguments, ensure_ascii=False)[:200]}")

    try:
        if name == "search_knowledge":
            results = await search_knowledge(
                query=arguments["query"],
                top_k=arguments.get("top_k", 5),
                tags=arguments.get("tags"),
            )
            return [TextContent(
                type="text",
                text=json.dumps(results, ensure_ascii=False, indent=2),
            )]

        elif name == "read_document":
            doc = await read_document(doc_id=arguments["doc_id"])
            if doc is None:
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": "文档不存在", "doc_id": arguments["doc_id"]}, ensure_ascii=False),
                )]
            return [TextContent(
                type="text",
                text=json.dumps(doc, ensure_ascii=False, indent=2),
            )]

        elif name == "upsert_knowledge":
            result = await upsert_knowledge(
                title=arguments["title"],
                content=arguments["content"],
                tags=arguments.get("tags"),
                auto_revision=arguments.get("auto_revision", True),
                force_new=arguments.get("force_new", False),
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2),
            )]

        elif name == "list_documents":
            docs = await list_documents()
            return [TextContent(
                type="text",
                text=json.dumps(docs, ensure_ascii=False, indent=2),
            )]

        else:
            return [TextContent(
                type="text",
                text=json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False),
            )]

    except Exception as e:
        logger.exception(f"MCP 工具执行出错: {name}")
        return [TextContent(
            type="text",
            text=json.dumps({"error": str(e)}, ensure_ascii=False),
        )]
