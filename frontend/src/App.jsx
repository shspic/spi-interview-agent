import { useEffect, useMemo, useState } from "react";

import apiClient from "./api/client";
import { useAuth } from "./auth/authContext";
import BackgroundJobCenter from "./components/BackgroundJobCenter";
import BrandLockup from "./components/BrandLockup";
import StatePanel from "./components/StatePanel";
import { useLocationPath } from "./routing";
import AdminDashboard from "./pages/AdminDashboard";
import AuthPage from "./pages/AuthPage";
import History from "./pages/History";
import InterviewAgent from "./pages/InterviewAgent";
import KnowledgeBase from "./pages/KnowledgeBase";
import Profile from "./pages/Profile";
import Settings from "./pages/Settings";
import SystemStatus from "./pages/SystemStatus";
import Usage from "./pages/Usage";
import PasswordResetRequest from "./pages/PasswordResetRequest";
import TemporaryPasswordChange from "./pages/TemporaryPasswordChange";

import "./index.css";
import "./aurora.css";

const primaryPages = [
  ["/interview", "模拟面试", "从资料准备到面试、评价、改进复练和简历表达的一体化训练工作台。"],
  ["/knowledge", "知识库", "管理 PDF、TXT、MD 资料以及索引状态。"],
  ["/history", "历史", "查看训练记录、评价结果与历史版本。"],
  ["/system", "系统状态", "查看服务、数据库、Worker 与资料存储的可用状态。"],
];

const utilityPages = {
  "/profile": ["个人资料", "维护求职方向、目标岗位与资料完成度。"],
  "/usage": ["使用额度", "查看今日业务用量、每日上限与剩余次数。"],
  "/settings": ["设置", "管理登录会话、密码以及个人数据。"],
  "/admin": ["管理后台", "查看用户、任务、审计与运行状态。"],
};

const publicPaths = new Set(["/login", "/register", "/password-reset"]);

function NotFound({ navigate }) {
  return <StatePanel tone="error" title="页面不存在" description="该地址无对应页面，可能已移动或输入有误。" actionLabel="返回面试工作台" onAction={() => navigate("/interview", { replace: true })} />;
}

function Forbidden({ navigate }) {
  return <StatePanel tone="error" title="无权访问管理后台" description="当前账号不是管理员。权限以服务端返回的账号角色为准。" actionLabel="返回面试工作台" onAction={() => navigate("/interview", { replace: true })} />;
}

function App() {
  const { currentUser, isAuthenticated, isLoading, logout } = useAuth();
  const { location, pathname, navigate } = useLocationPath();
  const [backendStatus, setBackendStatus] = useState("检查中");
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated) {
      if (!publicPaths.has(pathname)) {
        if (pathname !== "/") window.sessionStorage.setItem("spi.return-to", location);
        navigate("/login", { replace: true });
      }
      return;
    }
    if (currentUser?.must_change_password) {
      if (pathname !== "/change-temporary-password") {
        if (!publicPaths.has(pathname) && pathname !== "/") {
          window.sessionStorage.setItem("aurora.return-to", location);
        }
        navigate("/change-temporary-password", { replace: true });
      }
      return;
    }
    if (pathname === "/change-temporary-password") {
      navigate("/interview", { replace: true });
      return;
    }
    if (pathname === "/" || publicPaths.has(pathname)) {
      const returnTo = window.sessionStorage.getItem("aurora.return-to")
        || window.sessionStorage.getItem("spi.return-to");
      window.sessionStorage.removeItem("aurora.return-to");
      window.sessionStorage.removeItem("spi.return-to");
      navigate(returnTo?.startsWith("/") ? returnTo : "/interview", { replace: true });
    }
  }, [currentUser?.must_change_password, isAuthenticated, isLoading, location, navigate, pathname]);

  useEffect(() => {
    if (!isAuthenticated) return undefined;
    let active = true;
    apiClient.get("/api/health/ready")
      .then((response) => active && setBackendStatus(response.data?.status === "ready" ? "就绪" : "需检查"))
      .catch((error) => {
        if (!active) return;
        setBackendStatus(error.response?.data?.status === "not_ready" ? "需检查" : "连接失败");
      });
    return () => { active = false; };
  }, [isAuthenticated]);

  useEffect(() => {
    const close = (event) => {
      if (event.key === "Escape") {
        setUserMenuOpen(false);
        setMobileNavOpen(false);
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);

  const pageMeta = useMemo(() => {
    const primary = primaryPages.find(([path]) => path === pathname);
    if (primary) return [primary[1], primary[2]];
    return utilityPages[pathname] || ["页面", "AURORA 面试训练工作台"];
  }, [pathname]);

  useEffect(() => {
    document.title = `${pageMeta[0]} · AURORA`;
  }, [pageMeta]);

  const go = (path) => {
    setUserMenuOpen(false);
    setMobileNavOpen(false);
    navigate(path);
  };

  if (isLoading) {
    return <main className="auth-page"><div className="auth-loading" role="status">正在验证登录状态...</div></main>;
  }

  if (!isAuthenticated) {
    if (pathname === "/password-reset") {
      return <PasswordResetRequest onBack={() => navigate("/login")} />;
    }
    return <AuthPage initialMode={pathname === "/register" ? "register" : "login"} onModeChange={(mode) => navigate(mode === "register" ? "/register" : "/login", { replace: true })} onPasswordReset={() => navigate("/password-reset")} />;
  }

  if (currentUser?.must_change_password) {
    return <TemporaryPasswordChange onCompleted={() => navigate("/login", { replace: true })} />;
  }

  const requestedSessionId = Number(new URLSearchParams(location.split("?")[1] || "").get("session")) || null;
  let page;
  if (pathname === "/interview") page = <InterviewAgent requestedSessionId={requestedSessionId} onOpenProfile={() => go("/profile")} onOpenKnowledge={() => go("/knowledge")} />;
  else if (pathname === "/knowledge") page = <KnowledgeBase />;
  else if (pathname === "/history") page = <History onOpenTrainingSession={(id) => go(`/interview?session=${id}`)} />;
  else if (pathname === "/system") page = <SystemStatus />;
  else if (pathname === "/profile") page = <Profile onOpenKnowledge={() => go("/knowledge")} />;
  else if (pathname === "/usage") page = <Usage />;
  else if (pathname === "/settings") page = <Settings onDataCleaned={() => go("/interview")} />;
  else if (pathname === "/admin") page = currentUser?.is_admin ? <AdminDashboard onBack={() => go("/interview")} /> : <Forbidden navigate={navigate} />;
  else page = <NotFound navigate={navigate} />;

  return (
    <div className="app-layout">
      <button type="button" className="mobile-nav-trigger" onClick={() => setMobileNavOpen((value) => !value)} aria-expanded={mobileNavOpen} aria-controls="primary-navigation">
        <span>导航</span>
      </button>
      <aside className={`sidebar${mobileNavOpen ? " is-open" : ""}`} id="primary-navigation">
        <div className="sidebar-brand"><BrandLockup compact /></div>
        <nav className="sidebar-nav" aria-label="主导航">
          {primaryPages.map(([path, label], index) => (
            <button key={path} type="button" className={pathname === path ? "nav-button active" : "nav-button"} onClick={() => go(path)} aria-current={pathname === path ? "page" : undefined}>
              <span className="nav-index">{String(index + 1).padStart(2, "0")}</span><span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-user">
          {userMenuOpen && (
            <div className="user-menu" role="menu">
              <button type="button" onClick={() => go("/profile")}>个人资料</button>
              <button type="button" onClick={() => go("/usage")}>使用额度</button>
              <button type="button" onClick={() => go("/settings")}>设置</button>
              {currentUser?.is_admin && <button type="button" onClick={() => go("/admin")}>管理后台</button>}
              <button type="button" onClick={() => { setUserMenuOpen(false); void logout(); }}>退出登录</button>
            </div>
          )}
          <button type="button" className="user-trigger" onClick={() => setUserMenuOpen((open) => !open)} aria-expanded={userMenuOpen}>
            <span className="user-avatar" aria-hidden="true">{currentUser?.username?.slice(0, 1).toUpperCase() || "U"}</span>
            <span className="user-meta"><strong>{currentUser?.username}</strong><small>{currentUser?.is_admin ? "管理员" : "普通用户"}</small></span>
          </button>
        </div>
      </aside>
      {mobileNavOpen && <button type="button" className="nav-backdrop" aria-label="关闭导航" onClick={() => setMobileNavOpen(false)} />}

      <main className="main-content">
        <header className="top-panel">
          <div><p className="eyebrow">AURORA · MISSION BRIDGE</p><h2>{pageMeta[0]}</h2><p>{pageMeta[1]}</p></div>
          <div className="top-panel-actions">
            {pathname !== "/profile" && pathname !== "/admin" && <button type="button" className="profile-entry-button" onClick={() => go("/profile")}>完善资料</button>}
            <BackgroundJobCenter />
            <button type="button" className={`status-card ${backendStatus === "就绪" ? "is-online" : "is-offline"}`} onClick={() => go("/system")}>
              <span className="status-dot" aria-hidden="true" /><span>服务状态</span><strong>{backendStatus}</strong>
            </button>
          </div>
        </header>
        <div className="content-card">{page}</div>
      </main>
    </div>
  );
}

export default App;
