import { useCallback, useEffect, useRef, useState } from "react";

import apiClient from "../api/client";
import { getFriendlyErrorMessage } from "../utils/errorMessage";
import useBackgroundJob from "../hooks/useBackgroundJob";
import BackgroundJobCard from "../components/BackgroundJobCard";
import { formatDateTime } from "../utils/format";

const MAX_FILE_BYTES = 20 * 1024 * 1024;
const statusLabels = { uploaded: "待索引", indexed: "已索引", failed: "索引失败", processing: "处理中" };

function KnowledgeBase() {
  const [files, setFiles] = useState([]);
  const [knowledgeStatus, setKnowledgeStatus] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState("other");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [dragActive, setDragActive] = useState(false);
  const [query, setQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const fileInputRef = useRef(null);

  const fetchFiles = useCallback(async () => {
    try {
      setLoading(true);
      const response = await apiClient.get("/api/files");
      setFiles(response.data.files || []);
    } catch (error) {
      console.error("fetch files error:", error);

      setMessage(getFriendlyErrorMessage(error, "获取文件列表失败。"));
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchKnowledgeStatus = useCallback(async () => {
    try {
      setLoading(true);
      setMessage("正在刷新知识库状态...");

      const response = await apiClient.get("/api/knowledge/status");

      setKnowledgeStatus(response.data);
      setMessage("知识库状态刷新成功。");
    } catch (error) {
      console.error("fetch knowledge status error:", error);

      setMessage(getFriendlyErrorMessage(error, "获取知识库状态失败。"));
    } finally {
      setLoading(false);
    }
  }, []);

  const refreshAll = useCallback(async () => {
    await fetchFiles();
    await fetchKnowledgeStatus();
  }, [fetchFiles, fetchKnowledgeStatus]);

  const { job, createJob, cancelJob, isRunning } = useBackgroundJob(
    "knowledge-rebuild",
    async (result) => {
      setMessage(
        `知识库索引重建完成。当前向量片段数：${result.total_chunks || 0}`,
      );
      await refreshAll();
    },
  );
  const busy = loading || isRunning;

  useEffect(() => {
    const timerId = window.setTimeout(refreshAll, 0);

    return () => window.clearTimeout(timerId);
  }, [refreshAll]);

  const selectFile = (file) => {
    if (!file) {
      setSelectedFile(null);
      return;
    }
    const extension = file.name.toLowerCase().slice(file.name.lastIndexOf("."));
    if (![".md", ".txt", ".pdf"].includes(extension)) {
      setSelectedFile(null);
      setMessage("文件类型不受支持。仅可上传 PDF、TXT 或 MD。");
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setSelectedFile(null);
      setMessage("文件超过 20 MB 单文件上限，请压缩或拆分后重试。");
      return;
    }
    setSelectedFile(file);
    setMessage("");
  };

  const handleFileChange = (event) => selectFile(event.target.files?.[0]);

  const handleUpload = async () => {
    if (!selectedFile) {
      setMessage("请先选择一个文件。");
      return;
    }

    const allowedExtensions = [".md", ".txt", ".pdf"];
    const filename = selectedFile.name.toLowerCase();
    const isAllowed = allowedExtensions.some((ext) => filename.endsWith(ext));

    if (!isAllowed) {
      setMessage("只支持上传 .md / .txt / .pdf 文件。");
      return;
    }

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("category", selectedCategory);

    try {
      setLoading(true);
      setUploadProgress(0);
      setMessage("正在上传文件...");

      await apiClient.post("/api/files/upload", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
        onUploadProgress: (event) => {
          if (event.total) setUploadProgress(Math.round((event.loaded / event.total) * 100));
        },
      });

      setSelectedFile(null);
      setMessage("文件上传成功。请点击“重建知识库索引”，让新文件进入 RAG 检索。");

      if (fileInputRef.current) fileInputRef.current.value = "";

      await fetchFiles();
      await fetchKnowledgeStatus();
    } catch (error) {
      console.error("upload file error:", error);

      setMessage(getFriendlyErrorMessage(error, "文件上传失败。"));
    } finally {
      setLoading(false);
      setUploadProgress(0);
    }
  };

  const handleSearch = async (event) => {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setMessage("");
    try {
      const response = await apiClient.post("/api/knowledge/search", { query: query.trim(), top_k: 5 });
      setSearchResults(response.data.results || response.data.chunks || []);
    } catch (error) {
      setMessage(getFriendlyErrorMessage(error, "知识库近似搜索失败。"));
    } finally {
      setSearching(false);
    }
  };

  const handleDelete = async (fileId) => {
    const confirmed = window.confirm("确认删除这个文件吗？");

    if (!confirmed) {
      return;
    }

    try {
      setLoading(true);
      setMessage("正在删除文件...");

      await apiClient.delete(`/api/files/${fileId}`);

      setMessage("文件删除成功。建议重新构建知识库索引，避免向量库中残留旧文件内容。");

      await fetchFiles();
      await fetchKnowledgeStatus();
    } catch (error) {
      console.error("delete file error:", error);

      setMessage(getFriendlyErrorMessage(error, "文件删除失败。"));
    } finally {
      setLoading(false);
    }
  };

  const handleRebuildKnowledge = async () => {
    const confirmed = window.confirm(
      "确认重建知识库索引吗？这会重新解析已上传文件，并刷新 ChromaDB 向量库。"
    );

    if (!confirmed) {
      return;
    }

    try {
      setLoading(true);
      setMessage("正在重建知识库索引，首次加载 embedding 模型可能较慢...");

      await createJob(
        "/api/tasks/knowledge-rebuild",
        {},
        "knowledge-rebuild",
      );
      setMessage("知识库索引任务已进入后台队列。");
    } catch (error) {
      console.error("rebuild knowledge error:", error);

      setMessage(getFriendlyErrorMessage(error, "知识库索引重建失败。"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <section>
      <h1>知识库管理</h1>
      <p>上传 PDF、TXT 或 MD 文件并建立索引，供面试 Agent 在当前账号范围内查找相关资料。</p>

      <div className="upload-limits" aria-label="上传限制">
        <span>支持 PDF / TXT / MD</span><span>单文件最多 20 MB</span><span>账号总存储最多 200 MB</span>
      </div>

      <div className={`upload-panel drop-zone${dragActive ? " is-dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragActive(true); }} onDragLeave={() => setDragActive(false)} onDrop={(event) => { event.preventDefault(); setDragActive(false); selectFile(event.dataTransfer.files?.[0]); }}>
        <input
          id="file-input"
          ref={fileInputRef}
          type="file"
          accept=".md,.txt,.pdf"
          onChange={handleFileChange}
          disabled={busy}
        />

        <button type="button" className="secondary-button" onClick={() => fileInputRef.current?.click()} disabled={busy}>选择文件</button>

        <select
          value={selectedCategory}
          onChange={(event) => setSelectedCategory(event.target.value)}
          aria-label="文件分类"
        >
          <option value="resume">简历</option>
          <option value="project">项目资料</option>
          <option value="other">其他</option>
        </select>

        <button type="button" onClick={handleUpload} disabled={busy}>
          {busy ? "处理中..." : "上传文件"}
        </button>
      </div>

      {selectedFile && (
        <p className="hint-text">
          已选择：<strong>{selectedFile.name}</strong>（{(selectedFile.size / 1024 / 1024).toFixed(2)} MB）
        </p>
      )}
      {uploadProgress > 0 && <div className="job-progress" aria-label={`上传进度 ${uploadProgress}%`}><span style={{ width: `${uploadProgress}%` }} /></div>}

      <div className="chat-actions">
        <button type="button" onClick={refreshAll} disabled={busy}>
          刷新文件与状态
        </button>

        <button type="button" onClick={fetchKnowledgeStatus} disabled={busy}>
          刷新知识库状态
        </button>

        <button type="button" onClick={handleRebuildKnowledge} disabled={busy}>
          重建知识库索引
        </button>
      </div>

      {message && <p className="message-text">{message}</p>}

      {job && <BackgroundJobCard job={job} onCancel={isRunning ? cancelJob : undefined} onRetry={job.status === "failed" || job.status === "timed_out" ? handleRebuildKnowledge : undefined} />}

      <form className="knowledge-search" onSubmit={handleSearch}>
        <div><label htmlFor="knowledge-query">在我的资料中近似搜索</label><p>结果按语义相关性展示，仅用于查找资料，不代表 Agent 已采纳为回答证据。</p></div>
        <div><input id="knowledge-query" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={6000} placeholder="例如：项目中如何处理并发任务？" /><button type="submit" disabled={searching}>{searching ? "搜索中..." : "搜索"}</button></div>
      </form>
      {searchResults.length > 0 && <div className="search-result-list">{searchResults.map((item, index) => <article key={`${item.file_id || item.filename}-${index}`}><strong>{item.filename || "资料片段"}</strong><p>{item.text || item.content || "无预览内容"}</p></article>)}</div>}

      {knowledgeStatus && (
        <div className="status-box">
          <h2>知识库状态</h2>

          <p>
            文件总数：
            <strong>{knowledgeStatus.total_files ?? "-"}</strong>
          </p>

          <p>
            已索引文件：
            <strong>{knowledgeStatus.indexed_files ?? "-"}</strong>
          </p>

          <p>
            失败文件：
            <strong>{knowledgeStatus.failed_files ?? "-"}</strong>
          </p>

          <p>
            向量片段数：
            <strong>{knowledgeStatus.total_chunks ?? "-"}</strong>
          </p>

          <p>
            状态：
            <strong>{knowledgeStatus.status ?? "-"}</strong>
          </p>
        </div>
      )}

      <div className="table-header">
        <h2>已上传文件</h2>

        <button type="button" onClick={fetchFiles} disabled={busy}>
          刷新列表
        </button>
      </div>

      {files.length === 0 ? (
        <p className="empty-text">暂无上传文件。</p>
      ) : (
        <div className="table-scroll"><table className="file-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>类型</th>
              <th>分类</th>
              <th>状态</th>
              <th>上传时间</th>
              <th>操作</th>
            </tr>
          </thead>

          <tbody>
            {files.map((file) => (
              <tr key={file.file_id}>
                <td>{file.filename}</td>
                <td>{file.file_type}</td>
                <td>
                  {file.category === "resume"
                    ? "简历"
                    : file.category === "project"
                      ? "项目资料"
                      : "其他"}
                </td>
                <td><span className={`status-badge ${file.status}`}>{statusLabels[file.status] || "状态未知"}</span></td>
                <td>{formatDateTime(file.created_at)}</td>
                <td>
                  <button
                    type="button"
                    className="danger-button"
                    onClick={() => handleDelete(file.file_id)}
                    disabled={busy}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table></div>
      )}
    </section>
  );
}

export default KnowledgeBase;
