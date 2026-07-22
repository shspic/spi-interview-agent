import { useCallback, useEffect, useState } from "react";

import { getMyUsage } from "../api/usage";
import { formatDateTime } from "../utils/format";
import { getFriendlyErrorMessage } from "../utils/errorMessage";

function Usage() {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const loadUsage = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setUsage(await getMyUsage());
    } catch (requestError) {
      setError(getFriendlyErrorMessage(requestError, "用量读取失败，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(loadUsage, 0);
    return () => window.clearTimeout(timer);
  }, [loadUsage]);

  return (
    <section className="management-page usage-page">
      <div className="page-heading-row">
        <div>
          <h1>用量查看</h1>
          <p>
            统计日期 {usage?.current_date || "--"}，按 {usage?.timezone || "Asia/Shanghai"}
            自然日重置。
          </p>
        </div>
        <button type="button" onClick={loadUsage} disabled={loading}>
          {loading ? "刷新中..." : "刷新"}
        </button>
      </div>

      {error && (
        <div className="notice-box error-notice" role="alert">
          <span>{error}</span>
          <button type="button" onClick={loadUsage}>重试</button>
        </div>
      )}

      {loading && !usage ? (
        <div className="page-loading">正在读取今日用量...</div>
      ) : usage?.items?.length ? (
        <div className="usage-grid">
          {usage.items.map((item) => {
            const unlimited = Boolean(item.unlimited);
            const occupied = Number(item.used || 0) + Number(item.reserved || 0);
            const percent = !unlimited && item.limit > 0 ? Math.min(100, (occupied / item.limit) * 100) : 0;
            const exhausted = !unlimited && item.remaining === 0;
            const nearLimit = !exhausted && item.limit > 0 && occupied / item.limit >= 0.8;
            return (
              <article key={item.usage_type} className={`usage-card${exhausted ? " exhausted" : ""}`}>
                <div className="usage-card-heading">
                  <div>
                    <span>{item.usage_type}</span>
                    <h2>{item.display_name || item.usage_type}</h2>
                  </div>
                  <strong>{unlimited ? "无限" : exhausted ? "今日额度已用完" : nearLimit ? "接近上限" : "可用"}</strong>
                </div>
                <div className="usage-progress" aria-label={`${item.display_name}用量`}>
                  <span style={{ width: `${percent}%` }} />
                </div>
                <dl className="usage-metrics">
                  <div><dt>已使用</dt><dd>{item.used}</dd></div>
                  <div><dt>执行中</dt><dd>{item.reserved}</dd></div>
                  <div><dt>每日上限</dt><dd>{unlimited ? "无限" : item.limit}</dd></div>
                  <div><dt>剩余</dt><dd>{unlimited ? "无限" : item.remaining}</dd></div>
                </dl>
                <p>重置时间：{formatDateTime(item.reset_at)}</p>
              </article>
            );
          })}
        </div>
      ) : !error ? (
        <div className="empty-state">后端暂未返回用量数据。</div>
      ) : null}
    </section>
  );
}

export default Usage;
