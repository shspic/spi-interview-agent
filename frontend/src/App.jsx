import { useEffect, useState } from "react";

import apiClient from "./api/client";
import { useAuth } from "./auth/authContext";
import KnowledgeBase from "./pages/KnowledgeBase";
import InterviewAgent from "./pages/InterviewAgent";
import History from "./pages/History";
import SystemStatus from "./pages/SystemStatus";
import AuthPage from "./pages/AuthPage";
import Profile from "./pages/Profile";

import "./index.css";

const pages = [
  {
    key: "interview-agent",
    label: "面试 Agent",
    description: "从资料准备到面试、评价、改进复练和简历表达的一体化训练工作台。",
  },
  {
    key: "knowledge",
    label: "知识库管理",
    description: "统一管理资料上传、索引状态和知识库重建。",
    component: <KnowledgeBase />,
  },
  {
    key: "history",
    label: "历史记录",
    description: "查看面试训练记录以及原有问答、岗位分析和模拟面试历史。",
  },
  {
    key: "system",
    label: "系统状态",
    description: "查看后端、数据库、API Key 与向量索引运行状态。",
    component: <SystemStatus />,
  },
];

const profilePage = {
  key: "profile",
  label: "我的资料",
  description: "维护个人介绍、技术栈、资料文件分类和当前目标岗位。",
};

function App() {
  const { currentUser, isAuthenticated, isLoading, logout } = useAuth();
  const [activePage, setActivePage] = useState("interview-agent");
  const [backendStatus, setBackendStatus] = useState("检查中");
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [requestedSessionId, setRequestedSessionId] = useState(null);

  const currentPage =
    activePage === "profile"
      ? profilePage
      : pages.find((page) => page.key === activePage);

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }

    const checkBackendHealth = async () => {
      try {
        const response = await apiClient.get("/api/health");

        if (response.data?.status === "ok") {
          setBackendStatus("ok");
        } else {
          setBackendStatus("异常");
        }
      } catch (error) {
        console.error("health check error:", error);
        setBackendStatus("连接失败");
      }
    };

    checkBackendHealth();
  }, [isAuthenticated]);

  if (isLoading) {
    return (
      <main className="auth-page">
        <div className="auth-loading" role="status">
          正在验证登录状态...
        </div>
      </main>
    );
  }

  if (!isAuthenticated) {
    return <AuthPage />;
  }

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark">AI</span>
          <div>
            <p className="sidebar-kicker">NO.1 Agent Console</p>
            <h1 className="sidebar-title">SPI面试Agent</h1>
          </div>
        </div>

        <nav className="sidebar-nav">
          {pages.map((page, index) => (
            <button
              key={page.key}
              type="button"
              className={
                activePage === page.key ? "nav-button active" : "nav-button"
              }
              onClick={() => setActivePage(page.key)}
            >
              <span className="nav-index">
                {String(index + 1).padStart(2, "0")}
              </span>
              <span>{page.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-user">
          {userMenuOpen && (
            <div className="user-menu">
              <button
                type="button"
                onClick={() => {
                  setActivePage("profile");
                  setUserMenuOpen(false);
                }}
              >
                我的资料
              </button>
              <button type="button" disabled title="后续开放">
                用量查看 <span>后续开放</span>
              </button>
              <button type="button" disabled title="后续开放">
                设置 <span>后续开放</span>
              </button>
              <button
                type="button"
                onClick={() => {
                  setUserMenuOpen(false);
                  logout();
                }}
              >
                退出登录
              </button>
            </div>
          )}

          <button
            type="button"
            className="user-trigger"
            onClick={() => setUserMenuOpen((open) => !open)}
            aria-expanded={userMenuOpen}
          >
            <span className="user-avatar" aria-hidden="true">
              {currentUser?.username?.slice(0, 1).toUpperCase() || "U"}
            </span>
            <span className="user-meta">
              <strong>{currentUser?.username}</strong>
              <small>已登录</small>
            </span>
          </button>
        </div>
      </aside>

      <main className="main-content">
        <header className="top-panel">
          <div>
            <p className="eyebrow">AI Interview Workspace</p>
            <h2>{currentPage?.label}</h2>
            <p>{currentPage?.description}</p>
          </div>

          <div className="top-panel-actions">
            {activePage !== "profile" && (
              <button
                type="button"
                className="profile-entry-button"
                onClick={() => setActivePage("profile")}
              >
                完善资料
              </button>
            )}

            <div
              className={
                backendStatus === "ok"
                  ? "status-card is-online"
                  : "status-card is-offline"
              }
            >
              <span className="status-dot" />
              <span>后端状态</span>
              <strong>{backendStatus}</strong>
            </div>
          </div>
        </header>

        <div className="content-card">
          {activePage === "profile" ? (
            <Profile onOpenKnowledge={() => setActivePage("knowledge")} />
          ) : activePage === "interview-agent" ? (
            <InterviewAgent
              requestedSessionId={requestedSessionId}
              onOpenProfile={() => setActivePage("profile")}
              onOpenKnowledge={() => setActivePage("knowledge")}
            />
          ) : activePage === "history" ? (
            <History
              onOpenTrainingSession={(sessionId) => {
                setRequestedSessionId(sessionId);
                setActivePage("interview-agent");
              }}
            />
          ) : (
            currentPage?.component
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
