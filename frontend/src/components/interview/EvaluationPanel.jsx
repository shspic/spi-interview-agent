const scoreItems = [
  ["technical_accuracy_score", "技术准确性"],
  ["evidence_consistency_score", "资料一致性"],
  ["answer_depth_score", "回答深度"],
  ["expression_structure_score", "表达结构"],
  ["job_match_score", "岗位匹配度"],
];

function textFromItem(item) {
  if (typeof item === "string") {
    return item;
  }
  return (
    item?.description ||
    item?.explanation ||
    item?.claim ||
    item?.suggestion ||
    JSON.stringify(item)
  );
}

function TextList({ items, emptyText }) {
  if (!items?.length) {
    return emptyText ? <p className="empty-text">{emptyText}</p> : null;
  }

  return (
    <ul className="interview-text-list">
      {items.map((item, index) => (
        <li key={`${textFromItem(item)}-${index}`}>{textFromItem(item)}</li>
      ))}
    </ul>
  );
}

function EvaluationPanel({ turn, decision, onCopy, compact = false }) {
  if (!turn?.user_answer) {
    return null;
  }

  const evaluated = turn.total_score !== null && turn.total_score !== undefined;

  if (!evaluated) {
    return (
      <div className="interview-alert warning" role="status">
        <strong>回答已保存，评价待恢复</strong>
        <p>后端尚未完成本题评价。再次提交相同答案会进入恢复逻辑，不会覆盖原回答。</p>
      </div>
    );
  }

  return (
    <article className={compact ? "evaluation-panel compact" : "evaluation-panel"}>
      <div className="evaluation-heading">
        <div>
          <p className="section-kicker">单题评价</p>
          <h3>本题得分与改进建议</h3>
        </div>
        <strong className="total-score">{turn.total_score}</strong>
      </div>

      {!compact && (
        <div className="evaluation-answer-block">
          <h4>你的原回答</h4>
          <p>{turn.user_answer}</p>
        </div>
      )}

      <div className="dimension-score-grid">
        {scoreItems.map(([key, label]) => {
          const score = turn[key] ?? 0;
          return (
            <div key={key} className="dimension-score-item">
              <span>{label}</span>
              <strong>{score}</strong>
              <div className="score-track" aria-label={`${label} ${score} 分`}>
                <span style={{ width: `${Math.max(0, Math.min(100, score))}%` }} />
              </div>
            </div>
          );
        })}
      </div>

      <div className="evaluation-grid">
        <div>
          <h4>做得好的地方</h4>
          <TextList items={turn.strengths} emptyText="本题暂无明确优势记录。" />
        </div>
        <div>
          <h4>存在的问题</h4>
          <TextList items={turn.problems} emptyText="本题暂无问题记录。" />
        </div>
      </div>

      {(turn.has_evidence_conflict || turn.evidence_conflicts?.length > 0) && (
        <div className="interview-alert danger">
          <strong>资料冲突</strong>
          <TextList items={turn.evidence_conflicts} />
        </div>
      )}

      {turn.unsupported_claims?.length > 0 && (
        <div className="interview-alert warning">
          <strong>无依据内容</strong>
          <TextList items={turn.unsupported_claims} />
        </div>
      )}

      {turn.optimized_answer && (
        <div className="optimized-answer">
          <div className="inline-heading">
            <h4>优化后的回答</h4>
            <button type="button" className="secondary-button" onClick={() => onCopy(turn.optimized_answer)}>
              复制
            </button>
          </div>
          <p>{turn.optimized_answer}</p>
        </div>
      )}

      {turn.modification_reason && (
        <div className="evaluation-answer-block">
          <h4>修改理由</h4>
          <p>{turn.modification_reason}</p>
        </div>
      )}

      {decision && (
        <div className="decision-note">
          <strong>下一步：{decision.action === "follow_up" ? "继续追问" : decision.action === "complete" ? "结束面试" : "进入下一主问题"}</strong>
          <span>{decision.reason}</span>
        </div>
      )}
    </article>
  );
}

export default EvaluationPanel;
