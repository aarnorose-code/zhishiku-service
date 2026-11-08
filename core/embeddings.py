"""
嵌入向量生成模块
支持多种嵌入提供商：OpenAI、Gemini、本地哈希回退方案。
"""

import hashlib
import logging
import struct
from abc import ABC, abstractmethod
from typing import Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """嵌入提供商抽象基类。"""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """将文本列表转为嵌入向量列表。"""
        ...

    @abstractmethod
    def dimension(self) -> int:
        """返回嵌入向量维度。"""
        ...


class OpenAIEmbedding(EmbeddingProvider):
    """OpenAI 嵌入 API 提供商（兼容 DeepSeek 等 OpenAI 格式 API）。"""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        api_base: Optional[str] = None,
        dim: int = 1536,
    ):
        self.api_key = api_key
        self.model = model
        self.api_base = (api_base or "https://api.openai.com/v1").rstrip("/")
        self._dim = dim

    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """调用 OpenAI 兼容的嵌入 API。"""
        url = f"{self.api_base}/embeddings"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {"input": texts, "model": self.model}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        # 按 index 排序确保顺序正确
        embeddings_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in embeddings_data]


class GeminiEmbedding(EmbeddingProvider):
    """Google Gemini 嵌入 API 提供商。"""

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-004",
        dim: int = 768,
    ):
        self.api_key = api_key
        self.model = model
        self._dim = dim

    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """调用 Gemini 嵌入 API。"""
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:batchEmbedContents?key={self.api_key}"
        )
        requests_body = [
            {"model": f"models/{self.model}", "content": {"parts": [{"text": t}]}}
            for t in texts
        ]
        payload = {"requests": requests_body}

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        return [item["values"] for item in data["embeddings"]]


class FastEmbedProvider(EmbeddingProvider):
    """
    Qdrant 官方 FastEmbed 本地深度语义嵌入模型 (BAAI/bge-small-zh-v1.5)。
    无需 API Key，纯本地 ONNX 极速推理，高质量中文语义嵌入。
    """

    def __init__(self, model_name: str = "BAAI/bge-small-zh-v1.5", dim: int = 512):
        from fastembed import TextEmbedding
        self._dim = dim
        self._model = TextEmbedding(model_name=model_name)

    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        embeddings = list(self._model.embed(texts))
        return [e.tolist() for e in embeddings]


class LocalHashEmbedding(EmbeddingProvider):
    """
    本地哈希嵌入回退方案。
    使用 SHA-256 哈希 + 滑动窗口 n-gram 生成伪嵌入向量。
    仅作为无 API 时的应急方案，语义搜索质量有限。
    """

    def __init__(self, dim: int = 256):
        self._dim = dim

    def dimension(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """使用哈希方法生成伪嵌入向量。"""
        results = []
        for text in texts:
            vector = self._hash_text(text)
            results.append(vector)
        return results

    def _hash_text(self, text: str) -> list[float]:
        """
        对文本生成固定维度的伪嵌入向量。
        通过对文本的多个 n-gram 进行哈希并聚合来模拟分布式表示。
        """
        dim = self._dim
        vector = [0.0] * dim

        # 对文本进行字符级 n-gram 切分（n=3），每个 n-gram 哈希后累加到对应维度
        text_normalized = text.lower().strip()
        if not text_normalized:
            return vector

        ngram_size = 3
        ngrams = []
        for i in range(max(1, len(text_normalized) - ngram_size + 1)):
            ngrams.append(text_normalized[i : i + ngram_size])

        for ngram in ngrams:
            h = hashlib.sha256(ngram.encode("utf-8")).digest()
            # 从哈希中提取浮点数并累加到向量
            for j in range(min(dim, len(h) // 4)):
                val = struct.unpack("f", h[j * 4 : j * 4 + 4])[0]
                # 归一化到合理范围
                if not (val != val):  # 排除 NaN
                    vector[j] += val

        # L2 归一化
        norm = sum(v * v for v in vector) ** 0.5
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector


def create_embedding_provider() -> EmbeddingProvider:
    """根据配置创建嵌入提供商实例。"""
    provider = settings.embedding_provider.lower()

    if provider == "fastembed" or provider == "local":
        logger.info("使用 FastEmbed 本地深度语义嵌入模型 (BAAI/bge-small-zh-v1.5)")
        return FastEmbedProvider(dim=512)

    elif provider == "openai":
        if not settings.embedding_api_key:
            logger.warning("OpenAI 嵌入 API Key 未配置，自动启用 FastEmbed 本地语义嵌入")
            return FastEmbedProvider(dim=512)
        return OpenAIEmbedding(
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            api_base=settings.embedding_api_base,
            dim=settings.embedding_dim,
        )

    elif provider == "gemini":
        if not settings.embedding_api_key:
            logger.warning("Gemini 嵌入 API Key 未配置，自动启用 FastEmbed 本地语义嵌入")
            return FastEmbedProvider(dim=512)
        return GeminiEmbedding(
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
        )

    else:
        logger.info("默认启用 FastEmbed 本地语义嵌入模型")
        return FastEmbedProvider(dim=512)


# 全局嵌入提供商实例（延迟初始化）
_provider: Optional[EmbeddingProvider] = None


def get_embedding_provider() -> EmbeddingProvider:
    """获取全局嵌入提供商实例。"""
    global _provider
    if _provider is None:
        _provider = create_embedding_provider()
        logger.info(
            f"嵌入提供商初始化完成: {type(_provider).__name__}, 维度={_provider.dimension()}"
        )
    return _provider


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """便捷函数：将文本列表转为嵌入向量。"""
    provider = get_embedding_provider()
    return await provider.embed(texts)


async def embed_text(text: str) -> list[float]:
    """便捷函数：将单个文本转为嵌入向量。"""
    results = await embed_texts([text])
    return results[0]
