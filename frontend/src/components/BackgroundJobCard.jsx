/* eslint-disable react-refresh/only-export-components */
import { formatDateTime } from "../utils/format";

export const terminalJobStatuses = new Set(["succeeded", "failed", "cancelled", "timed_out"]);

const taskLabels = {
  knowledge_rebuild: "知识库索引",
  agent_ask: "Agent 回答",
  job_analysis: "岗位分析",
  interview_start: "启动面试",
  interview_evaluation: "回答评价",
  improvement_generation: "生成改进任务",
  resume_generation: "生成简历描述",
  data_retention_cleanup: "清理过期数据",
};

const statusLabels = {
  queued: "等待执行",
  running: "执行中",
  retry_wait: "等待重试",
  cancel_requested: "正在取消",
  succeeded: "已完成",
  failed: "执行失败",
  cancelled: "已取消",
  timed_out: "已超时",
};

const phaseLabels = {
  queued: "已进入队列",
  preparing: "准备任务",
  parsing: "解析资料",
  indexing: "写入索引",
  retrieving: "查找相关资料",
  planning: "规划面试",
  evaluating: "生成评价",
  saving: "保存结果",
  cleaning_database: "清理数据记录",
  cleaning_vectors: "清理知识索引",
  completed: "处理完成",
};

export function getTaskLabel(taskType) {
  return taskLabels[taskType] || "后台任务";
}

function BackgroundJobCard({ job, onCancel, onRetry, retryLabel = "重新创建", compact = false }) {
  if (!job) return null;
  const terminal = terminalJobStatuses.has(job.status);
  const cancellable = !terminal && !["cancel_requested"].includes(job.status);
  const progress = Math.max(0, Math.min(100, Number(job.progress_percent || 0)));

  const requestCancel = () => {
    if (window.confirm(`确认取消“${getTaskLabel(job.task_type)}”吗？`)) onCancel?.();
  };

  return (
    <article className={`background-job-card status-${job.status}${compact ? " compact" : ""}`}>
      <div className="background-job-heading">
        <div>
          <span className={`status-badge ${job.status}`}>{statusLabels[job.status] || job.status}</span>
          <h3>{getTaskLabel(job.task_type)}</h3>
        </div>
        <strong>{progress}%</strong>
      </div>
      <p>{phaseLabels[job.phase] || "正在处理，请稍候"}</p>
      <div className="job-progress" aria-label={`${getTaskLabel(job.task_type)}进度 ${progress}%`}>
        <span style={{ width: `${progress}%` }} />
      </div>
      {!compact && <small>创建于 {formatDateTime(job.created_at)}</small>}
      {(job.status === "failed" || job.status === "timed_out" || job.status === "cancelled") && (
        <div className="job-failure" role="alert">
          <strong>{job.status === "timed_out" ? "任务超过允许时间" : job.status === "cancelled" ? "任务已取消" : "任务未能完成"}</strong>
          <p>{job.error_summary || (job.status === "cancelled" ? "任务已停止，可刷新状态或重新发起。" : "请稍后重新创建任务；若问题持续出现，请查看系统状态。")}</p>
        </div>
      )}
      <div className="job-actions">
        {cancellable && onCancel && <button type="button" className="secondary-button" onClick={requestCancel}>取消任务</button>}
        {(job.status === "failed" || job.status === "timed_out" || job.status === "cancelled") && onRetry && (
          <button type="button" onClick={onRetry}>{retryLabel}</button>
        )}
      </div>
    </article>
  );
}

export default BackgroundJobCard;
