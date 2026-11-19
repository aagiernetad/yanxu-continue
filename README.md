# 研序 · 多智能体研究工作台

> 让研究从一个问题，有序走向有据可查的结论。

研序（YanXu）是一个运行在本机的多智能体研究工作台。你可以提出研究问题、上传资料，先查看系统给出的计划，确认后再让 Agent 搜索网页、查询数据库、检索知识库或整理文档。研究进展会显示在聊天页面中，完成后可以阅读答案、查看来源并下载报告。

“研”代表研究与资料分析，“序”代表先规划、再执行、最后汇总的有序流程。

## 项目背景

这个项目的出发点，是想学习 ChatGPT 等网页 AI 聊天工具的交互方式，并尝试自己搭建一个可以实际使用的 AI 应用。通过实现问题输入、附件上传、回答展示和历史会话管理，理解聊天页面如何与后端模型调用、任务状态和数据存储配合。

在此基础上，希望把它用于更具体的资料调研场景。例如，了解一项新技术时，往往需要查阅网页、阅读本地文档、检索知识库，再把不同来源的信息核对、整理成结论。这类任务涉及多个步骤，除了最终答案，也需要能够提前确认研究方向，并在执行中了解进展。

因此，研序在已有多智能体研究框架上进行二次开发，将聊天交互与研究计划确认、专家协作、执行过程展示和报告交付结合起来，在实践中学习一个多智能体研究应用从前端到后端的完整实现。

## 项目目标

让用户从提出问题、确认研究计划，到查看执行过程、获取答案和报告，在同一个聊天页面内完成研究流程。围绕这一目标，重点完善以下能力：

- **研究方向确认**：开始执行前展示计划，支持用户提出修改意见并确认当前版本。
- **多源资料协作处理**：由主 Agent 调度不同专家，结合网页、数据库、知识库和附件形成回答。
- **执行过程可查看、可控制**：展示调用与任务状态，支持取消、历史查询和刷新后同步进度，并限制调用预算、并发和超时。
- **研究结果交付**：保留回答、来源和输出文件，支持按需下载 Markdown / PDF 报告。

## 界面预览

下面按一次研究任务的使用流程，展示从提出问题、准备资料到查看结果和管理会话的主要界面。

### 1. 研究首页

从一个问题或一份资料开始，在输入框中提出研究需求。

![研究首页：问题输入与添加附件入口](docs/images/origin.png)

### 2. 上传附件

通过输入框旁的添加附件入口选择本地资料，已添加的附件显示在输入框上方。

![上传附件：选择本地文件并查看已添加的附件](docs/images/upload.png)

### 3. 知识库预览

查看知识库已收录的文档，按文档名称筛选，并选择文档查看已收录的原文片段。

![知识库预览：文档列表、名称筛选与原文片段查看入口](docs/images/rag.png)

### 4. 研究计划确认

执行前先查看研究计划与预期交付内容，可以直接确认执行，也可以提出修改意见后再确认。

![研究计划确认：查看计划并选择确认执行或修改计划](docs/images/plan.png)

### 5. 研究执行过程

执行期间查看模型与工具调用事件，并通过任务详情了解调用预算使用、助手调度和异常情况。

![研究执行过程：调用事件、执行状态与任务统计](docs/images/running_01.png)

### 6. 研究结果与参考来源

任务完成后，在聊天页面阅读最终结论和详细说明。

![研究结果：任务完成状态与最终回答](docs/images/result.png)

继续查看参考来源、检索限制和输出文件区域。本示例以对话形式交付，未生成额外文件。

![研究结果：参考来源、检索限制与输出文件区域](docs/images/result_01.png)

### 7. 会话管理

在侧边栏查看历史研究；删除会话前弹窗确认，并提示聊天记录、附件和生成文件的删除范围。

![会话管理：删除会话前的确认弹窗](docs/images/delete.png)

## 实现方案

### 关键实现

- **先确认研究方向**：执行前先生成计划。可以确认开始，也可以提出修改意见，等新计划生成后再确认。
- **不同资料交给不同专家**：主 Agent 根据问题调度网络、数据库、知识库和评审专家，综合结果后形成回答。
- **随时查看执行情况**：页面展示模型与工具调用、回答和文件；支持取消任务、切换历史会话，以及刷新后同步进度。
- **从资料到报告**：上传附件进行分析，或检索已经导入的知识库；按需要生成 Markdown 和 PDF 文件。
- **限制执行范围**：一轮任务共享调用预算，设置并发与超时限制，输入附件和生成文件按任务目录管理。

会话、计划和输出文件保存在本机；模型、网络搜索、Embedding 和重排请求会发送到配置的外部服务。

### 它是怎么工作的

```text
React 聊天页面
       │ HTTP + WebSocket
       ▼
FastAPI 后端
  ├─ 生成计划 → 等待确认 → 启动研究任务
  ├─ 主 Agent → 专家子 Agent → 搜索、SQL、RAG 和文件工具
  ├─ Middleware 检查预算，Monitor / Manager 保存并推送事件
  └─ SQLite 业务记录 + LangGraph 检查点 + 本轮文件目录
```

前端负责展示和交互，后端负责 Agent 执行、任务状态与持久化。确认和取消等操作通过 HTTP 提交，进展通过 WebSocket 推送；页面刷新后从后端查询历史，接上当前任务。

<details>
<summary>完整任务时序图：提交、规划、确认、执行与历史恢复</summary>

```mermaid
sequenceDiagram
    actor User as 用户
    participant UI as React / Hook
    participant API as FastAPI / 后台 Task
    participant DB as SessionStore / SQLite
    participant Planner as 规划模型
    participant Agent as 研究图 / 工具 / 子 Agent
    participant Event as Monitor / Manager

    UI->>API: 建立 WebSocket /ws/{thread_id}
    API->>Event: 登记会话连接，回放保留事件
    opt 用户上传附件
        UI->>API: POST /api/upload
        API-->>UI: 返回已保存的附件名称
    end

    User->>UI: 1. 输入问题并点击提交
    UI->>API: 2. POST /api/task，携带 query、thread_id、run_id
    API->>DB: 3. 检查重复与活跃任务，创建 planning 记录
    Note over API: 先 launch_task 调度规划，再返回接口响应
    par 本次 HTTP 回执
        API-->>UI: 4. 返回 planning、thread_id、run_id
    and 后台规划
        API->>Event: task_accepted，保存后推送“正在生成研究计划”
        API->>Planner: 5. plan_task：问题、附件名、旧计划和修改意见
        Planner->>Event: observe：model_start / model_end
        Planner-->>API: 6. 返回并校验 Markdown 计划
    end
    API->>Event: 7. 等待观测事件排空，提交 plan_ready
    Event->>DB: 8. 校验阶段与版本，保存计划并改为 waiting_approval
    Event-->>UI: 9. WebSocket 推送计划，Hook 更新状态并渲染 PlanCard
    Note over User,Agent: 等待确认时不读取附件正文、不创建本轮目录、不运行研究工具

    opt 用户先提出修改意见
        User->>UI: 展开“修改计划”，填写意见并提交
        UI->>API: POST 计划接口：revise、原 plan_version、feedback
        API->>DB: 事务保存意见，版本加一，状态改为 planning
        Note over API,UI: 调度新的规划 Task，重复第 5～9 步，仍需用户确认
    end

    User->>UI: 10. 查看当前版本，点击“确认并执行”
    UI->>API: 11. POST /api/task/{thread_id}/plan，action=approve
    API->>DB: 12. 校验当前版本，原子保存 running 与 approved_version
    Note over API: 先调度执行 Task，再返回审批接口；以下两条链路可交错
    par 审批 HTTP 回执
        API-->>UI: 返回审批受理结果，Hook 随后查询历史
    and 后台执行
        API->>Event: plan_approved，保存并推送
        API->>Agent: 13. run_deep_agent 检查批准状态，准备目录与附件
        Note over Agent: 设置上下文，加入批准计划，调用 astream
    end
    Note over Agent: 模型提出调用，框架执行工具或 task 委派，再将结果交回模型

    loop 执行期间持续发生
        Agent->>Event: 14. Middleware / Monitor 上报调用事件和正文快照
        Event->>DB: 15. 保存变化，递增 revision
        Event-->>UI: 16. WebSocket 推送，按 run_id 与 revision 合并
    end

    Agent-->>API: 17. 图完整结束，返回最终回答
    API->>Event: 18. terminal 排空事件，扫描产物并保存清单，提交 task_result
    Event->>DB: 19. 同一事务保存 completed、最终正文和终态事件
    Event-->>UI: 20. 推送完成结果，前端同步最终回答与文件

    opt 刷新、重新聚焦或每五秒历史同步
        UI->>API: 21. GET /api/sessions/{thread_id}
        API->>DB: 22. 读取任务、计划、正文、事件与文件元数据
        DB-->>API: 23. 返回一致的历史快照
        API-->>UI: 24. 返回历史，Hook 按 revision 合并并重新渲染
    end
    Note over UI,DB: 第 21～24 步在执行期间也会发生；刷新不会重新提交任务
```

用户可以修订计划或取消任务。异常和超时会结束对应任务；联网搜索次数耗尽时，停止新增搜索，继续基于已有证据整理结果。

</details>

## 技术栈

| 部分 | 使用的技术 | 负责什么 |
| --- | --- | --- |
| 前端 | React 19、TypeScript、Vite、Ant Design、Tailwind CSS | 聊天、计划确认、执行过程和报告下载 |
| 后端 | Python 3.12、FastAPI、asyncio | HTTP / WebSocket、任务调度、取消和状态同步 |
| Agent | DeepAgents、LangGraph、LangChain | 模型调用、工具执行、专家委派和图状态 |
| 存储 | SQLite、AsyncSqliteSaver、本地文件 | 任务历史、计划、检查点、附件和报告 |
| 检索与文档 | Tavily、Embedding、Rerank、ReportLab | 网络与知识检索、Markdown / PDF 交付 |

## 目录说明

```text
.
├── app/
│   ├── api/          # 后端接口、任务调度、存储、连接与上下文
│   ├── agent/        # 主 Agent、专家配置和调用中间件
│   ├── prompt/       # 提示词
│   ├── rag/          # 文档导入、向量检索与重排
│   ├── tools/        # 搜索、数据库、附件和报告工具
│   └── utils/        # 文件路径、产物检查和证据处理
├── frontend/         # React 页面与会话状态
├── docs/             # 启动说明与 README 界面截图
├── .env.example      # 环境变量模板
├── pyproject.toml    # Python 依赖
└── uv.lock           # 依赖锁文件
```

## 本地运行

环境安装、配置、前后端启动及知识库导入见 [启动说明](docs/SETUP.md)。
