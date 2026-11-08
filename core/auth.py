"""
认证中间件模块
使用 Bearer Token 认证方式保护 API 端点。
"""

import logging
from typing import Optional

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import settings

logger = logging.getLogger(__name__)

# Bearer Token 安全方案
_bearer_scheme = HTTPBearer(auto_error=False)


async def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(_bearer_scheme),
) -> str:
    """
    验证 Bearer Token。
    如果 AUTH_TOKEN 未配置，则跳过认证（开发模式）。
    """
    # 如果未配置认证令牌，跳过验证（开发模式警告）
    if not settings.auth_token:
        logger.warning("AUTH_TOKEN 未配置，跳过认证验证（仅限开发环境使用）")
        return "anonymous"

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少认证令牌，请在请求头中添加 Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.credentials != settings.auth_token:
        logger.warning("认证失败：无效的令牌")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无效的认证令牌",
        )

    return credentials.credentials


def verify_token_raw(token: str) -> bool:
    """
    直接验证令牌字符串（供 MCP 等非 FastAPI 上下文使用）。
    """
    if not settings.auth_token:
        return True
    return token == settings.auth_token
