# 知识库 (ZhiShiKu) 🧠

> 智能云端知识库服务 —— 语义搜索 · 自动修订 · GitHub 同步 · 双协议接入

一个基于 Python 的生产级知识库服务，支持 REST API 和 MCP (Model Context Protocol) 双协议，可直接被 AI 助手（如 Claude Desktop、ChatGPT 等）调用。

---

## ✨ 核心特性

| 功能 | 说明 |
|------|------|
| 🔍 **语义搜索** | 基于向量嵌入的智能搜索，理解自然语言查询意图 |
| 🤖 **自动修订引擎** | LLM 驱动，自动判断新知识是「补充」「更正」还是「新主题」，智能合并 |
| 📁 **GitHub 同步** | 所有知识以 Markdown 存储在 GitHub 私有仓库，自动提交变更 |
| 🔌 **双协议** | 同端口同时提供 REST API（OpenAPI）和 MCP SSE 协议 |
| 🔐 **认证保护** | Bearer Token 认证，保护 API 安全 |
| ☁️ **云原生** | Docker 部署，一键上线 Render / Railway |

## 📐 架构图

```
┌───────────────────────────────────────────────────────┐
│                   客户端                               │
│  ┌──────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ Claude   │  │ ChatGPT      │  │ 自定义应用     │   │
│  │ Desktop  │  │ Actions      │  │ (curl/SDK)     │   │
│  └────┬─────┘  └──────┬───────┘  └───────┬────────┘  │
│       │ MCP SSE       │ REST API         │ REST API  │
└───────┼───────────────┼──────────────────┼───────────┘
        │               │                  │
┌───────▼───────────────▼──────────────────▼───────────┐
│                  知识库服务 (FastAPI)                   │
│  ┌─────────────┐  ┌──────────────────────────────┐   │
│  │ MCP SSE     │  │ REST API (/api/*)            │   │
│  │ (/mcp/sse)  │  │ - /api/search                │   │
│  └──────┬──────┘  │ - /api/read/{doc_id}         │   │
│         │         │ - /api/upsert                 │   │
│         │         │ - /api/documents              │   │
│         │         │ - /api/sync                   │   │
│         │         └──────────┬───────────────────┘   │
│  ┌──────▼────────────────────▼───────────────────┐   │
│  │           知识操作层 (knowledge.py)              │   │
│  │  ┌──────────────────────────────────────────┐ │   │
│  │  │     自动修订引擎 (revisor.py)              │ │   │
│  │  │  1. 接收新内容                            │ │   │
│  │  │  2. 语义搜索相似文档 (top-3)              │ │   │
│  │  │  3. LLM 判断: 补充/更正/新建              │ │   │
│  │  │  4. 合并或创建文档                        │ │   │
│  │  └──────────────────────────────────────────┘ │   │
│  └───────┬──────────────────┬────────────────────┘   │
│          │                  │                         │
│  ┌───────▼──────┐  ┌───────▼──────────┐              │
│  │ Qdrant 向量库 │  │ GitHub 同步模块   │              │
│  │ (向量存储/搜索)│  │ (读写/提交 Markdown)│             │
│  └───────┬──────┘  └───────┬──────────┘              │
└──────────┼─────────────────┼─────────────────────────┘
           │                 │
   ┌───────▼──────┐  ┌──────▼──────────┐
   │ Qdrant Cloud │  │ GitHub 私有仓库  │
   │ (向量数据库)  │  │ (Markdown 文件)  │
   └──────────────┘  └─────────────────┘
```

## 🚀 快速开始

### 前提条件

1. **Python 3.9+**
2. **Qdrant Cloud 账号** - 免费额度足够测试使用
   - 注册: https://cloud.qdrant.io
   - 创建集群，获取 URL 和 API Key
3. **GitHub 仓库** - 用于存储知识文件
   - 创建私有仓库
   - 生成 Personal Access Token (需要 repo 权限)
4. **LLM API Key** - 用于自动修订引擎
   - OpenAI / Gemini / DeepSeek 任选其一

### 第一步：克隆项目

```bash
git clone <your-repo-url>
cd zhishiku
```

### 第二步：安装依赖

```bash
# 推荐使用虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

### 第三步：配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入实际的 API Key 和配置：

```bash
# 必要配置
GITHUB_TOKEN=ghp_your_github_token
GITHUB_REPO=your-username/your-knowledge-repo
QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333
QDRANT_API_KEY=your-qdrant-api-key
EMBEDDING_API_KEY=sk-your-openai-key
LLM_API_KEY=sk-your-openai-key
AUTH_TOKEN=your-secret-token
```

### 第四步：启动服务

```bash
python server.py
```

服务启动后，你可以访问：

- **REST API 文档**: http://localhost:8000/api/docs
- **MCP SSE 端点**: http://localhost:8000/mcp/sse
- **健康检查**: http://localhost:8000/api/health

### 第五步：初始化同步

如果你的 GitHub 仓库中已有知识文件，执行一次全量同步：

```bash
curl -X POST http://localhost:8000/api/sync \
  -H "Authorization: Bearer your-secret-token"
```

---

## 📖 API 使用说明

### 搜索知识

```bash
curl -X POST http://localhost:8000/api/search \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "如何配置 Docker 网络",
    "top_k": 5,
    "tags": ["docker"]
  }'
```

### 读取文档

```bash
curl -X GET http://localhost:8000/api/read/docs/README.md \
  -H "Authorization: Bearer your-token"
```

### 提交新知识

```bash
curl -X POST http://localhost:8000/api/upsert \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Python 异步编程指南",
    "content": "# Python 异步编程\n\n## asyncio 基础\n\nasyncio 是 Python 的异步 I/O 框架...",
    "tags": ["python", "异步编程"],
    "auto_revision": true
  }'
```

### 列出所有文档

```bash
curl -X GET http://localhost:8000/api/documents \
  -H "Authorization: Bearer your-token"
```

---

## 🔌 MCP 接入指南

### Claude Desktop 配置

编辑 Claude Desktop 配置文件：

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

添加以下配置：

```json
{
  "mcpServers": {
    "zhishiku": {
      "url": "https://your-service.onrender.com/mcp/sse",
      "headers": {
        "Authorization": "Bearer your-secret-token"
      }
    }
  }
}
```

### 可用的 MCP 工具

| 工具名 | 功能 | 参数 |
|--------|------|------|
| `search_knowledge` | 语义搜索知识库 | `query`, `top_k?`, `tags?` |
| `read_document` | 读取指定文档 | `doc_id` |
| `upsert_knowledge` | 新增/更新知识 | `title`, `content`, `tags?`, `auto_revision?`, `force_new?` |
| `list_documents` | 列出所有文档 | 无 |

### ChatGPT Actions 配置

服务自动生成 OpenAPI 规范，可直接导入 ChatGPT Actions：

1. 在 ChatGPT 中创建自定义 GPT
2. 添加 Action，选择「导入 OpenAPI schema」
3. 输入 URL: `https://your-service.onrender.com/api/openapi.json`
4. 设置认证方式为 Bearer Token

---

## ☁️ 部署指南

### 方式一：Render 部署（推荐）

1. **Fork 本仓库** 到你的 GitHub 账号

2. **登录 Render**: https://render.com

3. **创建新 Web Service**:
   - 连接你的 GitHub 仓库
   - Render 会自动检测 `render.yaml` 配置

4. **配置环境变量**:
   在 Render 面板中设置以下环境变量（标记 `sync: false` 的需要手动填写）：
   - `GITHUB_TOKEN`
   - `GITHUB_REPO`
   - `QDRANT_URL`
   - `QDRANT_API_KEY`
   - `EMBEDDING_API_KEY`
   - `LLM_API_KEY`

5. **部署**: 点击「Create Web Service」，等待部署完成

### 方式二：Railway 部署

1. **登录 Railway**: https://railway.app

2. **从 GitHub 部署**:
   - 选择你的仓库
   - Railway 会自动检测 `Dockerfile`

3. **配置环境变量**: 在 Railway 面板中添加所有环境变量

4. **部署**: 自动构建和部署

### 方式三：Docker 手动部署

```bash
# 构建镜像
docker build -t zhishiku .

# 运行容器
docker run -d \
  --name zhishiku \
  -p 8000:8000 \
  -e GITHUB_TOKEN=your-token \
  -e GITHUB_REPO=user/repo \
  -e QDRANT_URL=https://your-cluster.cloud.qdrant.io:6333 \
  -e QDRANT_API_KEY=your-key \
  -e EMBEDDING_API_KEY=sk-your-key \
  -e LLM_API_KEY=sk-your-key \
  -e AUTH_TOKEN=your-secret \
  zhishiku
```

---

## ⚙️ 配置详解

### 嵌入提供商选择

| 提供商 | 说明 | 推荐场景 |
|--------|------|---------|
| `openai` | OpenAI text-embedding-3-small | **推荐**，质量高，性价比好 |
| `gemini` | Google text-embedding-004 | 免费额度较多 |
| `local` | 本地哈希嵌入 | 无 API 时的应急方案，质量有限 |

### LLM 提供商选择

| 提供商 | 推荐模型 | 说明 |
|--------|---------|------|
| `openai` | gpt-4o-mini | **推荐**，质量和成本平衡好 |
| `gemini` | gemini-2.0-flash | 免费额度较多 |
| `deepseek` | deepseek-chat | 性价比极高 |

### 环境变量完整列表

| 变量名 | 必需 | 默认值 | 说明 |
|--------|------|--------|------|
| `GITHUB_TOKEN` | 是 | - | GitHub Personal Access Token |
| `GITHUB_REPO` | 是 | - | GitHub 仓库 (格式: owner/repo) |
| `GITHUB_BRANCH` | 否 | `main` | Git 分支 |
| `GITHUB_DOCS_PATH` | 否 | `docs` | 知识文件目录 |
| `QDRANT_URL` | 是 | - | Qdrant 服务器地址 |
| `QDRANT_API_KEY` | 否 | - | Qdrant API Key |
| `QDRANT_COLLECTION` | 否 | `zhishiku` | 集合名称 |
| `EMBEDDING_PROVIDER` | 否 | `openai` | 嵌入提供商 |
| `EMBEDDING_MODEL` | 否 | `text-embedding-3-small` | 嵌入模型 |
| `EMBEDDING_DIM` | 否 | `1536` | 向量维度 |
| `EMBEDDING_API_KEY` | 取决于提供商 | - | 嵌入 API Key |
| `EMBEDDING_API_BASE` | 否 | - | 自定义 API 地址 |
| `LLM_PROVIDER` | 否 | `openai` | LLM 提供商 |
| `LLM_MODEL` | 否 | `gpt-4o-mini` | LLM 模型 |
| `LLM_API_KEY` | 是 | - | LLM API Key |
| `LLM_API_BASE` | 否 | - | 自定义 LLM API 地址 |
| `AUTH_TOKEN` | 推荐 | - | Bearer Token |
| `HOST` | 否 | `0.0.0.0` | 监听地址 |
| `PORT` | 否 | `8000` | 监听端口 |
| `LOG_LEVEL` | 否 | `INFO` | 日志级别 |

---

## 🔧 自动修订引擎详解

自动修订引擎是知识库的核心智能组件，其工作流程如下：

```
提交新知识
    │
    ▼
嵌入新内容，搜索 top-3 相似文档
    │
    ▼
┌──────────────────────────────┐
│ LLM 分析判断                  │
│                              │
│ 输入：新内容 + 相似文档       │
│ 输出：action + 合并方案       │
│                              │
│ ┌────────┐ ┌────────┐ ┌───┐ │
│ │ 补充   │ │ 更正   │ │新 │ │
│ │        │ │        │ │建 │ │
│ └───┬────┘ └───┬────┘ └─┬─┘ │
└─────┼──────────┼────────┼───┘
      │          │        │
      ▼          ▼        ▼
 合并到已有    替换已有   创建新
 文档末尾    文档相关段落  文档
      │          │        │
      ▼          ▼        ▼
 提交到 GitHub + 更新向量索引
```

### 示例场景

**场景 1：补充**
- 已有文档《Python 基础教程》包含变量和函数部分
- 新提交「Python 类与面向对象编程」
- 引擎判断为「补充」，将新内容合并到已有文档中

**场景 2：更正**
- 已有文档记录「Python 3.8 最新特性」
- 新提交「Python 3.12 新增了模式匹配语法」
- 引擎判断为「更正/更新」，更新版本相关内容

**场景 3：新建**
- 已有文档都关于 Python
- 新提交「Rust 所有权机制详解」
- 引擎判断为「新主题」，创建新文档

---

## 📁 项目结构

```
zhishiku/
├── server.py              # 主入口：FastAPI + MCP SSE 挂载
├── core/
│   ├── __init__.py
│   ├── config.py          # 环境配置管理
│   ├── auth.py            # Bearer Token 认证
│   ├── embeddings.py      # 嵌入向量生成（多提供商）
│   ├── vector_store.py    # Qdrant 向量数据库操作
│   ├── github_sync.py     # GitHub 仓库读写同步
│   ├── revisor.py         # 自动修订引擎（LLM 判断与合并）
│   └── knowledge.py       # 知识操作整合层
├── mcp_tools.py           # MCP 工具定义
├── api_routes.py          # REST API 路由
├── docs/                  # 初始知识文档模板
│   ├── README.md
│   └── examples/
│       └── getting-started.md
├── requirements.txt       # Python 依赖
├── Dockerfile             # Docker 构建文件
├── render.yaml            # Render 部署配置
├── .env.example           # 环境变量示例
└── README.md              # 本文档
```

---

## 🛡️ 安全注意事项

1. **务必设置 `AUTH_TOKEN`** —— 生产环境不设置令牌将导致 API 完全开放
2. **不要将 `.env` 提交到 Git** —— 已在 `.gitignore` 中排除
3. **使用 HTTPS** —— Render/Railway 默认提供 HTTPS
4. **定期轮换 Token** —— 包括 GitHub Token 和 API Keys
5. **GitHub Token 权限最小化** —— 只授予 `repo` 权限

---

## 📄 许可证

MIT License
