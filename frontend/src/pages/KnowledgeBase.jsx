import { useCallback, useEffect, useState } from "react";

import apiClient from "../api/client";
import { getFriendlyErrorMessage } from "../utils/errorMessage";

function KnowledgeBase() {
  const [files, setFiles] = useState([]);
  const [knowledgeStatus, setKnowledgeStatus] = useState(null);
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedCategory, setSelectedCategory] = useState("other");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

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

  useEffect(() => {
    const timerId = window.setTimeout(refreshAll, 0);

    return () => window.clearTimeout(timerId);
  }, [refreshAll]);

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];

    if (!file) {
      setSelectedFile(null);
      return;
    }

    setSelectedFile(file);
    setMessage("");
  };

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
      setMessage("正在上传文件...");

      await apiClient.post("/api/files/upload", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      setSelectedFile(null);
      setMessage("文件上传成功。请点击“重建知识库索引”，让新文件进入 RAG 检索。");

      const fileInput = document.getElementById("file-input");
      if (fileInput) {
        fileInput.value = "";
      }

      await fetchFiles();
      await fetchKnowledgeStatus();
    } catch (error) {
      console.error("upload file error:", error);

      setMessage(getFriendlyErrorMessage(error, "文件上传失败。"));
    } finally {
      setLoading(false);
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

      const response = await apiClient.post("/api/knowledge/rebuild");

      const totalChunks =
        response.data.total_chunks ??
        response.data.chunk_count ??
        response.data.knowledge_base?.total_chunks ??
        0;

      setMessage(`知识库索引重建完成。当前向量片段数：${totalChunks}`);

      await fetchFiles();
      await fetchKnowledgeStatus();
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
      <p>
        上传 Markdown、TXT 或 PDF 文件，并重建知识库索引。索引完成后，这些资料会用于
        RAG 自由问答、岗位分析、模拟面试和 LangGraph Agent。
      </p>

      <div className="upload-panel">
        <input
          id="file-input"
          type="file"
          accept=".md,.txt,.pdf"
          onChange={handleFileChange}
        />

        <select
          value={selectedCategory}
          onChange={(event) => setSelectedCategory(event.target.value)}
          aria-label="文件分类"
        >
          <option value="resume">简历</option>
          <option value="project">项目资料</option>
          <option value="other">其他</option>
        </select>

        <button type="button" onClick={handleUpload} disabled={loading}>
          {loading ? "处理中..." : "上传文件"}
        </button>
      </div>

      {selectedFile && (
        <p className="hint-text">
          已选择文件：<strong>{selectedFile.name}</strong>
        </p>
      )}

      <div className="chat-actions">
        <button type="button" onClick={refreshAll} disabled={loading}>
          刷新文件与状态
        </button>

        <button type="button" onClick={fetchKnowledgeStatus} disabled={loading}>
          刷新知识库状态
        </button>

        <button type="button" onClick={handleRebuildKnowledge} disabled={loading}>
          重建知识库索引
        </button>
      </div>

      {message && <p className="message-text">{message}</p>}

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

        <button type="button" onClick={fetchFiles} disabled={loading}>
          刷新列表
        </button>
      </div>

      {files.length === 0 ? (
        <p className="empty-text">暂无上传文件。</p>
      ) : (
        <table className="file-table">
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
                <td>{file.status}</td>
                <td>{file.created_at}</td>
                <td>
                  <button
                    type="button"
                    className="danger-button"
                    onClick={() => handleDelete(file.file_id)}
                    disabled={loading}
                  >
                    删除
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default KnowledgeBase;
