import { useMemo, useState } from "react";

function ListBlock({ title, items }) {
  if (!items?.length) {
    return null;
  }
  return (
    <div className="resume-description-block">
      <h4>{title}</h4>
      <ul>{items.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
    </div>
  );
}

function ResumeDescriptionPanel({
  completedSessions,
  targetJobs,
  projectFiles,
  descriptions,
  selectedDescription,
  generating,
  onGenerate,
  onSelect,
  onDelete,
  onCopy,
}) {
  const [sessionId, setSessionId] = useState("");
  const [targetJobId, setTargetJobId] = useState("");
  const [projectFileIds, setProjectFileIds] = useState([]);
  const defaultSessionId = completedSessions[0]?.id;
  const effectiveSessionId = sessionId || (defaultSessionId ? String(defaultSessionId) : "");
  const selectedSession = useMemo(
    () => completedSessions.find((session) => String(session.id) === effectiveSessionId),
    [completedSessions, effectiveSessionId],
  );

  const toggleFile = (fileId) => {
    setProjectFileIds((current) => current.includes(fileId) ? current.filter((id) => id !== fileId) : [...current, fileId]);
  };

  const submit = (event) => {
    event.preventDefault();
    onGenerate({
      session_id: Number(effectiveSessionId),
      target_job_id: targetJobId ? Number(targetJobId) : null,
      project_file_ids: projectFileIds.length ? projectFileIds : null,
    });
  };

  const conciseText = selectedDescription
    ? `${selectedDescription.project_name}\n${selectedDescription.one_line_summary}\n${selectedDescription.concise_bullets.map((item) => `- ${item}`).join("\n")}`
    : "";

  return (
    <div className="resume-description-panel">
      <form className="resume-generation-form" onSubmit={submit}>
        <div className="field-group">
          <label htmlFor="resume-session">已完成面试</label>
          <select id="resume-session" value={effectiveSessionId} onChange={(event) => setSessionId(event.target.value)} required>
            {completedSessions.length === 0 && <option value="">暂无已完成会话</option>}
            {completedSessions.map((session) => <option key={session.id} value={session.id}>{session.title}</option>)}
          </select>
        </div>
        <div className="field-group">
          <label htmlFor="resume-target-job">表达方向（可选）</label>
          <select id="resume-target-job" value={targetJobId} onChange={(event) => setTargetJobId(event.target.value)}>
            <option value="">使用会话岗位</option>
            {targetJobs.map((job) => <option key={job.id} value={job.id}>{job.job_title}{job.company_name ? ` · ${job.company_name}` : ""}</option>)}
          </select>
        </div>
        <fieldset className="project-file-picker">
          <legend>项目资料（可选）</legend>
          <p>不选择时使用面试会话关联的项目文件。</p>
          <div>
            {projectFiles.map((file) => (
              <label key={file.file_id}>
                <input type="checkbox" checked={projectFileIds.includes(file.file_id)} onChange={() => toggleFile(file.file_id)} />
                {file.filename}
              </label>
            ))}
          </div>
        </fieldset>
        <button type="submit" disabled={generating || !selectedSession}>
          {generating ? "生成中..." : "生成新版本"}
        </button>
      </form>

      <div className="resume-history-layout">
        <aside className="resume-version-list">
          <h3>历史版本</h3>
          {descriptions.length === 0 ? <p className="empty-text">暂无生成记录。</p> : descriptions.map((item) => (
            <button key={item.id} type="button" className={selectedDescription?.id === item.id ? "active" : ""} onClick={() => onSelect(item.id)}>
              <strong>{item.project_name}</strong>
              <span>{new Date(item.created_at).toLocaleString("zh-CN")}</span>
            </button>
          ))}
        </aside>

        <div className="resume-description-result">
          {!selectedDescription ? <p className="empty-text">选择历史版本或生成新描述后查看内容。</p> : (
            <>
              <div className="inline-heading">
                <div><p className="section-kicker">项目描述</p><h3>{selectedDescription.project_name}</h3></div>
                <button type="button" className="danger-button" onClick={() => onDelete(selectedDescription.id)}>删除版本</button>
              </div>
              <p className="one-line-summary">{selectedDescription.one_line_summary}</p>
              {selectedDescription.warnings?.length > 0 && (
                <div className="interview-alert warning"><strong>写入简历前请确认</strong><ul>{selectedDescription.warnings.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul></div>
              )}
              <div className="resume-description-block">
                <div className="inline-heading"><h4>精简版</h4><button type="button" className="secondary-button" onClick={() => onCopy(conciseText)}>整体复制</button></div>
                <ul>{selectedDescription.concise_bullets.map((item, index) => <li key={`${item}-${index}`}>{item}</li>)}</ul>
              </div>
              <div className="resume-description-block">
                <div className="inline-heading"><h4>详细版</h4><button type="button" className="secondary-button" onClick={() => onCopy(selectedDescription.detailed_description)}>整体复制</button></div>
                <p>{selectedDescription.detailed_description}</p>
              </div>
              <ListBlock title="技术栈" items={selectedDescription.technical_stack} />
              <ListBlock title="个人职责" items={selectedDescription.responsibilities} />
              <ListBlock title="难点" items={selectedDescription.challenges} />
              <ListBlock title="解决方案" items={selectedDescription.solutions} />
              <ListBlock title="项目成果" items={selectedDescription.outcomes} />
              <ListBlock title="面试讲解要点" items={selectedDescription.interview_talking_points} />
              <ListBlock title="证据来源 ID" items={selectedDescription.evidence_source_ids} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default ResumeDescriptionPanel;
