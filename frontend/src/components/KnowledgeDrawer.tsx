import { FileTextOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Drawer, Empty, Input, Pagination, Spin } from "antd";
import { useEffect, useState } from "react";
import { getKnowledgeChunks, listKnowledgeDocuments } from "../lib/api";
import type { KnowledgeChunksResponse, KnowledgeDocumentsResponse } from "../types";

const PAGE_SIZE = 20;

export function KnowledgeDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [library, setLibrary] = useState<KnowledgeDocumentsResponse | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [query, setQuery] = useState("");
  const [offset, setOffset] = useState(0);
  const [preview, setPreview] = useState<KnowledgeChunksResponse | null>(null);
  const [loadingDocuments, setLoadingDocuments] = useState(false);
  const [loadingChunks, setLoadingChunks] = useState(false);
  const [documentsError, setDocumentsError] = useState("");
  const [chunksError, setChunksError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const selected = library?.documents.find((item) => item.id === selectedId);
  const documents = library?.documents.filter((item) => item.source.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())) || [];
  const currentPreview = preview?.document_id === selectedId && preview.offset === offset ? preview : null;

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoadingDocuments(true);
    setDocumentsError("");
    listKnowledgeDocuments(controller.signal).then((response) => {
      if (controller.signal.aborted) return;
      setLibrary(response);
      setSelectedId((previous) => response.documents.some((item) => item.id === previous) ? previous : "");
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setDocumentsError(error instanceof Error ? error.message : "知识库加载失败");
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingDocuments(false);
    });
    return () => controller.abort();
  }, [open, refresh]);

  useEffect(() => {
    if (!open || !selectedId) return;
    const controller = new AbortController();
    setLoadingChunks(true);
    setChunksError("");
    getKnowledgeChunks(selectedId, offset, PAGE_SIZE, controller.signal).then((response) => {
      if (!controller.signal.aborted) setPreview(response);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setChunksError(error instanceof Error ? error.message : "文档内容加载失败");
    }).finally(() => {
      if (!controller.signal.aborted) setLoadingChunks(false);
    });
    return () => controller.abort();
  }, [open, selectedId, offset, refresh]);

  function selectDocument(id: string) {
    setSelectedId(id);
    setOffset(0);
    setChunksError("");
  }

  return (
    <Drawer
      title="知识库"
      open={open}
      onClose={onClose}
      width="min(960px, 100vw)"
      className="knowledge-drawer"
      extra={<Button type="text" icon={<ReloadOutlined />} aria-label="刷新知识库" onClick={() => setRefresh((value) => value + 1)} loading={loadingDocuments}>刷新</Button>}
    >
      <div className="knowledge-summary">
        <span>浏览已收录的文档与原文片段</span>
        {library ? <strong>{library.total_documents} 份文档 · {library.total_chunks} 段原文</strong> : null}
      </div>
      {documentsError ? <Alert className="knowledge-error" type="error" showIcon message={documentsError} action={<Button size="small" onClick={() => setRefresh((value) => value + 1)}>重试</Button>} /> : null}
      {loadingDocuments && !library ? (
        <div className="knowledge-placeholder"><Spin tip="正在读取知识库…"><div /></Spin></div>
      ) : !library?.documents.length ? (
        !documentsError ? <div className="knowledge-placeholder"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="知识库暂无文档，导入资料后可在这里浏览" /></div> : null
      ) : (
        <div className="knowledge-layout">
          <nav className="knowledge-documents" aria-label="知识库文档">
            <Input.Search allowClear placeholder="按文档名称筛选" aria-label="筛选知识库文档" value={query} onChange={(event) => setQuery(event.target.value)} />
            <ul className="knowledge-document-list">
              {documents.map((document) => (
                <li key={document.id}>
                  <button type="button" aria-current={document.id === selectedId ? "true" : undefined} onClick={() => selectDocument(document.id)} title={document.source}>
                    <FileTextOutlined aria-hidden />
                    <span><strong>{document.source}</strong><small>{document.chunk_count} 段原文{document.page_count ? ` · ${document.page_count} 页已收录` : ""}</small></span>
                  </button>
                </li>
              ))}
            </ul>
            {!documents.length ? <p className="knowledge-filter-empty">没有匹配的文档</p> : null}
          </nav>
          <section className="knowledge-preview" aria-label="文档原文片段" aria-busy={loadingChunks}>
            {!selected ? <div className="knowledge-placeholder"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="选择一份文档，查看已收录的原文片段" /></div> : (
              <>
                <div className="knowledge-preview-heading"><h2>{selected.source}</h2><span>共 {selected.chunk_count} 段原文</span></div>
                <p className="knowledge-preview-note">以下为知识库保存的文本片段，相邻片段可能包含重复内容。</p>
                {chunksError ? <Alert type="error" showIcon message={chunksError} action={<Button size="small" onClick={() => setRefresh((value) => value + 1)}>重试</Button>} /> : loadingChunks ? (
                  <div className="knowledge-placeholder"><Spin tip="正在读取原文…"><div /></Spin></div>
                ) : currentPreview ? (
                  <>
                    <ol className="knowledge-chunks" start={offset + 1}>
                      {currentPreview.chunks.map((chunk, index) => (
                        <li key={chunk.id}>
                          <article className="knowledge-chunk">
                            <div className="knowledge-chunk-meta"><span>片段 {offset + index + 1}</span><span>{chunk.page === null ? "未记录页码" : `第 ${chunk.page} 页`}</span></div>
                            <p>{chunk.text}</p>
                          </article>
                        </li>
                      ))}
                    </ol>
                    {!currentPreview.chunks.length ? <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="此页没有原文片段，请刷新知识库" /> : null}
                    <Pagination
                      size="small"
                      current={Math.floor(offset / PAGE_SIZE) + 1}
                      pageSize={PAGE_SIZE}
                      total={currentPreview.total}
                      showSizeChanger={false}
                      hideOnSinglePage
                      showTotal={(total) => `共 ${total} 段`}
                      onChange={(page) => setOffset((page - 1) * PAGE_SIZE)}
                    />
                  </>
                ) : null}
              </>
            )}
          </section>
        </div>
      )}
    </Drawer>
  );
}
