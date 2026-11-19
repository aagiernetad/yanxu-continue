export type ConnectionState = "connecting" | "connected" | "reconnecting" | "closed";

export type MonitorEventName =
  | "session_created"
  | "tool_start"
  | "assistant_call"
  | "task_result"
  | "task_cancelled"
  | "error"
  | string;

export interface MonitorMessage {
  type: "monitor_event";
  event: MonitorEventName;
  message: string;
  data: Record<string, unknown>;
  timestamp: string;
  thread_id: string;
  run_id: string;
  revision: number;
  event_id?: string;
  replayed?: boolean;
}

export interface PongMessage {
  type: "pong";
  message: string;
}

export interface SessionDeletedMessage {
  type: "session_deleted";
  thread_id: string;
}

export type SocketMessage = MonitorMessage | PongMessage | SessionDeletedMessage;

export interface TaskResponse {
  status: "started" | string;
  thread_id: string;
  run_id: string;
}

export type PlanAction = "approve" | "revise";

export interface CancelTaskResponse {
  status: "cancelled" | "cancelling" | string;
  thread_id: string;
  run_id: string;
  message?: string;
}

export interface UploadResponse {
  status: "uploaded" | string;
  files: string[];
}

export interface OutputFile {
  name: string;
  type: "file" | string;
  path: string;
  thread_id: string;
  run_id: string;
  size: number;
  mtime: number;
}

export interface FileListResponse {
  revision: number;
  files?: OutputFile[];
  error?: string;
}

export interface UploadedItem {
  uid: string;
  name: string;
  size: number;
  raw?: File;
}

export interface SessionSummary {
  thread_id: string;
  title: string;
  updated_at: string;
  is_running: boolean;
  can_delete: boolean;
}

export interface KnowledgeDocument {
  id: string;
  source: string;
  chunk_count: number;
  page_count: number;
}

export interface KnowledgeDocumentsResponse {
  documents: KnowledgeDocument[];
  total_documents: number;
  total_chunks: number;
}

export interface KnowledgeChunksResponse {
  document_id: string;
  source: string;
  total: number;
  offset: number;
  limit: number;
  chunks: {
    id: string;
    text: string;
    page: number | null;
    start_char: number | null;
    end_char: number | null;
  }[];
}
