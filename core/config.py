"""
配置管理模块
所有配置项均通过环境变量读取，支持 .env 文件自动加载。
"""

import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

# 加载 .env 文件（如果存在）
load_dotenv()


@dataclass
class Settings:
    """全局配置，所有敏感信息均从环境变量获取。"""

    # ── GitHub 同步配置 ──
    github_token: str = field(default_factory=lambda: os.getenv("GITHUB_TOKEN", ""))
    github_repo: str = field(default_factory=lambda: os.getenv("GITHUB_REPO", ""))  # 格式: owner/repo
    github_branch: str = field(default_factory=lambda: os.getenv("GITHUB_BRANCH", "main"))
    github_docs_path: str = field(default_factory=lambda: os.getenv("GITHUB_DOCS_PATH", "docs"))  # 仓库中知识文件目录

    # ── Qdrant 向量数据库配置 ──
    qdrant_url: str = field(default_factory=lambda: os.getenv("QDRANT_URL", "http://localhost:6333"))
    qdrant_api_key: Optional[str] = field(default_factory=lambda: os.getenv("QDRANT_API_KEY"))
    qdrant_collection: str = field(default_factory=lambda: os.getenv("QDRANT_COLLECTION", "zhishiku"))

    # ── Embedding 配置 ──
    embedding_provider: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_PROVIDER", "openai")
    )  # openai / gemini / local
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
    )
    embedding_dim: int = field(default_factory=lambda: int(os.getenv("EMBEDDING_DIM", "1536")))
    embedding_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("EMBEDDING_API_KEY") or os.getenv("OPENAI_API_KEY")
    )
    embedding_api_base: Optional[str] = field(
        default_factory=lambda: os.getenv("EMBEDDING_API_BASE")
    )

    # ── LLM 配置（用于自动修订引擎）──
    llm_provider: str = field(
        default_factory=lambda: os.getenv("LLM_PROVIDER", "openai")
    )  # openai / gemini / deepseek
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "gpt-4o-mini"))
    llm_api_key: Optional[str] = field(
        default_factory=lambda: os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    )
    llm_api_base: Optional[str] = field(default_factory=lambda: os.getenv("LLM_API_BASE"))

    # ── 认证配置 ──
    auth_token: str = field(default_factory=lambda: os.getenv("AUTH_TOKEN", ""))

    # ── 服务配置 ──
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8000")))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    def validate(self) -> list[str]:
        """验证必要配置项，返回缺失项列表。"""
        warnings: list[str] = []
        if not self.github_token:
            warnings.append("GITHUB_TOKEN 未设置，GitHub 同步功能将不可用")
        if not self.github_repo:
            warnings.append("GITHUB_REPO 未设置，GitHub 同步功能将不可用")
        if not self.qdrant_url:
            warnings.append("QDRANT_URL 未设置，向量搜索功能将不可用")
        if not self.auth_token:
            warnings.append("AUTH_TOKEN 未设置，API 将无认证保护！")
        if self.embedding_provider != "local" and not self.embedding_api_key:
            warnings.append("EMBEDDING_API_KEY 未设置，将回退到本地嵌入模式")
        return warnings


# 全局单例
settings = Settings()
