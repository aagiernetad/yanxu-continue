import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, cancelTask, decideTaskPlan, deleteSession as deleteSessionRequest, getSessionHistory, listSessionFiles, listSessions, startTask, uploadSessionFiles } from "../lib/api";
import { WS_BASE_URL } from "../lib/config";
import { createThreadId, getStoredThreadId, storeThreadId } from "../lib/thread";
import type { ChatTurn } from "../components/ConversationThread";
import type { ConnectionState, MonitorMessage, PlanAction, SessionSummary, SocketMessage, UploadedItem } from "../types";

const MAX_EVENTS = 120;
const terminalEvents = new Set(["task_result", "task_cancelled", "error"]);

// 历史快照和实时事件共用 revision：慢到的 HTTP 响应不能覆盖较新的流式正文或终态。
export function mergeHistory(previous: ChatTurn[], incoming: ChatTurn[]): ChatTurn[] {
  const local = new Map(previous.map((turn) => [turn.id, turn]));
  const merged = incoming.map((turn) => {
    const existing = local.get(turn.id);
    local.delete(turn.id);
    return existing && existing.revision > turn.revision ? existing : turn;
  });
  return [...merged, ...local.values()];
}

export function applyMonitorEvent(turns: ChatTurn[], event: MonitorMessage): ChatTurn[] {
  let turn = turns.find((item) => item.id === event.run_id);
  if (!turn) {
    if (event.event !== "task_accepted" || typeof event.data.query !== "string") return turns;
    turn = { id: event.run_id, revision: 0, status: "running", content: event.data.query,
      events: [], files: [], isRunning: true, result: "", timestamp: event.timestamp };
    turns = [...turns, turn];
  }
  if (event.revision <= turn.revision) return turns;
  const status = event.event === "task_accepted" && event.data.phase === "planning" ? "planning"
    : event.event === "plan_ready" ? "waiting_approval"
    : event.event === "plan_approved" ? "running"
    : event.event === "task_result" ? "completed"
    : event.event === "task_cancelled" ? "cancelled"
    : event.event === "error" ? "failed" : turn.status;
  const text = typeof event.data.result === "string" ? event.data.result : "";
  return turns.map((item) => item.id !== event.run_id ? item : {
    ...item, revision: event.revision, status,
    isRunning: ["planning", "waiting_approval", "running", "cancelling"].includes(status),
    plan: event.event === "plan_ready" && typeof event.data.plan === "string" ? event.data.plan : item.plan,
    planVersion: typeof event.data.plan_version === "number" ? event.data.plan_version : item.planVersion,
    result: event.event === "answer_delta" || event.event === "task_result" ? text
      : terminalEvents.has(event.event) ? item.result || event.message : item.result,
    events: event.event === "answer_delta" ? item.events : [...item.events, event].slice(-MAX_EVENTS)
  });
}

export function useDeepAgentSession() {
  const [threadId, setThreadId] = useState(getStoredThreadId);
  const currentThreadRef = useRef(threadId);
  const epochRef = useRef(0);
  const submitRef = useRef<string | null>(null);
  const uploadingRef = useRef(false);
  const decisionRef = useRef(false);
  const deletionRef = useRef<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const demoOfflineUntilRef = useRef(0);
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState("");
  const [lastError, setLastError] = useState("");
  const [lastPongAt, setLastPongAt] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isDeciding, setIsDeciding] = useState(false);
  const [uploadedItems, setUploadedItems] = useState<UploadedItem[]>([]);
  const [replayedEventCount, setReplayedEventCount] = useState(0);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionQuery, setSessionQuery] = useState("");
  const [sessionsError, setSessionsError] = useState("");
  const [deletingThreadId, setDeletingThreadId] = useState<string | null>(null);
  const [sessionListRevision, setSessionListRevision] = useState(0);
  const current = turns[turns.length - 1];
  const active = turns.find((turn) => turn.isRunning);
  const isRunning = Boolean(active);
  const isCancelling = active?.status === "cancelling";
  const events = current?.events || [];
  const files = current?.files || [];
  const sessionPath = events.find((event) => event.event === "session_created")?.data.path;

  const selectSession = useCallback((id: string) => {
    if (submitRef.current || uploadingRef.current || decisionRef.current || deletionRef.current || id === currentThreadRef.current) return;
    epochRef.current += 1;
    currentThreadRef.current = id;
    storeThreadId(id);
    setThreadId(id);
    setTurns([]);
    setUploadedItems([]);
    setHistoryLoading(true);
    setHistoryError("");
    setLastError("");
    setReplayedEventCount(0);
  }, []);

  const restoreHistory = useCallback(async () => {
    const epoch = epochRef.current;
    const response = await getSessionHistory(threadId);
    if (currentThreadRef.current !== threadId || epoch !== epochRef.current) return response;
    setTurns((previous) => mergeHistory(previous, response.turns));
    if (!uploadingRef.current) {
      setUploadedItems(response.uploads.map((file) => ({ ...file, uid: file.name })));
    }
    setHistoryError("");
    setHistoryLoading(false);
    return response;
  }, [threadId]);

  useEffect(() => {
    let disposed = false;
    const restore = () => restoreHistory().catch((error: unknown) => {
      if (!disposed) {
        setHistoryError(error instanceof Error ? error.message : "历史恢复失败");
        setHistoryLoading(false);
      }
    });
    void restore();
    const timer = window.setInterval(restore, 5000);
    window.addEventListener("focus", restore);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", restore);
    };
  }, [restoreHistory]);

  useEffect(() => {
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      listSessions(sessionQuery, controller.signal).then((response) => {
        setSessions(response.sessions);
        setSessionsError("");
      }).catch((error: unknown) => {
        if (!controller.signal.aborted) setSessionsError(error instanceof Error ? error.message : "会话列表加载失败");
      });
    }, 250);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [sessionQuery, threadId, isRunning, sessionListRevision]);

  useEffect(() => {
    let disposed = false;
    let reconnectTimer: number | undefined;
    let heartbeatTimer: number | undefined;
    let attempts = 0;
    const seen = new Set<string>();
    const clearTimers = () => { window.clearTimeout(reconnectTimer); window.clearInterval(heartbeatTimer); };
    function connect() {
      if (disposed) return;
      clearTimers();
      setConnectionState(attempts ? "reconnecting" : "connecting");
      const socket = new WebSocket(`${WS_BASE_URL}/ws/${encodeURIComponent(threadId)}`);
      socketRef.current = socket;
      let heartbeatAt = Date.now();
      socket.onopen = () => {
        if (disposed) return;
        attempts = 0;
        setConnectionState("connected");
        setLastError("");
        void restoreHistory().catch(() => {});
        heartbeatTimer = window.setInterval(() => {
          if (Date.now() - heartbeatAt > 60000) { socket.close(); return; }
          if (socket.readyState === WebSocket.OPEN) socket.send("ping");
        }, 25000);
      };
      socket.onmessage = (message) => {
        if (disposed || socketRef.current !== socket) return;
        try {
          const event = JSON.parse(message.data) as SocketMessage;
          heartbeatAt = Date.now();
          if (event.type === "pong") { setLastPongAt(new Date().toISOString()); return; }
          if (event.type === "session_deleted" && event.thread_id === currentThreadRef.current) {
            if (deletionRef.current !== event.thread_id) selectSession(createThreadId());
            setSessions((previous) => previous.filter((item) => item.thread_id !== event.thread_id));
            setSessionListRevision((previous) => previous + 1);
            return;
          }
          if (event.type !== "monitor_event" || event.thread_id !== threadId || !event.run_id) return;
          if (event.event_id && seen.has(event.event_id)) return;
          if (event.event_id) {
            seen.add(event.event_id);
            if (seen.size > 240) seen.delete(seen.values().next().value!);
          }
          if (event.replayed) setReplayedEventCount((previous) => previous + 1);
          setTurns((previous) => applyMonitorEvent(previous, event));
          if (terminalEvents.has(event.event)) void restoreHistory().catch(() => {});
        } catch {
          setLastError("收到无法解析的服务端消息，正在通过历史接口同步");
        }
      };
      socket.onerror = () => {
        if (!disposed) setLastError("实时连接暂不可用，聊天状态会通过历史接口同步");
      };
      socket.onclose = () => {
        clearTimers();
        if (disposed) return;
        setConnectionState("reconnecting");
        attempts += 1;
        const delay = Math.max(Math.min(1000 * 2 ** Math.min(attempts, 5), 30000) + Math.random() * 500, demoOfflineUntilRef.current - Date.now());
        reconnectTimer = window.setTimeout(connect, delay);
      };
    }
    setLastPongAt("");
    connect();
    return () => { disposed = true; clearTimers(); socketRef.current?.close(); };
  }, [threadId, restoreHistory, selectSession]);

  const deleteSession = useCallback(async (id: string) => {
    if (deletionRef.current || submitRef.current || uploadingRef.current || decisionRef.current) throw new Error("请等待当前操作完成再删除会话");
    deletionRef.current = id;
    setDeletingThreadId(id);
    try {
      await deleteSessionRequest(id);
      setSessions((previous) => previous.filter((item) => item.thread_id !== id));
      setSessionsError("");
      setSessionListRevision((previous) => previous + 1);
      deletionRef.current = null;
      if (currentThreadRef.current === id) selectSession(createThreadId());
    } finally {
      deletionRef.current = null;
      setDeletingThreadId(null);
    }
  }, [selectSession]);

  const refreshFiles = useCallback(async () => {
    if (!current) return;
    const epoch = epochRef.current;
    const response = await listSessionFiles(threadId, current.id);
    if (epoch !== epochRef.current) return;
    setTurns((previous) => previous.map((turn) => turn.id === current.id && response.revision >= turn.revision
      ? { ...turn, files: response.files || [] } : turn));
  }, [threadId, current?.id]);

  useEffect(() => {
    if (active?.status !== "running") return;
    const timer = window.setInterval(() => { void refreshFiles().catch(() => {}); }, 3000);
    return () => window.clearInterval(timer);
  }, [active?.status, refreshFiles]);

  const submitTask = useCallback(async (query: string) => {
    const clean = query.trim();
    if (!clean || active || submitRef.current || uploadingRef.current || deletionRef.current || historyLoading || historyError) throw new Error("请等待当前任务和会话同步完成");
    const runId = createThreadId();
    submitRef.current = runId;
    setIsSubmitting(true);
    setLastError("");
    setReplayedEventCount(0);
    setTurns((previous) => [...previous, { id: runId, revision: 0, status: "planning", content: clean,
      events: [], files: [], isRunning: true, result: "", timestamp: new Date().toISOString() }]);
    try {
      const response = await startTask(clean, threadId, runId);
      void restoreHistory().catch(() => {});
      return response;
    } catch (error) {
      // 受理成功但响应丢失时，用相同 run_id 在账本中确认，不能直接认定任务失败。
      if (!(error instanceof ApiError)) {
        try {
          const restored = await restoreHistory();
          const accepted = restored.turns.find((turn) => turn.id === runId);
          if (accepted) return { status: accepted.status, thread_id: threadId, run_id: runId };
        } catch { setHistoryError("任务受理状态尚未确认，连接恢复后会自动同步；请勿重复提交"); }
      }
      setTurns((previous) => previous.filter((turn) => turn.id !== runId || turn.revision > 0));
      void restoreHistory().catch(() => {});
      throw error;
    } finally {
      submitRef.current = null;
      setIsSubmitting(false);
    }
  }, [active, threadId, historyLoading, historyError, restoreHistory]);

  const decidePlan = useCallback(async (runId: string, version: number, action: PlanAction, feedback = "") => {
    if (decisionRef.current || deletionRef.current || historyLoading || historyError) throw new Error("请等待计划状态同步完成");
    decisionRef.current = true;
    setIsDeciding(true);
    try {
      await decideTaskPlan(threadId, runId, version, action, feedback);
      await restoreHistory();
    } catch (error) {
      try { await restoreHistory(); }
      catch { setHistoryError("计划操作状态尚未确认，请先同步历史；不要重复确认其他版本"); }
      throw error;
    } finally {
      decisionRef.current = false;
      setIsDeciding(false);
    }
  }, [threadId, historyLoading, historyError, restoreHistory]);

  const cancelCurrentTask = useCallback(async () => {
    if (!active) throw new Error("当前没有正在执行的任务");
    const response = await cancelTask(threadId, active.id);
    if (currentThreadRef.current === threadId) {
      setTurns((previous) => previous.map((turn) => turn.id === active.id && turn.isRunning ? { ...turn, status: "cancelling" } : turn));
      await restoreHistory();
    }
    return response;
  }, [active, threadId, restoreHistory]);

  const uploadFiles = useCallback(async (items: UploadedItem[]) => {
    if (active || submitRef.current || uploadingRef.current || deletionRef.current || historyLoading || historyError) throw new Error("请等待任务和会话同步完成后上传");
    const names = new Set(uploadedItems.map((item) => item.name.toLocaleLowerCase()));
    const next = items.filter((item) => item.raw && !names.has(item.name.toLocaleLowerCase()));
    if (!next.length) throw new Error("请选择新的附件，同名附件已存在");
    uploadingRef.current = true;
    setIsUploading(true);
    try {
      const response = await uploadSessionFiles(next.map((item) => item.raw!), threadId);
      setUploadedItems((previous) => [...previous, ...next]);
      return response;
    } finally {
      uploadingRef.current = false;
      setIsUploading(false);
      void restoreHistory().catch(() => {});
    }
  }, [active, threadId, uploadedItems, historyLoading, historyError, restoreHistory]);

  const stats = useMemo(() => ({ toolEvents: current?.usage?.tool ?? events.filter((event) => event.event === "tool_start").length,
    assistantEvents: current?.usage?.delegate ?? events.filter((event) => event.event === "assistant_call").length,
    modelCalls: current?.usage?.model ?? events.filter((event) => event.event === "model_start").length,
    modelBudget: current?.budget?.model,
    errorEvents: events.filter((event) => event.event === "error").length, fileCount: files.length }), [events, files.length, current?.usage, current?.budget]);

  const simulateWebSocketDrop = useCallback(() => {
    if (!import.meta.env.DEV) return;
    demoOfflineUntilRef.current = Date.now() + 8000;
    socketRef.current?.close(4000, "模拟断线");
  }, []);

  return { threadId, turns, events, files, connectionState, historyLoading, historyError, lastError,
    isRunning, isCancelling, isSubmitting, isUploading, isDeciding, decidePlan, uploadedItems, replayedEventCount, lastPongAt,
    sessionPath: typeof sessionPath === "string" ? sessionPath : "", stats, sessions, sessionsError, deletingThreadId, deleteSession,
    sessionQuery, setSessionQuery, selectSession, restoreHistory, submitTask, cancelCurrentTask, uploadFiles,
    refreshFiles, resetSession: () => selectSession(createThreadId()), simulateWebSocketDrop };
}
