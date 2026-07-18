import { useEffect, useState } from "react";

import apiClient from "./api/client";
import { useAuth } from "./auth/authContext";
import KnowledgeBase from "./pages/KnowledgeBase";
import JobAnalysis from "./pages/JobAnalysis";
import Agent from "./pages/Agent";
import Chat from "./pages/Chat";
import Interview from "./pages/Interview";
import History from "./pages/History";
import SystemStatus from "./pages/SystemStatus";
import AuthPage from "./pages/AuthPage";
import Profile from "./pages/Profile";

import "./index.css";

const pages = [
  {
    key: "knowledge",
    label: "知识库管理",
    description: "统一管理资料上传、索引状态和知识库重建。",
    component: <KnowledgeBase />,
  },
  {
    key: "system",
    label: "系统状态",
    description: "查看后端、数据库、API Key 与向量索引运行状态。",
    component: <SystemStatus />,
  },
  {
    key: "job",
    label: "岗位分析",
    description: "结合本地知识库与岗位信息，提炼匹配点和面试重点。",
    component: <JobAnalysis />,
  },
  {
    key: "agent",
    label: "LangGraph Agent",
    description: "在本地知识库、联网搜索与混合检索之间智能路由。",
    component: <Agent />,
  },
  {
    key: "chat",
    label: "自由问答",
    description: "围绕个人资料、项目经历和技术笔记进行 RAG 问答。",
    component: <Chat />,
  },
  {
    key: "interview",
    label: "模拟面试",
    description: "生成面试题、评估回答，并沉淀可复盘的面试记录。",
    component: <Interview />,
  },
  {
    key: "history",
    label: "历史记录",
    description: "检索问答、岗位分析、Agent 和模拟面试的历史结果。",
    component: <History />,
  },
];

const profilePage = {
  key: "profile",
  label: "我的资料",
  description: "维护个人介绍、技术栈、资料文件分类和当前目标岗位。",
};

function App() {
  const { currentUser, isAuthenticated, isLoading, logout } = useAuth();
  const [activePage, setActivePage] = useState("knowledge");
  const [backendStatus, setBackendStatus] = useState("检查中");
  const [userMenuOpen, setUserMenuOpen] = useState(false);

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
          ) : (
            currentPage?.component
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
