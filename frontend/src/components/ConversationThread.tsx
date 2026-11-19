import {
  BranchesOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  DownloadOutlined,
  FileMarkdownOutlined,
  FilePdfOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  StopOutlined,
  ToolOutlined,
  ExperimentOutlined,
} from "@ant-design/icons";
import { Button, Input, Tooltip } from "antd";
import { useEffect, useRef, useState } from "react";
import { getDownloadUrl } from "../lib/api";
import { MarkdownRenderer } from "./MarkdownRenderer";
import type { MonitorMessage, OutputFile, PlanAction } from "../types";

export interface ChatTurn {
  id: string;
  revision: number;
  status: "planning" | "waiting_approval" | "running" | "cancelling" | "completed" | "cancelled" | "failed";
  content: string;
  events: MonitorMessage[];
  files: OutputFile[];
  isRunning: boolean;
  result: string;
  timestamp: string;
  plan?: string;
  planVersion?: number;
  usage?: Record<string, number>;
  budget?: Record<string, number>;
}

interface ConversationThreadProps {
  turns: ChatTurn[];
  isDeciding?: boolean;
  onPlanDecision?: (runId: string, version: number, action: PlanAction, feedback?: string) => Promise<void>;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "--:--";
  }
  return date.toLocaleTimeString("zh-CN", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function parseTime(value: string): number | null {
  const time = new Date(value).getTime();
  return Number.isNaN(time) ? null : time;
}

function formatDuration(value: number): string {
  const totalSeconds = Math.max(0, Math.floor(value / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const paddedMinutes = String(minutes).padStart(2, "0");
  const paddedSeconds = String(seconds).padStart(2, "0");

  if (hours > 0) {
    return `${hours}:${paddedMinutes}:${paddedSeconds}`;
  }
  return `${paddedMinutes}:${paddedSeconds}`;
}

function getLastEventTime(
  events: MonitorMessage[],
  eventName?: string,
): number | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index];
    if (!eventName || event.event === eventName) {
      return parseTime(event.timestamp);
    }
  }
  return null;
}

function getThinkingDuration(
  events: MonitorMessage[],
  fallbackStart: string,
  isRunning: boolean,
  now: number,
): string {
  const startedAt =
    (events[0] ? parseTime(events[0].timestamp) : null) ??
    parseTime(fallbackStart) ??
    now;
  const finishedAt =
    getLastEventTime(events, "task_result") ??
    (!isRunning ? getLastEventTime(events) : null) ??
    now;
  return formatDuration(finishedAt - startedAt);
}

function EventIcon({ event }: { event: string }) {
  if (event === "task_accepted") {
    return <CheckCircleOutlined aria-hidden />;
  }

  if (event === "assistant_call") {
    return <BranchesOutlined aria-hidden />;
  }
  if (event === "tool_start") {
    return <ToolOutlined aria-hidden />;
  }
  if (event === "session_created") {
    return <FileSearchOutlined aria-hidden />;
  }
  if (event === "task_result") {
    return <CheckCircleOutlined aria-hidden />;
  }
  if (event === "task_cancelled") {
    return <StopOutlined aria-hidden />;
  }
  if (event === "error") {
    return <CloseCircleOutlined aria-hidden />;
  }
  return <ClockCircleOutlined aria-hidden />;
}

function getEventLabel(event: string): string {
  const labels: Record<string, string> = {
    task_accepted: "研究任务已受理",
    plan_ready: "计划已生成，等待确认",
    plan_approved: "计划已确认，开始执行",
    model_start: "模型调用开始",
    model_end: "模型调用结束",
    tool_end: "工具调用结束",
    search_budget_exhausted: "搜索已达上限，正在整理资料",
    session_created: "研究空间已准备",
    assistant_call: "正在分配研究任务",
    tool_start: "正在调用研究工具",
    task_result: "研究结果已生成",
    task_cancelled: "研究已取消",
    error: "研究遇到问题"
  };
  return labels[event] || event;
}

function FileIcon({ name }: { name: string }) {
  if (name.endsWith(".pdf")) {
    return <FilePdfOutlined aria-hidden />;
  }
  if (name.endsWith(".md")) {
    return <FileMarkdownOutlined aria-hidden />;
  }
  return <FileTextOutlined aria-hidden />;
}

function ThinkingTimeline({ events }: { events: MonitorMessage[] }) {
  const timelineRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    const timelineNode = timelineRef.current;
    if (!timelineNode) {
      return;
    }

    window.requestAnimationFrame(() => {
      timelineNode.scrollTop = timelineNode.scrollHeight;
    });
  }, [events.length]);

  if (events.length === 0) {
    return (
      <div className="thinking-empty">
        <ClockCircleOutlined aria-hidden />
        等待后端推送执行事件
      </div>
    );
  }

  return (
    <ol className="thinking-timeline" ref={timelineRef}>
      {events.map((event, index) => (
        <li
          className={`thinking-event thinking-event--${event.event}`}
          key={`${event.timestamp}-${index}`}
        >
          <span className="thinking-event-icon">
            <EventIcon event={event.event} />
          </span>
          <div>
            <div className="thinking-event-meta">
              <span>{getEventLabel(event.event)}</span>
              <time dateTime={event.timestamp}>
                {formatTime(event.timestamp)}
              </time>
            </div>
            <p>{event.message}</p>
            {event.event === "assistant_call" ||
              event.event === "tool_start" ? (
              <code>{JSON.stringify(event.data)}</code>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}

function ArtifactShelf({ files }: { files: OutputFile[] }) {
  if (files.length === 0) {
    return (
      <div className="artifact-empty">
        <FileSearchOutlined aria-hidden />
        暂无输出文件
      </div>
    );
  }

  return (
    <div className="artifact-shelf">
      {files.map((file) => (
        <div className="artifact-card" key={file.path}>
          <span className="artifact-icon">
            <FileIcon name={file.name} />
          </span>
          <div className="artifact-copy">
            <strong title={file.name}>{file.name}</strong>
            <span>{formatBytes(file.size)}</span>
          </div>
          <Tooltip title="下载">
            <Button
              aria-label={`下载 ${file.name}`}
              className="artifact-download"
              href={getDownloadUrl(file)}
              icon={<DownloadOutlined />}
              shape="circle"
            />
          </Tooltip>
        </div>
      ))}
    </div>
  );
}

function ThinkingLoader({ durationLabel, phaseLabel, planning }: { durationLabel: string; phaseLabel: string; planning: boolean }) {
  return (
    <div
      className="thinking-loader"
      aria-live="polite"
      aria-label="正在生成回复"
    >
      <div className="loader-status">
        <span className="loader-pulse" aria-hidden />
        <strong>{phaseLabel}</strong>
        <span className="loader-duration">已思考 {durationLabel}</span>
        <span className="loader-dots" aria-hidden>
          <i />
          <i />
          <i />
        </span>
      </div>
      <div className="loader-track" aria-hidden />
      <ul className="loader-steps" aria-hidden>
        {planning ? <><li>理解问题</li><li>整理步骤</li><li>等待你的确认</li></>
          : <><li>理解问题</li><li>调度工具</li><li>汇总答案</li></>}
      </ul>
    </div>
  );
}

function PlanCard({ turn, isDeciding, onPlanDecision }: { turn: ChatTurn } & Omit<ConversationThreadProps, "turns">) {
  const [editing, setEditing] = useState(false);
  const [feedback, setFeedback] = useState("");
  const [error, setError] = useState("");
  const waiting = turn.status === "waiting_approval";
  useEffect(() => { setEditing(false); setFeedback(""); setError(""); }, [turn.planVersion]);
  async function decide(action: PlanAction) {
    if (!onPlanDecision || !turn.planVersion) return;
    setError("");
    try { await onPlanDecision(turn.id, turn.planVersion, action, feedback.trim()); }
    catch (failure) { setError(failure instanceof Error ? failure.message : "计划操作失败，请重试"); }
  }
  return (
    <details className="plan-card" open={waiting}>
      <summary>{waiting ? `研究计划 · 第 ${turn.planVersion} 版` : "查看已生成的研究计划"}</summary>
      <div className="plan-card-body">
        <MarkdownRenderer content={turn.plan || ""} />
        {waiting && <p className="plan-note">确认后开始检索、读取资料与生成报告。也可以先提出修改意见。</p>}
        {waiting && onPlanDecision && <div className="plan-actions">
          <Button type="primary" disabled={isDeciding || editing} loading={isDeciding && !editing} onClick={() => void decide("approve")}>确认并执行</Button>
          <Button disabled={isDeciding} onClick={() => setEditing((value) => !value)}>{editing ? "收起修改" : "修改计划"}</Button>
        </div>}
        {waiting && editing && <div className="plan-feedback">
          <Input.TextArea aria-label="计划修改意见" placeholder="例如：先比较近两年资料，暂不生成 PDF。" maxLength={4000} autoSize={{ minRows: 3, maxRows: 8 }} value={feedback} disabled={isDeciding} onChange={(event) => setFeedback(event.target.value)} />
          <Button disabled={isDeciding || !feedback.trim()} loading={isDeciding} onClick={() => void decide("revise")}>提交修改</Button>
        </div>}
        {error && <p className="plan-error" role="alert">{error}</p>}
      </div>
    </details>
  );
}

function AssistantMessage({
  turn, isDeciding, onPlanDecision,
}: { turn: ChatTurn } & Omit<ConversationThreadProps, "turns">) {
  const { events, files, isRunning, result, timestamp, status } = turn;
  const waiting = status === "waiting_approval";
  const planning = status === "planning";
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (!isRunning || waiting) {
      return;
    }

    const timer = window.setInterval(() => {
      setNow(Date.now());
    }, 1000);

    return () => window.clearInterval(timer);
  }, [isRunning, waiting]);

  const durationLabel = getThinkingDuration(events, timestamp, isRunning, now);
  const isCancelled = events.some((event) => event.event === "task_cancelled");
  const hasError = events.some((event) => event.event === "error");
  const hasResult = events.some((event) => event.event === "task_result");
  const phaseLabel = events.length > 0 ? getEventLabel(events[events.length - 1].event) : "正在理解研究问题";
  const syncLabel = waiting ? "等待你确认计划" : isRunning
    ? `${planning ? "生成计划中" : "执行中"} · ${durationLabel}`
    : `${isCancelled ? "已取消" : hasError ? "研究异常" : hasResult ? "研究完成" : "已结束"} · 用时 ${durationLabel}`;

  return (
    <article className="chat-message chat-message--assistant">
      <div className="message-avatar">AI</div>
      <div className="message-bubble">
        <div className="message-meta">
          <span>DeepSearch Agents</span>
          <time>{syncLabel}</time>
        </div>

        <details
          className="thinking-block"
          open={(isRunning && !waiting) || hasError}
        >
          <summary>
            <span>
              <BranchesOutlined aria-hidden />
              {waiting ? "查看规划过程" : isRunning ? "查看当前过程" : "查看研究过程"}
            </span>
            <strong>{events.length}</strong>
          </summary>
          <ThinkingTimeline events={events} />
        </details>

        {turn.plan && !planning && <PlanCard turn={turn} isDeciding={isDeciding} onPlanDecision={onPlanDecision} />}

        {result ? (
          <div className="assistant-answer">
            <MarkdownRenderer content={result} />
          </div>
        ) : (
          <div className="assistant-answer assistant-answer--pending">
            {waiting ? "计划尚未执行。请确认、修改计划，或在输入框右侧取消任务。" : isRunning ? (
              <ThinkingLoader durationLabel={durationLabel} phaseLabel={planning ? "正在生成研究计划" : phaseLabel} planning={planning} />
            ) : (
              isCancelled ? "本次研究已取消，可以调整问题后重新开始。" : "本次研究已结束，暂未返回正文，可展开研究过程查看详情。"
            )}
          </div>
        )}

        {(files.length > 0 || (!planning && !waiting)) && <details
          className="thinking-block artifact-block"
          open={files.length > 0}
        >
          <summary>
            <span>
              <FileSearchOutlined aria-hidden />
              输出文件
            </span>
            <strong>{files.length}</strong>
          </summary>
          <ArtifactShelf files={files} />
        </details>}
      </div>
    </article>
  );
}

export function ConversationThread({
  turns,
  isDeciding,
  onPlanDecision,
}: ConversationThreadProps) {
  if (turns.length === 0) {
    return (
      <div className="conversation-empty">
        <div className="welcome-copy">
          <span className="welcome-symbol"><ExperimentOutlined aria-hidden /></span>
          <h3>今天，想探索什么？</h3>
          <p>从一个问题，或一份资料开始。</p>
        </div>
      </div>
    );
  }

  return (
    <div className="conversation-thread" aria-label="聊天消息流">
      {turns.map((turn) => (
        <div className="conversation-turn" id={`turn-${turn.id}`} tabIndex={-1} key={turn.id}>
          <article className="chat-message chat-message--user">
            <div className="message-bubble">
              <div className="message-meta">
                <span>你</span>
                <time dateTime={turn.timestamp}>
                  {formatTime(turn.timestamp)}
                </time>
              </div>
              <p>{turn.content}</p>
            </div>
          </article>
          <AssistantMessage
            turn={turn}
            isDeciding={isDeciding}
            onPlanDecision={onPlanDecision}
          />
        </div>
      ))}
    </div>
  );
}
