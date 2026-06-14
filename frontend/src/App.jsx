import { useEffect, useState } from "react";

import apiClient from "./api/client";
import KnowledgeBase from "./pages/KnowledgeBase";
import JobAnalysis from "./pages/JobAnalysis";
import Agent from "./pages/Agent";
import Chat from "./pages/Chat";
import Interview from "./pages/Interview";
import History from "./pages/History";

import "./index.css";

const pages = [
  {
    key: "knowledge",
    label: "知识库管理",
    component: <KnowledgeBase />,
  },
  {
    key: "job",
    label: "岗位分析",
    component: <JobAnalysis />,
  },
  {
    key: "agent",
    label: "LangGraph Agent",
    component: <Agent />,
  },
  {
    key: "chat",
    label: "自由问答",
    component: <Chat />,
  },
  {
    key: "interview",
    label: "模拟面试",
    component: <Interview />,
  },
  {
    key: "history",
    label: "历史记录",
    component: <History />,
  },
];

function App() {
  const [activePage, setActivePage] = useState("knowledge");
  const [backendStatus, setBackendStatus] = useState("检查中");

  const currentPage = pages.find((page) => page.key === activePage);

  useEffect(() => {
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
  }, []);

  return (
    <div className="app-layout">
      <aside className="sidebar">
        <h1 className="sidebar-title">SPI面试Agent</h1>

        <nav className="sidebar-nav">
          {pages.map((page) => (
            <button
              key={page.key}
              type="button"
              className={
                activePage === page.key ? "nav-button active" : "nav-button"
              }
              onClick={() => setActivePage(page.key)}
            >
              {page.label}
            </button>
          ))}
        </nav>
      </aside>

      <main className="main-content">
        <div className="status-card">
          后端状态：
          <strong className={backendStatus === "ok" ? "status-ok" : "status-bad"}>
            {backendStatus}
          </strong>
        </div>

        <div className="content-card">{currentPage?.component}</div>
      </main>
    </div>
  );
}

export default App;