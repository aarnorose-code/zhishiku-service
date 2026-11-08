"""
自动修订引擎模块
使用 LLM 智能判断新知识与现有知识的关系，实现智能合并/更新/新增。

修订流程:
1. 接收新内容
2. 嵌入并搜索最相似的 top-3 现有文档
3. 调用 LLM 判断：「补充」、「更正/更新」或「新主题」
4. 根据判断结果，就地更新现有 Markdown 或创建新文件
5. 自动提交到 GitHub
6. 刷新向量索引
"""

import json
import logging
from typing import Any, Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


# ── LLM 调用适配器 ──


async def _call_openai_compatible(
    messages: list[dict],
    model: str,
    api_key: str,
    api_base: str,
    temperature: float = 0.1,
) -> str:
    """调用 OpenAI 兼容 API（支持 OpenAI / DeepSeek 等）。"""
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    return data["choices"][0]["message"]["content"]


async def _call_gemini(
    messages: list[dict],
    model: str,
    api_key: str,
    temperature: float = 0.1,
) -> str:
    """调用 Google Gemini API。"""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent?key={api_key}"
    )
    # 将 OpenAI 格式消息转为 Gemini 格式
    contents = []
    system_instruction = None
    for msg in messages:
        if msg["role"] == "system":
            system_instruction = {"parts": [{"text": msg["content"]}]}
        else:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {"temperature": temperature},
    }
    if system_instruction:
        payload["systemInstruction"] = system_instruction

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    return data["candidates"][0]["content"]["parts"][0]["text"]


async def call_llm(messages: list[dict], temperature: float = 0.1) -> str:
    """根据配置调用对应的 LLM 提供商。"""
    provider = settings.llm_provider.lower()
    api_key = settings.llm_api_key
    model = settings.llm_model

    if not api_key:
        raise RuntimeError("LLM_API_KEY 未配置，无法使用自动修订功能")

    if provider in ("openai", "deepseek"):
        api_base = settings.llm_api_base or "https://api.openai.com/v1"
        return await _call_openai_compatible(messages, model, api_key, api_base, temperature)
    elif provider == "gemini":
        return await _call_gemini(messages, model, api_key, temperature)
    else:
        # 默认尝试 OpenAI 兼容格式
        api_base = settings.llm_api_base or "https://api.openai.com/v1"
        return await _call_openai_compatible(messages, model, api_key, api_base, temperature)


# ── 修订判断逻辑 ──

_REVISION_SYSTEM_PROMPT = """你是一个知识库管理专家。你的任务是分析新提交的知识内容与现有知识库中最相关的文档，
判断应该如何处理这条新知识。

你必须输出严格的 JSON 格式，包含以下字段：
{
    "action": "supplement" | "update" | "new",
    "target_doc_id": "要更新的文档ID（仅 supplement/update 时需要）",
    "reason": "判断理由（简要说明）",
    "merged_title": "合并后或新文档的标题",
    "merged_body": "合并后的完整正文内容（Markdown 格式）",
    "merged_tags": ["标签1", "标签2"],
    "revision_note": "修订说明（简要描述本次变更内容）"
}

三种 action 的判断标准：
- "supplement"：新内容是对某个已有文档的补充或扩展，应该合并到该文档中
- "update"：新内容是对某个已有文档的更正或更新，应该替换/修改该文档中的相关部分
- "new"：新内容是一个全新的主题，应该创建新文档

重要规则：
1. merged_body 必须是完整的、可直接使用的 Markdown 正文（不含 frontmatter）
2. 对于 supplement/update，合并内容时要保持原文档结构的合理性
3. 合并时保留原有内容中仍然正确的部分，只添加/修改必要的内容
4. 如果相似文档的相似度很低或主题明显不同，选择 "new"
5. 输出必须是合法的 JSON，不要包含任何其他内容"""


async def judge_revision(
    new_title: str,
    new_content: str,
    similar_docs: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    调用 LLM 判断新内容与现有知识的关系，返回修订方案。

    参数:
        new_title: 新知识的标题
        new_content: 新知识的正文
        similar_docs: 语义搜索返回的最相似文档列表

    返回:
        修订方案字典，包含 action、target_doc_id、merged_body 等
    """
    # 构建相似文档描述
    similar_descriptions = []
    for i, doc in enumerate(similar_docs):
        similar_descriptions.append(
            f"--- 文档 {i + 1} ---\n"
            f"文档ID: {doc.get('doc_id', 'unknown')}\n"
            f"标题: {doc.get('title', '无标题')}\n"
            f"标签: {doc.get('tags', [])}\n"
            f"相似度: {doc.get('score', 0):.3f}\n"
            f"内容:\n{doc.get('content', '')[:3000]}\n"
        )

    similar_text = "\n\n".join(similar_descriptions) if similar_descriptions else "（无相关文档）"

    user_message = f"""## 新提交的知识

**标题**: {new_title}

**内容**:
{new_content}

## 知识库中最相关的文档

{similar_text}

请分析并输出 JSON 格式的修订方案。"""

    messages = [
        {"role": "system", "content": _REVISION_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    try:
        response_text = await call_llm(messages, temperature=0.1)

        # 清理可能的 markdown 代码块标记
        cleaned = response_text.strip()
        if cleaned.startswith("```"):
            # 移除 ```json 或 ``` 开头
            lines = cleaned.split("\n")
            lines = lines[1:]  # 跳过第一行
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines)

        result = json.loads(cleaned)

        # 验证必要字段
        assert "action" in result, "缺少 action 字段"
        assert result["action"] in ("supplement", "update", "new"), f"无效的 action: {result['action']}"
        assert "merged_body" in result, "缺少 merged_body 字段"
        assert "merged_title" in result, "缺少 merged_title 字段"

        logger.info(
            f"修订判断完成: action={result['action']}, "
            f"target={result.get('target_doc_id', 'N/A')}, "
            f"reason={result.get('reason', '')}"
        )
        return result

    except json.JSONDecodeError as e:
        logger.error(f"LLM 返回的 JSON 解析失败: {e}\n原始响应: {response_text[:500]}")
        # 回退：作为新文档处理
        return {
            "action": "new",
            "target_doc_id": None,
            "reason": f"LLM 响应解析失败，默认创建新文档: {e}",
            "merged_title": new_title,
            "merged_body": new_content,
            "merged_tags": [],
            "revision_note": "自动创建（LLM 解析失败回退）",
        }
    except Exception as e:
        logger.error(f"修订判断失败: {e}")
        return {
            "action": "new",
            "target_doc_id": None,
            "reason": f"修订判断出错，默认创建新文档: {e}",
            "merged_title": new_title,
            "merged_body": new_content,
            "merged_tags": [],
            "revision_note": "自动创建（修订判断出错回退）",
        }
