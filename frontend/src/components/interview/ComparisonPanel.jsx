const dimensionLabels = {
  technical_accuracy_score: "技术准确性",
  evidence_consistency_score: "资料一致性",
  answer_depth_score: "回答深度",
  expression_structure_score: "表达结构",
  job_match_score: "岗位匹配度",
};

function formatDelta(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  return `${value > 0 ? "+" : ""}${value}`;
}

function ComparisonPanel({ comparison, loading, onLoad }) {
  if (!comparison) {
    return (
      <div className="comparison-empty">
        <p>完成再次练习后，可查看两轮训练表现变化。</p>
        <button type="button" onClick={onLoad} disabled={loading}>
          {loading ? "加载中..." : "加载成绩对比"}
        </button>
      </div>
    );
  }

  if (!comparison.comparable) {
    return (
      <div className="interview-alert warning">
        <strong>暂时无法比较</strong>
        <p>{comparison.reason || "两轮会话缺少可比较的评分数据。"}</p>
      </div>
    );
  }

  return (
    <div className="comparison-panel">
      <div className="comparison-overall">
        <div><span>上一轮</span><strong>{comparison.previous_overall_score}</strong></div>
        <div className={comparison.overall_delta > 0 ? "delta positive" : comparison.overall_delta < 0 ? "delta negative" : "delta"}>
          <span>总分变化</span><strong>{formatDelta(comparison.overall_delta)}</strong>
        </div>
        <div><span>本轮</span><strong>{comparison.current_overall_score}</strong></div>
      </div>

      <div className="comparison-dimensions">
        {Object.entries(dimensionLabels).map(([key, label]) => {
          const previous = comparison.previous_dimension_scores?.[key];
          const current = comparison.current_dimension_scores?.[key];
          const delta = comparison.dimension_deltas?.[key];
          return (
            <div key={key} className="comparison-dimension-row">
              <strong>{label}</strong>
              <span>{previous ?? "-"}</span>
              <div className="comparison-bar"><span style={{ width: `${Math.max(0, Math.min(100, current ?? 0))}%` }} /></div>
              <span>{current ?? "-"}</span>
              <span className={delta > 0 ? "positive" : delta < 0 ? "negative" : ""}>{formatDelta(delta)}</span>
            </div>
          );
        })}
      </div>

      <div className="comparison-groups">
        <p><strong>改善维度：</strong>{comparison.improved_dimensions?.map((key) => dimensionLabels[key] || key).join("、") || "无"}</p>
        <p><strong>下降维度：</strong>{comparison.regressed_dimensions?.map((key) => dimensionLabels[key] || key).join("、") || "无"}</p>
        <p><strong>不变维度：</strong>{comparison.unchanged_dimensions?.map((key) => dimensionLabels[key] || key).join("、") || "无"}</p>
      </div>

      <div className="comparison-task-stats">
        上一轮任务 {comparison.previous_task_count} 项，已完成 {comparison.completed_task_count} 项，完成率 {comparison.task_completion_rate}%
      </div>
      <p className="comparison-note">{comparison.note || "这是训练表现对比，不是严格的同题实验。"}</p>
    </div>
  );
}

export default ComparisonPanel;
