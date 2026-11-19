import {
  PaperClipOutlined,
  PlusOutlined,
  ArrowUpOutlined,
  StopOutlined
} from "@ant-design/icons";
import { Button, Input, Tooltip, Upload } from "antd";
import type { UploadFile } from "antd";
import type { UploadedItem } from "../types";

interface ChatComposerProps {
  isUnavailable?: boolean;
  isCancelling: boolean;
  isRunning: boolean;
  isUploading: boolean;
  onCancel: () => void;
  onQueryChange: (value: string) => void;
  onSubmit: () => void;
  onUpload: (items: UploadedItem[]) => Promise<void> | void;
  query: string;
  stagedItems: UploadedItem[];
  uploadedItems: UploadedItem[];
  onStagedItemsChange: (items: UploadedItem[]) => void;
}

function toUploadedItem(file: UploadFile): UploadedItem | null {
  if (!file.originFileObj) {
    return null;
  }

  return {
    uid: file.uid,
    name: file.name,
    size: file.size || 0,
    raw: file.originFileObj
  };
}

function uniqueUploadedItems(items: UploadedItem[]): UploadedItem[] {
  const names = new Set<string>();
  return items.filter((item) => {
    if (names.has(item.name)) {
      return false;
    }
    names.add(item.name);
    return true;
  });
}

export function ChatComposer({
  isUnavailable = false,
  isCancelling,
  isRunning,
  isUploading,
  onCancel,
  onQueryChange,
  onStagedItemsChange,
  onSubmit,
  onUpload,
  query,
  stagedItems,
  uploadedItems
}: ChatComposerProps) {
  const hasStagedFiles = stagedItems.length > 0;
  const canSubmit = query.trim().length > 0 && !isUploading && !isUnavailable;

  function handleAttachmentChange(fileList: UploadFile[]) {
    const nextItems = uniqueUploadedItems(
      fileList
        .map(toUploadedItem)
        .filter((item): item is UploadedItem => Boolean(item))
    );

    if (nextItems.length === 0) {
      return;
    }

    onStagedItemsChange(nextItems);
    void Promise.resolve(onUpload(nextItems)).finally(() => {
      onStagedItemsChange([]);
    });
  }

  return (
    <section className="chat-composer" aria-label="发送研搜任务">
      {uploadedItems.length > 0 ? (
        <div className="attachment-strip" aria-label="当前会话附件">
          {uploadedItems.map((item) => (
            <span className="attachment-pill" key={`${item.uid}-${item.name}`}>
              <PaperClipOutlined aria-hidden />
              {item.name}
            </span>
          ))}
        </div>
      ) : null}

      {hasStagedFiles ? (
        <div className="attachment-strip" aria-label="待上传附件">
          {stagedItems.map((item) => (
            <span className="attachment-pill attachment-pill--pending" key={item.uid}>
              <PaperClipOutlined aria-hidden />
              {item.name}
            </span>
          ))}
          {isUploading ? <span className="attachment-uploading">上传中…</span> : null}
        </div>
      ) : null}

      <div className="composer-shell">
        <Input.TextArea
          id="research-query"
          aria-label="研搜任务"
          aria-describedby="composer-hint"
          autoSize={{ minRows: 2, maxRows: 6 }}
          disabled={isRunning || isUnavailable}
          onChange={(event) => onQueryChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing || event.keyCode === 229) return;
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (canSubmit && !isRunning) onSubmit();
            }
          }}
          placeholder="向 DeepSearch 提问…"
          value={query}
        />

        <div className="composer-toolbar">
          <div className="composer-left-actions">
            <Upload
              beforeUpload={() => false}
              disabled={isRunning || isUploading || isUnavailable}
              fileList={[]}
              multiple
              onChange={(info) => {
                handleAttachmentChange(info.fileList.length > 0 ? info.fileList : [info.file]);
              }}
              showUploadList={false}
            >
              <Tooltip title="添加附件">
                <Button
                  aria-label="添加附件"
                  className="composer-icon-button"
                  disabled={isRunning || isUploading || isUnavailable}
                  icon={<PlusOutlined />}
                  shape="circle"
                />
              </Tooltip>
            </Upload>
          </div>

          <div className="composer-right-actions">
            <Tooltip title={isRunning ? "取消当前任务" : "发送任务"}>
              <Button
                aria-label={isRunning ? "取消当前任务" : "发送任务"}
                className={isRunning ? "send-button send-button--cancel" : "send-button"}
                disabled={isRunning ? isCancelling || isUnavailable : !canSubmit}
                icon={isRunning ? <StopOutlined /> : <ArrowUpOutlined />}
                loading={isCancelling}
                onClick={isRunning ? onCancel : onSubmit}
                shape="circle"
                type="primary"
              />
            </Tooltip>
          </div>
        </div>
      </div>
      <p className="composer-hint" id="composer-hint">
        <span>Enter 发送 · Shift + Enter 换行</span>
      </p>
    </section>
  );
}
