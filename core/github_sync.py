"""
GitHub 同步模块
通过 PyGithub 实现与 GitHub 私有仓库的读写和自动提交。
所有知识文件以 Markdown 格式存储，包含 YAML frontmatter 元数据。
"""

import base64
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import yaml
from github import Auth, Github, GithubException

from core.config import settings

logger = logging.getLogger(__name__)

# 全局 GitHub 客户端（延迟初始化）
_github: Optional[Github] = None


def _get_github() -> Github:
    """获取 GitHub 客户端实例。"""
    global _github
    if _github is None:
        if not settings.github_token:
            raise RuntimeError("GITHUB_TOKEN 未配置，无法使用 GitHub 同步功能")
        auth = Auth.Token(settings.github_token)
        _github = Github(auth=auth)
        logger.info("GitHub 客户端已初始化")
    return _github


def _get_repo():
    """获取目标仓库对象。"""
    gh = _get_github()
    if not settings.github_repo:
        raise RuntimeError("GITHUB_REPO 未配置")
    return gh.get_repo(settings.github_repo)


def _build_file_path(filename: str) -> str:
    """构建仓库内的完整文件路径。"""
    docs_path = settings.github_docs_path.strip("/")
    filename = filename.strip("/")
    if docs_path:
        return f"{docs_path}/{filename}"
    return filename


def parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """
    解析 Markdown 文件的 YAML frontmatter 和正文。
    返回 (metadata_dict, body_text)。
    """
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            try:
                metadata = yaml.safe_load(parts[1]) or {}
                body = parts[2].strip()
                return metadata, body
            except yaml.YAMLError:
                pass
    return {}, content


def build_frontmatter(metadata: dict[str, Any], body: str) -> str:
    """将 metadata 和正文组合为带 YAML frontmatter 的 Markdown。"""
    yaml_str = yaml.dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).strip()
    return f"---\n{yaml_str}\n---\n\n{body}"


def list_files() -> list[dict[str, str]]:
    """列出仓库中知识文件目录下的所有 Markdown 文件。"""
    try:
        repo = _get_repo()
        docs_path = settings.github_docs_path.strip("/")
        contents = repo.get_contents(docs_path, ref=settings.github_branch)

        files = []
        # 递归遍历目录
        while contents:
            file_content = contents.pop(0)
            if file_content.type == "dir":
                sub_contents = repo.get_contents(
                    file_content.path, ref=settings.github_branch
                )
                if isinstance(sub_contents, list):
                    contents.extend(sub_contents)
                else:
                    contents.append(sub_contents)
            elif file_content.name.endswith(".md"):
                files.append(
                    {
                        "path": file_content.path,
                        "name": file_content.name,
                        "sha": file_content.sha,
                        "size": file_content.size,
                    }
                )

        if not isinstance(contents, list):
            contents = [contents]

        logger.info(f"从 GitHub 列出 {len(files)} 个 Markdown 文件")
        return files
    except GithubException as e:
        if e.status == 404:
            logger.warning(f"GitHub 目录不存在: {settings.github_docs_path}")
            return []
        raise


def read_file(filepath: str) -> Optional[dict[str, Any]]:
    """
    从 GitHub 读取指定文件，解析 frontmatter 返回结构化数据。
    返回 {"path", "metadata", "body", "raw", "sha"}。
    """
    try:
        repo = _get_repo()
        file_content = repo.get_contents(filepath, ref=settings.github_branch)

        if isinstance(file_content, list):
            logger.error(f"路径是目录而非文件: {filepath}")
            return None

        # 解码文件内容
        raw_content = base64.b64decode(file_content.content).decode("utf-8")
        metadata, body = parse_frontmatter(raw_content)

        return {
            "path": filepath,
            "metadata": metadata,
            "body": body,
            "raw": raw_content,
            "sha": file_content.sha,
        }
    except GithubException as e:
        if e.status == 404:
            logger.info(f"文件不存在: {filepath}")
            return None
        raise


def write_file(
    filepath: str,
    content: str,
    commit_message: str,
    sha: Optional[str] = None,
) -> dict[str, str]:
    """
    写入或更新 GitHub 文件。
    如果提供 sha 则更新已有文件，否则创建新文件。
    返回 {"path", "sha", "commit_sha"}。
    """
    repo = _get_repo()

    try:
        if sha:
            # 更新已有文件
            result = repo.update_file(
                path=filepath,
                message=commit_message,
                content=content,
                sha=sha,
                branch=settings.github_branch,
            )
            logger.info(f"文件已更新: {filepath}")
        else:
            # 尝试获取现有文件的 sha
            try:
                existing = repo.get_contents(filepath, ref=settings.github_branch)
                if not isinstance(existing, list):
                    result = repo.update_file(
                        path=filepath,
                        message=commit_message,
                        content=content,
                        sha=existing.sha,
                        branch=settings.github_branch,
                    )
                    logger.info(f"文件已更新（自动获取sha）: {filepath}")
                else:
                    raise ValueError(f"路径是目录: {filepath}")
            except GithubException as e:
                if e.status == 404:
                    # 创建新文件
                    result = repo.create_file(
                        path=filepath,
                        message=commit_message,
                        content=content,
                        branch=settings.github_branch,
                    )
                    logger.info(f"新文件已创建: {filepath}")
                else:
                    raise

        return {
            "path": filepath,
            "sha": result["content"].sha,
            "commit_sha": result["commit"].sha,
        }
    except GithubException as e:
        logger.error(f"写入 GitHub 失败: {filepath}, 错误: {e}")
        raise


def save_document(
    filename: str,
    title: str,
    body: str,
    tags: list[str] = None,
    existing_metadata: dict = None,
    sha: Optional[str] = None,
    revision_note: str = "",
) -> dict[str, str]:
    """
    高级文档保存函数。
    自动处理 frontmatter、修订历史、时间戳等元数据。
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 构建元数据
    metadata = existing_metadata.copy() if existing_metadata else {}
    metadata["title"] = title
    metadata["tags"] = tags or metadata.get("tags", [])

    if "created_at" not in metadata:
        metadata["created_at"] = now
    metadata["updated_at"] = now

    # 更新修订历史
    revision_history = metadata.get("revision_history", [])
    if revision_note:
        revision_history.append({
            "date": now,
            "note": revision_note,
        })
    metadata["revision_history"] = revision_history

    # 组装完整内容
    full_content = build_frontmatter(metadata, body)

    # 构建文件路径
    filepath = _build_file_path(filename)

    # 生成提交消息
    action = "更新" if sha else "创建"
    commit_msg = f"📝 {action}知识文档: {title}"
    if revision_note:
        commit_msg += f" ({revision_note})"

    return write_file(filepath, full_content, commit_msg, sha=sha)


def read_all_documents() -> list[dict[str, Any]]:
    """读取仓库中所有知识文档，返回结构化数据列表。"""
    files = list_files()
    documents = []

    for f in files:
        doc = read_file(f["path"])
        if doc:
            documents.append(doc)

    logger.info(f"已读取 {len(documents)} 个文档")
    return documents
