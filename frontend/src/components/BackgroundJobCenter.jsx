import { useCallback, useEffect, useMemo, useState } from "react";

import apiClient from "../api/client";
import BackgroundJobCard, { terminalJobStatuses } from "./BackgroundJobCard";

function BackgroundJobCenter() {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState([]);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const response = await apiClient.get("/api/tasks", { params: { page: 1, page_size: 20 } });
      setJobs(response.data.items || []);
      setError("");
    } catch {
      setError("后台任务列表暂时不可用。");
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const activeCount = useMemo(
    () => jobs.filter((job) => !terminalJobStatuses.has(job.status)).length,
    [jobs],
  );

  useEffect(() => {
    if (!activeCount) return undefined;
    const timer = window.setInterval(load, document.hidden ? 15000 : 5000);
    return () => window.clearInterval(timer);
  }, [activeCount, load]);

  useEffect(() => {
    const close = (event) => event.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  return (
    <div className="job-center">
      <button type="button" className="job-center-trigger" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        后台任务{activeCount ? <span>{activeCount}</span> : null}
      </button>
      {open && (
        <div className="job-center-panel" role="dialog" aria-label="后台任务中心">
          <div className="inline-heading"><div><h2>后台任务</h2><p>进行中的任务会自动刷新。</p></div><button type="button" className="secondary-button" onClick={load}>刷新</button></div>
          {error && <p className="inline-error">{error}</p>}
          {!jobs.length ? <p className="empty-text">暂无后台任务。</p> : jobs.map((job) => <BackgroundJobCard key={job.task_id} job={job} compact />)}
        </div>
      )}
    </div>
  );
}

export default BackgroundJobCenter;
