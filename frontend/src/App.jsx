import { useEffect, useState } from "react";

import apiClient from "./api/client";
import Sidebar from "./components/Sidebar";
import KnowledgeBase from "./pages/KnowledgeBase";
import JobAnalysis from "./pages/JobAnalysis";
import Chat from "./pages/Chat";
import Interview from "./pages/Interview";
import History from "./pages/History";
import "./index.css";

function App() {
  const [currentPage, setCurrentPage] = useState("knowledge");
  const [backendStatus, setBackendStatus] = useState("checking");

  useEffect(() => {
    apiClient
      .get("/api/health")
      .then((response) => {
        setBackendStatus(response.data.status);
      })
      .catch(() => {
        setBackendStatus("error");
      });
  }, []);

  const renderPage = () => {
    if (currentPage === "knowledge") return <KnowledgeBase />;
    if (currentPage === "jobs") return <JobAnalysis />;
    if (currentPage === "chat") return <Chat />;
    if (currentPage === "interview") return <Interview />;
    if (currentPage === "history") return <History />;

    return <KnowledgeBase />;
  };

  return (
    <div className="app-layout">
      <Sidebar currentPage={currentPage} onChangePage={setCurrentPage} />

      <main className="main-content">
        <div className="status-bar">
          后端状态：
          <span
            className={
              backendStatus === "ok"
                ? "status-ok"
                : backendStatus === "error"
                ? "status-error"
                : "status-checking"
            }
          >
            {backendStatus}
          </span>
        </div>

        {renderPage()}
      </main>
    </div>
  );
}

export default App;