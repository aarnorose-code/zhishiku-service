---
title: 快速入门示例
tags:
  - 示例
  - 入门
created_at: "2024-01-01T00:00:00Z"
updated_at: "2024-01-01T00:00:00Z"
revision_history:
  - date: "2024-01-01T00:00:00Z"
    note: 初始创建
---

# 快速入门示例

本文档通过实际示例演示如何使用知识库 API。

## 1. 搜索知识

```bash
curl -X POST https://your-service.onrender.com/api/search \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何部署 Docker 应用",
    "top_k": 5
  }'
```

## 2. 读取文档

```bash
curl -X GET https://your-service.onrender.com/api/read/docs/README.md \
  -H "Authorization: Bearer your-token"
```

## 3. 提交新知识

```bash
curl -X POST https://your-service.onrender.com/api/upsert \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Docker 最佳实践",
    "content": "# Docker 最佳实践\n\n## 镜像构建\n\n1. 使用多阶段构建减小镜像体积\n2. 合理利用构建缓存\n3. 选择合适的基础镜像",
    "tags": ["docker", "最佳实践"],
    "auto_revision": true
  }'
```

## 4. 列出所有文档

```bash
curl -X GET https://your-service.onrender.com/api/documents \
  -H "Authorization: Bearer your-token"
```

## 5. 同步 GitHub 到向量库

```bash
curl -X POST https://your-service.onrender.com/api/sync \
  -H "Authorization: Bearer your-token"
```

## MCP 客户端配置

在 Claude Desktop 的配置文件中添加：

```json
{
  "mcpServers": {
    "zhishiku": {
      "url": "https://your-service.onrender.com/mcp/sse",
      "headers": {
        "Authorization": "Bearer your-token"
      }
    }
  }
}
```

配置完成后，Claude 即可直接使用知识库的搜索、读取和写入功能。
