# 研序（YanXu）启动说明

## 环境准备

使用 Python 3.12、uv，以及能够运行本项目 Vite 构建的 Node.js 环境。前端使用 pnpm 10.33.0，版本声明见 `frontend/package.json`。

在仓库根目录安装后端依赖：

```bash
uv sync --frozen
```

复制根目录 `.env.example` 为 `.env`，填写主模型的 `OPENAI_API_KEY`、`OPENAI_BASE_URL` 和 `LLM_QWEN_MAX`。联网搜索需要 `TAVILY_API_KEY`。真实 `.env` 文件仅保存在本机。

## 启动前后端

在仓库根目录启动后端：

```bash
uv run python -m app.api.server
```

另开终端，安装前端依赖并启动：

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

默认前端地址为 http://localhost:5173，后端接口文档为 http://127.0.0.1:8000/docs，以终端实际输出为准。需要修改后端地址时，复制 `frontend/.env.example` 为 `frontend/.env.local`，配置 `VITE_API_BASE_URL` 和 `VITE_WS_BASE_URL`。

前端类型检查与生产构建：

```bash
cd frontend
pnpm build
```

## 配置所需数据服务

- **本地知识库**：填写 `RAG_EMBEDDING_API_KEY`、`RAG_EMBEDDING_BASE_URL`、模型名称和向量维度。需要重排时，填写 `RAG_RERANK_BASE_URL` 和 `RAG_RERANK_MODEL`；重排复用 Embedding API Key。
- **数据库查询**：连接自己的 MySQL 数据库，填写 `MYSQL_*` 配置，使用仅拥有所需业务库 SELECT 权限的专用账号。本发布版本不附带教学数据库和初始化数据。
- **Jev 证据评估**：`TYPESAFE_API_KEY` 为可选项，未配置时跳过该评估。
- **RAGFlow**：当前主流程使用本地 RAG；保留的 RAGFlow 工具为可选集成，需要使用时另行填写 `RAGFLOW_*`。

知识库文档和索引需要自行准备。本发布版本不包含个人资料或演示 PDF。在仓库根目录导入自己的文档：

```bash
uv run python -m app.rag.rag_pipeline index "你的文档路径.pdf"
```

导入后可在网页知识库面板查看已收录文档，也可通过命令行检索：

```bash
uv run python -m app.rag.rag_pipeline search "你的研究问题"
```

独立 RAG 问答命令 `app.rag.rag_generator` 还需要配置 `RAG_GENERATION_API_KEY`、`RAG_GENERATION_BASE_URL` 和 `RAG_GENERATION_MODEL`。

## 运行范围与数据

当前面向本机单用户、单 worker，未提供用户认证。聊天记录、计划和任务状态默认存储于 `app/data/`，上传资料位于 `app/updated/`，产物位于 `app/output/`，本地向量索引位于 `data/knowledge_base/`；这些运行数据均不随源码发布。服务重启后，未完成的执行任务会标记中断，等待确认的计划保留。

Reviewer 由主 Agent 按需调用。模型、联网搜索、Embedding 和重排等外部服务需要有效配置，研究结果和来源仍需人工核对。
