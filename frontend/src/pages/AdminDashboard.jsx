import { useCallback, useMemo, useState } from "react";

import AdminOperations from "../components/admin/AdminOperations";
import AdminRecords from "../components/admin/AdminRecords";
import AdminUsage from "../components/admin/AdminUsage";
import AdminUsers from "../components/admin/AdminUsers";
import { useAuth } from "../auth/authContext";

const tabs = [
  ["overview", "概览"], ["users", "用户管理"], ["usage", "用量统计"],
  ["runs", "Agent 运行记录"], ["invite", "邀请码设置"], ["cleanup", "数据清理"], ["audit", "审计日志"],
];

function dateText(daysAgo = 0) {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function AdminDashboard({ onBack }) {
  const { currentUser } = useAuth();
  const [activeTab, setActiveTab] = useState("overview");
  const [dateRange, setDateRange] = useState({ date_from: dateText(6), date_to: dateText() });
  const [refreshKey, setRefreshKey] = useState(0);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const onForbidden = useCallback(() => setPermissionDenied(true), []);
  const stableDateRange = useMemo(() => dateRange, [dateRange]);

  if (!currentUser?.is_admin || permissionDenied) {
    return <section className="management-page permission-denied"><h1>无管理员权限</h1><p>当前账号没有管理员权限。后端权限校验是最终访问边界。</p><button type="button" onClick={onBack}>返回普通工作区</button></section>;
  }

  return <section className="management-page admin-dashboard">
    <div className="page-heading-row admin-heading">
      <div><h1>管理后台</h1><p>管理员：{currentUser.username}。敏感操作均由后端再次校验并记录审计。</p></div>
      <div className="admin-global-controls"><label>开始日期<input type="date" value={dateRange.date_from} onChange={(e) => setDateRange((v) => ({ ...v, date_from: e.target.value }))} /></label><label>结束日期<input type="date" value={dateRange.date_to} onChange={(e) => setDateRange((v) => ({ ...v, date_to: e.target.value }))} /></label><button type="button" onClick={() => setRefreshKey((v) => v + 1)}>刷新当前页</button></div>
    </div>
    <nav className="admin-tabs" aria-label="管理后台功能">{tabs.map(([key, label]) => <button key={key} type="button" className={activeTab === key ? "active" : ""} onClick={() => setActiveTab(key)}>{label}</button>)}</nav>
    {activeTab === "overview" && <AdminUsage mode="overview" dateRange={stableDateRange} refreshKey={refreshKey} onForbidden={onForbidden} />}
    {activeTab === "users" && <AdminUsers refreshKey={refreshKey} onForbidden={onForbidden} />}
    {activeTab === "usage" && <AdminUsage mode="usage" dateRange={stableDateRange} refreshKey={refreshKey} onForbidden={onForbidden} />}
    {activeTab === "runs" && <AdminRecords kind="agent" dateRange={stableDateRange} refreshKey={refreshKey} onForbidden={onForbidden} />}
    {activeTab === "invite" && <AdminOperations kind="invite" refreshKey={refreshKey} onForbidden={onForbidden} onCompleted={() => setRefreshKey((v) => v + 1)} />}
    {activeTab === "cleanup" && <AdminOperations kind="cleanup" refreshKey={refreshKey} onForbidden={onForbidden} />}
    {activeTab === "audit" && <AdminRecords kind="audit" dateRange={stableDateRange} refreshKey={refreshKey} onForbidden={onForbidden} />}
  </section>;
}

export default AdminDashboard;
