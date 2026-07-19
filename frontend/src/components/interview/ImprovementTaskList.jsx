const categoryLabels = {
  technical: "技术能力",
  project_evidence: "项目证据",
  answer_depth: "回答深度",
  expression: "表达结构",
  job_match: "岗位匹配",
  resume: "简历表达",
};

const priorityLabels = {
  high: "高优先级",
  medium: "中优先级",
  low: "低优先级",
};

function ImprovementTaskList({ tasks, updatingTaskId, onToggle }) {
  const completedCount = tasks.filter((task) => task.status === "completed").length;
  const completionRate = tasks.length
    ? Math.round((completedCount / tasks.length) * 100)
    : 0;

  return (
    <div className="improvement-task-panel">
      <div className="inline-heading">
        <div>
          <h3>改进任务</h3>
          <p>已完成 {completedCount}/{tasks.length}，完成率 {completionRate}%</p>
        </div>
        <strong className="task-progress-value">{completionRate}%</strong>
      </div>

      <div className="task-progress-track" aria-label={`任务完成率 ${completionRate}%`}>
        <span style={{ width: `${completionRate}%` }} />
      </div>

      {tasks.length === 0 ? (
        <p className="empty-text">当前会话暂无改进任务。</p>
      ) : (
        <div className="improvement-task-list">
          {tasks.map((task) => {
            const completed = task.status === "completed";
            const updating = updatingTaskId === task.id;
            return (
              <article key={task.id} className={completed ? "improvement-task completed" : "improvement-task"}>
                <label className="task-check">
                  <input
                    type="checkbox"
                    checked={completed}
                    disabled={updating}
                    onChange={() => onToggle(task)}
                  />
                  <span>{updating ? "更新中..." : completed ? "已完成" : "待完成"}</span>
                </label>
                <div className="task-body">
                  <div className="task-title-row">
                    <h4>{task.title}</h4>
                    <span className={`priority-badge ${task.priority}`}>
                      {priorityLabels[task.priority] || task.priority}
                    </span>
                  </div>
                  <p>{task.description}</p>
                  <div className="task-meta">
                    <span>{categoryLabels[task.category] || task.category}</span>
                    {task.source_turn && (
                      <span>来源：主问题 {task.source_turn.main_question_number} · {task.source_turn.question}</span>
                    )}
                  </div>
                  <div className="completion-criteria">
                    <strong>完成标准</strong>
                    <p>{task.completion_criteria}</p>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default ImprovementTaskList;
