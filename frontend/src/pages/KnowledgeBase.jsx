import { useEffect, useState } from "react";

import apiClient from "../api/client";

function KnowledgeBase() {
  const [files, setFiles] = useState([]);
  const [selectedFile, setSelectedFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");

  const fetchFiles = async () => {
    try {
      setLoading(true);
      const response = await apiClient.get("/api/files");
      setFiles(response.data.files || []);
    } catch (error) {
      setMessage("获取文件列表失败，请检查后端是否启动。");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFiles();
  }, []);

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

    try {
      setLoading(true);
      setMessage("正在上传文件...");

      await apiClient.post("/api/files/upload", formData, {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      });

      setSelectedFile(null);
      setMessage("文件上传成功。");

      const fileInput = document.getElementById("file-input");
      if (fileInput) {
        fileInput.value = "";
      }

      await fetchFiles();
    } catch (error) {
      const detail = error.response?.data?.detail;
      setMessage(detail || "文件上传失败。");
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
      await apiClient.delete(`/api/files/${fileId}`);
      setMessage("文件删除成功。");
      await fetchFiles();
    } catch (error) {
      const detail = error.response?.data?.detail;
      setMessage(detail || "文件删除失败。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <section>
      <h1>知识库管理</h1>
      <p>上传 Markdown、TXT 或 PDF 文件，后续将用于构建本地 RAG 知识库。</p>

      <div className="upload-panel">
        <input
          id="file-input"
          type="file"
          accept=".md,.txt,.pdf"
          onChange={handleFileChange}
        />

        <button type="button" onClick={handleUpload} disabled={loading}>
          {loading ? "处理中..." : "上传文件"}
        </button>
      </div>

      {selectedFile && (
        <p className="hint-text">
          已选择文件：<strong>{selectedFile.name}</strong>
        </p>
      )}

      {message && <p className="message-text">{message}</p>}

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