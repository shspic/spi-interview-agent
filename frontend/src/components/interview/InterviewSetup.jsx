import { useState } from "react";

import AuroraTaskLoader from "../AuroraTaskLoader";

const modes = [
  { value: "quick", title: "快速练习", description: "3 个主问题，适合快速热身。" },
  { value: "standard", title: "标准面试", description: "5 个主问题，覆盖更完整。" },
  { value: "deep_dive", title: "专项深挖", description: "围绕已选项目持续追问。" },
];

function InterviewSetup({ targetJobs, projectFiles, activeJob, busy, loadingLabel, draftSession, onCreate, onStartDraft }) {
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState("quick");
  const [targetJobId, setTargetJobId] = useState(activeJob ? String(activeJob.id) : "");
  const [selectedFileIds, setSelectedFileIds] = useState([]);
  const [validationMessage, setValidationMessage] = useState("");

  const toggleFile = (fileId) => {
    setSelectedFileIds((current) => current.includes(fileId) ? current.filter((id) => id !== fileId) : [...current, fileId]);
  };

  const submit = (event) => {
    event.preventDefault();
    if (mode === "deep_dive" && selectedFileIds.length === 0) {
      setValidationMessage("专项深挖至少需要选择一个项目文件。");
      return;
    }
    setValidationMessage("");
    const modeLabel = modes.find((item) => item.value === mode)?.title || "面试练习";
    const generatedTitle = `${modeLabel} · ${new Date().toLocaleDateString("zh-CN")}`;
    onCreate({
      title: title.trim() || generatedTitle,
      mode,
      target_job_id: targetJobId ? Number(targetJobId) : null,
      selected_project_file_ids: selectedFileIds,
    });
  };

  return (
    <div className="interview-setup-layout">
      <form className="interview-setup-form" onSubmit={submit} aria-busy={Boolean(loadingLabel)}>
        <div className="field-group">
          <label htmlFor="session-title">会话标题（可选）</label>
          <input id="session-title" value={title} onChange={(event) => setTitle(event.target.value)} maxLength={200} placeholder="例如：后端开发标准面试" />
        </div>

        <fieldset className="mode-selector">
          <legend>面试模式</legend>
          {modes.map((item) => (
            <label key={item.value} className={mode === item.value ? "active" : ""}>
              <input type="radio" name="interview-mode" value={item.value} checked={mode === item.value} onChange={(event) => setMode(event.target.value)} />
              <strong>{item.title}</strong>
              <span>{item.description}</span>
            </label>
          ))}
        </fieldset>

        <div className="field-group">
          <label htmlFor="target-job">目标岗位</label>
          <select id="target-job" value={targetJobId} onChange={(event) => setTargetJobId(event.target.value)}>
            <option value="">暂不指定</option>
            {targetJobs.map((job) => <option key={job.id} value={job.id}>{job.job_title}{job.company_name ? ` · ${job.company_name}` : ""}{job.is_active ? "（当前）" : ""}</option>)}
          </select>
        </div>

        <fieldset className="project-file-picker">
          <legend>项目文件</legend>
          <p>{mode === "deep_dive" ? "专项深挖必须至少选择一个项目文件。" : "可选一个或多个项目文件，帮助问题更贴近真实经历。"}</p>
          <div>
            {projectFiles.length === 0 ? <span className="empty-text">暂无项目文件。</span> : projectFiles.map((file) => (
              <label key={file.file_id}>
                <input type="checkbox" checked={selectedFileIds.includes(file.file_id)} onChange={() => toggleFile(file.file_id)} />
                {file.filename}
              </label>
            ))}
          </div>
        </fieldset>

        {validationMessage && <p className="form-error" role="alert">{validationMessage}</p>}
        {projectFiles.length === 0 && mode !== "deep_dive" && <div className="interview-alert warning"><strong>当前证据有限</strong><p>快速或标准面试仍可启动，但问题会更偏开放式，无法充分核对项目细节。</p></div>}

        <button type="submit" disabled={busy}>{busy ? "正在创建并启动..." : "创建并开始"}</button>
        <AuroraTaskLoader label={loadingLabel} />
      </form>

      {draftSession && (
        <aside className="draft-recovery-card">
          <span className="status-badge draft">草稿待启动</span>
          <h3>{draftSession.title}</h3>
          <p>会话已经创建，但尚未成功启动。可以直接重试，不会重复创建。</p>
          <button type="button" onClick={() => onStartDraft(draftSession.id)} disabled={busy}>{busy ? "启动中..." : "重新开始"}</button>
        </aside>
      )}
    </div>
  );
}

export default InterviewSetup;
