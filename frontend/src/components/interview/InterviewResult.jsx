import { useMemo, useState } from "react";

import ComparisonPanel from "./ComparisonPanel";

const scoreItems = [
  ["technical_accuracy_score", "技术准确性"],
  ["evidence_consistency_score", "资料一致性"],
  ["answer_depth_score", "回答深度"],
  ["expression_structure_score", "表达结构"],
  ["job_match_score", "岗位匹配度"],
];
const tabs = [
  ["diagnosis", "诊断"],
  ["answer", "原回答"],
  ["optimized", "优化回答"],
  ["tasks", "改进任务"],
];

function text(item) {
  return typeof item === "string"
    ? item
    : item?.description || item?.explanation || item?.claim || item?.suggestion || JSON.stringify(item);
}

function TextList({ items, empty = "暂无记录。" }) {
  return items?.length
    ? <ul className="interview-text-list">{items.map((item, index) => <li key={`${text(item)}-${index}`}>{text(item)}</li>)}</ul>
    : <p className="empty-text">{empty}</p>;
}

function riskCount(turns, key) {
  return turns.reduce((count, turn) => count + (turn[key]?.length || 0), 0);
}

function InterviewResult({
  session,
  sessions,
  comparison,
  busy,
  onCopy,
  onShowTasks,
  onRetry,
  onShowResume,
  onLoadComparison,
  onLoadSession,
  onRetryImprovements,
}) {
  const turns = useMemo(() => session.turns || [], [session.turns]);
  const initialExpanded = useMemo(() => {
    const conflict = turns.find((turn) => turn.has_evidence_conflict || turn.evidence_conflicts?.length);
    if (conflict) return conflict.id;
    return [...turns].sort((a, b) => (a.total_score ?? 101) - (b.total_score ?? 101))[0]?.id ?? null;
  }, [turns]);
  const [expandedId, setExpandedId] = useState(initialExpanded);
  const [filter, setFilter] = useState("all");
  const [activeTabs, setActiveTabs] = useState({});

  const conflictCount = riskCount(turns, "evidence_conflicts");
  const unsupportedCount = riskCount(turns, "unsupported_claims");
  const dimensions = session.dimension_scores || {};
  const filteredTurns = turns.filter((turn) => {
    if (filter === "improve") return (turn.total_score ?? 100) < 75;
    if (filter === "conflict") return turn.has_evidence_conflict || turn.evidence_conflicts?.length;
    if (filter === "unsupported") return turn.unsupported_claims?.length;
    return true;
  });

  return (
    <div className="aurora-result">
      <section className="result-overview">
        <div className="result-score"><span>总分</span><strong>{session.overall_score ?? "—"}</strong><small>/ 100</small></div>
        <div className="result-summary"><p className="section-kicker">MISSION REVIEW</p><h2>{session.title}</h2><p>{session.summary || "暂无会话总结。"}</p><small>完成于 {session.completed_at ? new Date(session.completed_at).toLocaleString("zh-CN") : "—"}</small></div>
        <div className="result-risk-summary"><strong>证据风险</strong><span className={conflictCount ? "danger" : ""}>资料冲突 {conflictCount} 项</span><span className={unsupportedCount ? "warning" : ""}>无依据内容 {unsupportedCount} 项</span></div>
        <div className="result-primary-actions"><button type="button" onClick={onShowTasks}>查看改进任务</button><button type="button" onClick={onRetry} disabled={busy}>再次练习</button><button type="button" className="secondary-button" onClick={onShowResume}>生成简历描述</button>{session.previous_session && <button type="button" className="secondary-button" onClick={onLoadComparison}>成绩对比</button>}</div>
      </section>

      <section className="dimension-bars" aria-label="五维评分">
        {scoreItems.map(([key, label]) => {
          const score = dimensions[key] ?? 0;
          return <article key={key}><div><span>{label}</span><strong>{dimensions[key] ?? "—"}</strong></div><div className="score-track" aria-label={`${label} ${score} 分`}><span className={score < 70 ? "is-warning" : ""} style={{ width: `${Math.max(0, Math.min(100, score))}%` }} /></div></article>;
        })}
      </section>

      {comparison && <ComparisonPanel comparison={comparison} />}

      <div className="result-body">
        <section className="question-review">
          <div className="question-review-heading"><div><p className="section-kicker">QUESTION DIAGNOSTICS</p><h3>问题诊断</h3></div><div className="result-filters" role="group" aria-label="筛选问题">{[["all","全部"],["improve","需改进"],["conflict","资料冲突"],["unsupported","无依据内容"]].map(([key, label]) => <button key={key} type="button" className={filter === key ? "active" : ""} onClick={() => setFilter(key)}>{label}</button>)}</div></div>
          {filteredTurns.map((turn) => {
            const expanded = expandedId === turn.id;
            const activeTab = activeTabs[turn.id] || "diagnosis";
            const turnTasks = (session.improvement_tasks || []).filter((task) => task.source_turn_id === turn.id || task.interview_turn_id === turn.id);
            return (
              <article key={turn.id} className={`question-accordion${expanded ? " expanded" : ""}`}>
                <button type="button" className="question-accordion-trigger" aria-expanded={expanded} aria-controls={`turn-${turn.id}`} onClick={() => setExpandedId(expanded ? null : turn.id)}>
                  <span className="question-kind">{turn.follow_up_number ? `追问 ${turn.follow_up_number}` : `主问题 ${turn.main_question_number}`}</span>
                  <span className="question-title">{turn.question}</span>
                  <strong>{turn.total_score ?? "待评价"}</strong>
                  <span className="question-risks">{(turn.has_evidence_conflict || turn.evidence_conflicts?.length) && <em className="danger">资料冲突</em>}{turn.unsupported_claims?.length > 0 && <em className="warning">无依据</em>}</span>
                  <span aria-hidden="true">{expanded ? "−" : "+"}</span>
                </button>
                {expanded && <div id={`turn-${turn.id}`} className="question-accordion-content">
                  {(turn.has_evidence_conflict || turn.evidence_conflicts?.length > 0) && <div className="risk-panel danger" role="note"><strong>资料冲突</strong><TextList items={turn.evidence_conflicts} empty="检测到资料冲突，但暂无可展示的冲突详情。" /></div>}
                  {turn.unsupported_claims?.length > 0 && <div className="risk-panel warning" role="note"><strong>无依据内容</strong><TextList items={turn.unsupported_claims} /></div>}
                  <div className="turn-local-tabs" role="tablist">{tabs.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={activeTab === key} className={activeTab === key ? "active" : ""} onClick={() => setActiveTabs((value) => ({ ...value, [turn.id]: key }))}>{label}</button>)}</div>
                  {activeTab === "diagnosis" && <div className="turn-diagnosis"><div><h4>本题评分</h4><strong className="turn-score">{turn.total_score ?? "待评价"}</strong><p>{turn.evaluation_summary || "暂无评价总结。"}</p></div><div><h4>做得好的地方</h4><TextList items={turn.strengths} /></div><div><h4>存在的问题</h4><TextList items={turn.problems} /></div>{turn.modification_reason && <div><h4>修改理由</h4><p>{turn.modification_reason}</p></div>}</div>}
                  {activeTab === "answer" && <div className="long-answer"><h4>原问题</h4><p>{turn.question}</p><h4>用户原回答</h4><p>{turn.user_answer || "未保存回答。"}</p></div>}
                  {activeTab === "optimized" && <div className="long-answer optimized-answer"><div className="inline-heading"><h4>优化后的回答</h4><button type="button" className="secondary-button" onClick={() => onCopy(turn.optimized_answer || "")} disabled={!turn.optimized_answer}>复制优化回答</button></div><p>{turn.optimized_answer || "暂无优化回答。"}</p><small>优化内容用于练习表达，不代表唯一正确答案。</small></div>}
                  {activeTab === "tasks" && <div><h4>本题改进任务</h4>{turnTasks.length ? turnTasks.map((task) => <article key={task.id} className="result-task"><strong>{task.title}</strong><p>{task.description}</p><small>{task.completion_criteria}</small></article>) : <p className="empty-text">暂无直接关联到本题的改进任务。</p>}</div>}
                </div>}
              </article>
            );
          })}
          {!filteredTurns.length && <div className="empty-state"><strong>没有符合当前筛选的问题</strong><p>切换筛选条件可查看其他诊断。</p></div>}
        </section>

        <aside className="result-context">
          <section><h3>下一步行动</h3><p>{session.improvement_summary || "根据问题诊断完成改进任务，再进入下一轮练习。"}</p><p><strong>任务状态：</strong>{session.improvement_status || "待生成"}</p>{session.next_round_strategy && <p><strong>下一轮策略：</strong>{session.next_round_strategy}</p>}{session.improvement_status === "failed" && <button type="button" onClick={onRetryImprovements} disabled={busy}>重试生成改进任务</button>}</section>
          <section><div className="inline-heading"><h3>最近会话</h3><span>{sessions.length}</span></div>{sessions.slice(0, 3).map((item) => <button key={item.id} type="button" className={item.id === session.id ? "recent-result-session current" : "recent-result-session"} onClick={() => onLoadSession(item.id)}><strong>{item.title}</strong><span>{item.id === session.id ? "当前会话" : item.status}</span><small>{item.overall_score == null ? "暂无总分" : `总分 ${item.overall_score}`}</small></button>)}</section>
        </aside>
      </div>
    </div>
  );
}

export default InterviewResult;
