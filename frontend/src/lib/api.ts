import { API_BASE_URL } from "./config";
import type { CancelTaskResponse, FileListResponse, KnowledgeChunksResponse, KnowledgeDocumentsResponse, OutputFile, PlanAction, SessionSummary, TaskResponse, UploadResponse } from "../types";
import type { ChatTurn } from "../components/ConversationThread";

function apiUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
  }
}

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, { ...init, signal: init?.signal || AbortSignal.timeout(20000) });
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof payload === "object" && payload && "detail" in payload ? payload.detail : null;
    throw new ApiError(typeof detail === "string" ? detail : `请求失败（HTTP ${response.status}）`, response.status);
  }
  return payload as T;
}

export async function startTask(query: string, threadId: string, runId: string): Promise<TaskResponse> {
  const init = {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, thread_id: threadId, run_id: runId })
  };
  try {
    return await requestJson<TaskResponse>(apiUrl("/api/task"), init);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // 响应丢失时只重试同一个 run_id，不创建第二个任务。
    return requestJson<TaskResponse>(apiUrl("/api/task"), init);
  }
}

export interface SessionHistoryResponse {
  thread_id: string;
  turns: ChatTurn[];
  is_running: boolean;
  active_run_id: string | null;
  uploads: { name: string; size: number }[];
}

export async function decideTaskPlan(threadId: string, runId: string, planVersion: number, action: PlanAction, feedback: string): Promise<TaskResponse> {
  const url = apiUrl(`/api/task/${encodeURIComponent(threadId)}/plan`);
  const init = { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_id: runId, plan_version: planVersion, action, feedback }) };
  try {
    return await requestJson<TaskResponse>(url, init);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    // 相同版本与修改意见可安全重试，不能改用当前的新版本再次执行。
    return requestJson<TaskResponse>(url, init);
  }
}

export function getSessionHistory(threadId: string): Promise<SessionHistoryResponse> {
  return requestJson(apiUrl(`/api/sessions/${encodeURIComponent(threadId)}`));
}

export function listSessions(query: string, signal?: AbortSignal): Promise<{ sessions: SessionSummary[] }> {
  return requestJson(apiUrl(`/api/sessions?q=${encodeURIComponent(query)}`), { signal });
}

export function deleteSession(threadId: string): Promise<{ status: "deleted"; thread_id: string }> {
  return requestJson(apiUrl(`/api/sessions/${encodeURIComponent(threadId)}`), { method: "DELETE" });
}

export function listKnowledgeDocuments(signal?: AbortSignal): Promise<KnowledgeDocumentsResponse> {
  return requestJson(apiUrl("/api/knowledge/documents"), { signal });
}

export function getKnowledgeChunks(documentId: string, offset: number, limit = 20, signal?: AbortSignal): Promise<KnowledgeChunksResponse> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  return requestJson(apiUrl(`/api/knowledge/documents/${encodeURIComponent(documentId)}/chunks?${params}`), { signal });
}

export function cancelTask(threadId: string, runId: string): Promise<CancelTaskResponse> {
  return requestJson(apiUrl(`/api/task/${encodeURIComponent(threadId)}/cancel?run_id=${encodeURIComponent(runId)}`), { method: "POST" });
}

export function uploadSessionFiles(files: File[], threadId: string): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("thread_id", threadId);
  files.forEach((file) => formData.append("files", file));
  return requestJson(apiUrl("/api/upload"), { method: "POST", body: formData, signal: AbortSignal.timeout(120000) });
}

export function listSessionFiles(threadId: string, runId: string): Promise<FileListResponse> {
  return requestJson(apiUrl(`/api/files?thread_id=${encodeURIComponent(threadId)}&run_id=${encodeURIComponent(runId)}`));
}

export function getDownloadUrl(file: OutputFile): string {
  const url = new URL(apiUrl("/api/download"));
  url.searchParams.set("thread_id", file.thread_id);
  url.searchParams.set("run_id", file.run_id);
  url.searchParams.set("path", file.path);
  return url.toString();
}
