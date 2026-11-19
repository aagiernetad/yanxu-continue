
import {
  BranchesOutlined,
  CheckCircleOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import { Button } from "antd";
import { useEffect, useState } from "react";
// 定义组件接收哪些 Props
interface ChatHeaderProps {
  sidebarOpen: boolean;
  isRunning: boolean;
  phase?: string;
  startedAt?: string;
  finishedAt?: string;
  onToggleSidebar: () => void;
}

// 定义 ChatHeader 组件
export function ChatHeader({
  sidebarOpen,
  isRunning,
  phase,
  startedAt,
  finishedAt,
  onToggleSidebar
}: ChatHeaderProps) {
  const [now, setNow] = useState(Date.now());

  // 监听任务运行状态
  useEffect(() => {
    if (!isRunning || phase === "waiting_approval") {
      return;
    }

    const timer = window.setInterval(() => setNow(Date.now()), 1000);

    // 任务停止或组件卸载时清理定时器
    return () => {
      window.clearInterval(timer);
    };
  }, [isRunning, startedAt, phase]);

  // 使用后端轮次时间，刷新和切换历史后不会沿用上一个任务的秒表。
  const start = startedAt ? Date.parse(startedAt) : now;
  const end = finishedAt ? Date.parse(finishedAt) : isRunning ? now : start;
  const elapsedSeconds = Number.isFinite(start) && Number.isFinite(end) ? Math.max(0, Math.floor((end - start) / 1000)) : 0;

  // 将秒数格式化为 MM:SS
  const minutes = String(
    Math.floor(elapsedSeconds / 60)
  ).padStart(2, "0");

  const seconds = String(
    elapsedSeconds % 60
  ).padStart(2, "0");

  const elapsedTime = `${minutes}:${seconds}`;


  return (
    <header className="chat-topbar">
      <div className="chat-topbar-left">
        <Button
          className="sidebar-toggle"
          type="text"
          icon={
            sidebarOpen
              ? <MenuFoldOutlined />
              : <MenuUnfoldOutlined />
          }
          aria-label={sidebarOpen ? "收起侧栏" : "展开侧栏"}
          aria-expanded={sidebarOpen}
          aria-controls="chat-sidebar"
          onClick={onToggleSidebar}
        />

        <div>
          <h2>研究对话</h2>
        </div>
      </div>

      <div
        className={`run-indicator ${isRunning ? "run-indicator--live" : ""
          }`}
      >
        {isRunning
          ? <BranchesOutlined aria-hidden />
          : <CheckCircleOutlined aria-hidden />
        }
        {isRunning
          ? phase === "waiting_approval" ? "等待确认计划" : `${phase === "planning" ? "生成计划" : phase === "cancelling" ? "正在取消" : "执行中"} · ${elapsedTime}`
          : startedAt
            ? `已结束 · ${elapsedTime}`
            : "准备就绪"}
      </div>
    </header>
  );
}
