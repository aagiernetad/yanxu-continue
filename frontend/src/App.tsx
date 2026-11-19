import {
  ApiOutlined,
  BranchesOutlined,
  CloseCircleOutlined,
  CloudServerOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  FileSearchOutlined,
  ToolOutlined,
  CopyOutlined,
  ExperimentOutlined,
  PlusOutlined,
  MessageOutlined,
  CloseOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import { Alert, App as AntApp, Button, Input, Popover } from "antd";
import { useEffect, useRef, useState } from "react";
import { ChatComposer } from "./components/ChatComposer";
import { ChatHeader } from "./components/ChatHeader";
import { ConversationThread } from "./components/ConversationThread";
import { KnowledgeDrawer } from "./components/KnowledgeDrawer";
import { API_BASE_URL, WS_BASE_URL } from "./lib/config";
import { useDeepAgentSession } from "./hooks/useDeepAgentSession";
import type { ConnectionState, SessionSummary, UploadedItem } from "./types";

function connectionLabel(state: ConnectionState): string {
  const labels: Record<ConnectionState, string> = {
    connecting: "连接中",
    connected: "已连接",
    reconnecting: "重连中",
    closed: "已关闭"
  };
  return labels[state];
}

export default function App() {
  const { message, modal } = AntApp.useApp();
  const [sidebarOpen, setSidebarOpen] = useState(() =>
    window.matchMedia("(min-width: 981px)").matches
  );
  const [isNarrow, setIsNarrow] = useState(() =>
    window.matchMedia("(max-width: 980px)").matches
  );
  const [query, setQuery] = useState("");
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [stagedItems, setStagedItems] = useState<UploadedItem[]>([]);
  const streamRef = useRef<HTMLElement | null>(null);
  // 是否允许自动跟随最新消息
  const shouldFollowRef = useRef(true);

  // 记录上一次的滚动位置
  const previousScrollTopRef = useRef(0);
  const session = useDeepAgentSession();
  const { turns, historyLoading, historyError } = session;

  useEffect(() => {
    setQuery("");
    setStagedItems([]);
    shouldFollowRef.current = true;
  }, [session.threadId]);

  useEffect(() => {
    const media = window.matchMedia("(min-width: 981px)");
    const handleResize = (event: MediaQueryListEvent) => {
      setSidebarOpen(event.matches);
      setIsNarrow(!event.matches);
    };
    media.addEventListener("change", handleResize);
    return () => media.removeEventListener("change", handleResize);
  }, []);

  useEffect(() => {
    if (!sidebarOpen || !isNarrow) return;
    document.querySelector<HTMLButtonElement>(".sidebar-mobile-close")?.focus();
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSidebarOpen(false);
    };
    document.addEventListener("keydown", handleEscape);
    return () => {
      document.removeEventListener("keydown", handleEscape);
      document.querySelector<HTMLButtonElement>(".sidebar-toggle")?.focus();
    };
  }, [sidebarOpen, isNarrow]);

  function handleStreamScroll() {
    const node = streamRef.current;
    if (!node) return;

    // 当前距离底部还有多少像素
    const distanceToBottom =
      node.scrollHeight - node.scrollTop - node.clientHeight;

    // 用户回到接近底部的位置
    if (distanceToBottom <= 80) {
      shouldFollowRef.current = true;
    }
    // 用户正在向上滚动
    else if (
      node.scrollTop < previousScrollTopRef.current - 2
    ) {
      shouldFollowRef.current = false;
    }

    previousScrollTopRef.current = node.scrollTop;
  }

  useEffect(() => {
    const node = streamRef.current;

    if (turns.length === 0) {
      node?.scrollTo({ top: 0 });
      return;
    }

    // 用户正在阅读旧内容时，不自动滚动
    if (!node || !shouldFollowRef.current) {
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      node.scrollTo({
        top: node.scrollHeight,
        behavior: "auto"
      });

      previousScrollTopRef.current = node.scrollTop;
    });

    return () => window.cancelAnimationFrame(frame);
  }, [turns]);


  async function handleSubmit() {
    const cleanQuery = query.trim();
    if (!cleanQuery || session.isRunning || session.isSubmitting || session.isUploading) return;
    shouldFollowRef.current = true;
    try {
      await session.submitTask(cleanQuery);
      setQuery("");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "任务启动失败");
    }
  }

  async function handleCancel() {
    try {
      const response = await session.cancelCurrentTask();
      message.info(response.status === "cancelling" ? "取消请求已发送，正在等待当前调用结束" : "任务已取消");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "取消任务失败");
    }
  }

  async function handleUpload(items: UploadedItem[]) {
    try {
      const response = await session.uploadFiles(items);
      setStagedItems([]);
      message.success(`已上传 ${response.files.length} 个文件`);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "上传失败");
    }
  }

  function handleNewSession() {
    session.resetSession();
  }

  function handleDeleteSession(item: SessionSummary) {
    modal.confirm({
      title: "删除这段会话？",
      content: `“${item.title}”的聊天记录、附件和生成文件将一并删除，删除后无法恢复。`,
      okText: "删除会话",
      cancelText: "保留",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await session.deleteSession(item.thread_id);
          message.success("会话已删除");
        } catch (error) {
          message.error(error instanceof Error ? error.message : "删除会话失败");
          throw error;
        }
      }
    });
  }

  async function handleCopyThreadId() {
    try {
      await navigator.clipboard.writeText(session.threadId);
      message.success("Thread ID 已复制");
    } catch {
      message.error("复制失败，请检查浏览器剪贴板权限");
    }
  }

  const online = session.connectionState === "connected";

  function handleSelectTurn(turnId: string) {
    const node = streamRef.current;
    const target = document.getElementById(`turn-${turnId}`);
    if (node && target) {
      shouldFollowRef.current = false;
      node.scrollTop += target.getBoundingClientRect().top - node.getBoundingClientRect().top;
      previousScrollTopRef.current = node.scrollTop;
      target.focus({ preventScroll: true });
    }
    if (window.matchMedia("(max-width: 980px)").matches) setSidebarOpen(false);
  }

  return (
    <div
      className={`chat-app-shell min-h-dvh ${sidebarOpen ? "" : "sidebar-collapsed"
        }`}
    >
      {sidebarOpen && (
        <button
          className="sidebar-scrim"
          type="button"
          aria-label="关闭会话导航"
          onClick={() => setSidebarOpen(false)}
        />
      )}
      <aside className="chat-sidebar" id="chat-sidebar" aria-label="会话导航" inert={!sidebarOpen}>
        <div className="sidebar-brand">
          <span className="brand-mark"><ExperimentOutlined aria-hidden /></span>
          <div>
            <h1>DeepSearch</h1>
            <p>AI 科研助手</p>
          </div>
          <Button
            className="sidebar-mobile-close"
            type="text"
            icon={<CloseOutlined />}
            aria-label="关闭会话导航"
            onClick={() => setSidebarOpen(false)}
          />
        </div>

        <Button className="new-chat-button" icon={<PlusOutlined />} block onClick={handleNewSession} disabled={session.isSubmitting || session.isUploading || session.isDeciding || Boolean(session.deletingThreadId)}>
          新建研究
        </Button>

        <Button className="knowledge-entry" type="text" icon={<FileSearchOutlined aria-hidden />} aria-label="打开知识库" block onClick={() => {
          setKnowledgeOpen(true);
          if (isNarrow) setSidebarOpen(false);
        }}>
          知识库
        </Button>

        <nav className="session-navigation" aria-label="研究会话与记录">
          <Input.Search
            className="session-search"
            aria-label="搜索历史研究"
            placeholder="搜索历史研究"
            allowClear
            value={session.sessionQuery}
            onChange={(event) => session.setSessionQuery(event.target.value)}
          />
          <div className="sidebar-section-heading"><span className="sidebar-label">历史研究</span></div>
          {session.sessionsError ? <p className="session-list-error">{session.sessionsError}</p> : null}
          <ul className="session-turn-list">
            {session.sessions.map((item) => (
              <li key={item.thread_id} className="session-history-row">
                <button
                  type="button"
                  aria-current={item.thread_id === session.threadId ? "page" : undefined}
                  disabled={session.isUploading || session.isSubmitting || session.isDeciding || Boolean(session.deletingThreadId)}
                  title={item.title}
                  onClick={() => {
                    session.selectSession(item.thread_id);
                    if (isNarrow) setSidebarOpen(false);
                  }}
                >
                  <MessageOutlined aria-hidden />
                  <span>{item.title}</span>
                  {item.is_running ? <small>进行中</small> : null}
                </button>
                <Button
                  className="session-delete-button"
                  type="text"
                  danger
                  icon={<DeleteOutlined />}
                  aria-label={`删除会话：${item.title}`}
                  title={item.can_delete ? "删除会话" : "请先取消任务，再删除会话"}
                  disabled={!item.can_delete || session.isUploading || session.isSubmitting || session.isDeciding || Boolean(session.deletingThreadId)}
                  loading={session.deletingThreadId === item.thread_id}
                  onClick={() => handleDeleteSession(item)}
                />
              </li>
            ))}
          </ul>
          {!session.sessions.length ? <p className="session-list-empty">{session.sessionQuery ? "暂无匹配的研究" : "尚无历史研究"}</p> : null}
          <div className="sidebar-section-heading">
            <span className="sidebar-label">当前会话</span>
            <span className="session-count">{turns.length}</span>
          </div>
          {turns.length > 0 ? (
            <ul className="session-turn-list">
              {turns.map((turn, index) => (
                <li key={turn.id}>
                  <button type="button" onClick={() => handleSelectTurn(turn.id)} title={turn.content}>
                    <MessageOutlined aria-hidden />
                    <span>{turn.content}</span>
                    <small>{String(index + 1).padStart(2, "0")}</small>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="session-navigation-empty">
              <MessageOutlined aria-hidden />
              <p>从一个问题开始</p>
              <span>本次会话的研究记录将显示在这里</span>
            </div>
          )}
        </nav>

        <details className="sidebar-details">
          <summary><SettingOutlined aria-hidden />任务详情<span className="details-chevron">⌄</span></summary>
          <div className="sidebar-details-body">
            <div className="sidebar-section">
              <span className="sidebar-label">会话 ID</span>
              <div className="thread-id-row">
                <strong className="thread-id" title={session.threadId}>
                  {session.threadId.slice(0, 8)}
                </strong>
                <Button
                  type="text"
                  size="small"
                  icon={<CopyOutlined />}
                  title="复制完整 Thread ID"
                  aria-label="复制完整 Thread ID"
                  onClick={handleCopyThreadId}
                />
              </div>
            </div>

            <div className="sidebar-status-list">
              <div className="sidebar-status">
                <CloudServerOutlined aria-hidden />
                <span>模型调用</span>
                <strong>{session.stats.modelCalls}{session.stats.modelBudget ? ` / ${session.stats.modelBudget}` : ""}</strong>
              </div>
              <div className="sidebar-status">
                <BranchesOutlined aria-hidden />
                <span>助手调度</span>
                <strong>{session.stats.assistantEvents}</strong>
              </div>
              <div className="sidebar-status">
                <ToolOutlined aria-hidden />
                <span>工具调用</span>
                <strong>{session.stats.toolEvents}</strong>
              </div>
              <div className={session.stats.errorEvents > 0 ? "sidebar-status sidebar-status--error" : "sidebar-status"}>
                <CloseCircleOutlined aria-hidden />
                <span>异常</span>
                <strong>{session.stats.errorEvents}</strong>
              </div>
            </div>

            <div className="sidebar-section">
              <span className="sidebar-label">研究助手</span>
              <ul className="agent-mini-list">
                <li><CloudServerOutlined aria-hidden />网络搜索助手</li>
                <li><DatabaseOutlined aria-hidden />数据库查询助手</li>
                <li><FileSearchOutlined aria-hidden />知识库助手</li>
              </ul>
            </div>

            <div className="sidebar-section sidebar-endpoints">
              <span className="sidebar-label">服务地址</span>
              <code>{API_BASE_URL}</code>
              <code>{WS_BASE_URL}</code>
            </div>

            {import.meta.env.DEV && (
              <div className="sidebar-section">
                <span className="sidebar-label">开发调试</span>
                <Button block size="small" disabled={!online} onClick={session.simulateWebSocketDrop}>
                  模拟断线 8 秒
                </Button>
                <p>补收事件：{session.replayedEventCount} 条</p>
              </div>
            )}
          </div>
        </details>

        <div className="sidebar-footer">
          <Popover
            title="WebSocket 连接详情"
            trigger="click"
            placement="right"
            content={
              <div className="socket-popover">
                <p>
                  连接状态：{connectionLabel(session.connectionState)}
                </p>

                <p>
                  Thread ID：{session.threadId}
                </p>

                <p>
                  最近 Agent 事件：
                  {session.events.length > 0
                    ? session.events[session.events.length - 1].event
                    : "暂无事件"}
                </p>

                <p>
                  上次心跳响应：
                  {session.lastPongAt
                    ? new Date(session.lastPongAt).toLocaleTimeString("zh-CN", {
                      hour12: false
                    })
                    : "尚未收到 pong"}
                </p>
              </div>
            }
          >
            <button
              type="button"
              className={`sidebar-status sidebar-status-button ${online ? "sidebar-status--online" : "sidebar-status--warn"
                }`}
            >
              <ApiOutlined aria-hidden />
              <span>服务连接</span>
              <strong>{connectionLabel(session.connectionState)}</strong>
            </button>
          </Popover>

          <span className="sidebar-footnote">多智能体协作 · 让研究更进一步</span>
        </div>
      </aside>

      <main className={`chat-main ${turns.length === 0 ? "chat-main--empty" : ""}`} inert={isNarrow && sidebarOpen}>
        <ChatHeader
          sidebarOpen={sidebarOpen}
          isRunning={session.isRunning}
          phase={turns[turns.length - 1]?.status}
          startedAt={[...session.events].reverse().find((event) => event.event === "plan_approved")?.timestamp || turns[turns.length - 1]?.timestamp}
          finishedAt={[...session.events].reverse().find((event) => ["task_result", "task_cancelled", "error"].includes(event.event))?.timestamp}
          onToggleSidebar={() => setSidebarOpen(prev => !prev)}
        />

        {session.lastError ? (
          <Alert
            className="chat-alert"
            message={session.lastError}
            showIcon
            type="error"
          />
        ) : null}

        {historyLoading && (
          <Alert
            className="chat-alert"
            message="正在恢复历史对话…"
            type="info"
            showIcon
          />
        )}

        {historyError && (
          <Alert
            className="chat-alert"
            message={`历史同步失败：${historyError}`}
            action={<Button size="small" onClick={() => session.restoreHistory().catch((error: Error) => message.error(error.message))}>重试同步</Button>}
            type="error"
            showIcon
          />
        )}

        <section className="chat-stream-panel" ref={streamRef} onScroll={handleStreamScroll} aria-label="研究工作区">
          <ConversationThread turns={turns} isDeciding={session.isDeciding || historyLoading || Boolean(historyError) || Boolean(session.deletingThreadId)} onPlanDecision={session.decidePlan} />
        </section>

        <ChatComposer
          isUnavailable={historyLoading || Boolean(historyError) || session.isSubmitting || session.isDeciding || Boolean(session.deletingThreadId)}
          isCancelling={session.isCancelling}
          isRunning={session.isRunning}
          isUploading={session.isUploading}
          onCancel={handleCancel}
          onQueryChange={setQuery}
          onStagedItemsChange={setStagedItems}
          onSubmit={handleSubmit}
          onUpload={handleUpload}
          query={query}
          stagedItems={stagedItems}
          uploadedItems={session.uploadedItems}
        />
      </main>
      <KnowledgeDrawer open={knowledgeOpen} onClose={() => setKnowledgeOpen(false)} />
    </div>
  );
}
