function Sidebar({ currentPage, onChangePage }) {
  const menuItems = [
    { key: "knowledge", label: "知识库管理" },
    { key: "jobs", label: "岗位分析" },
    { key: "chat", label: "自由问答" },
    { key: "interview", label: "模拟面试" },
    { key: "history", label: "历史记录" },
  ];

  return (
    <aside className="sidebar">
      <h2 className="sidebar-title">AI Interview RAG Coach</h2>

      <nav className="sidebar-menu">
        {menuItems.map((item) => (
          <button
            key={item.key}
            className={
              currentPage === item.key
                ? "sidebar-button active"
                : "sidebar-button"
            }
            onClick={() => onChangePage(item.key)}
          >
            {item.label}
          </button>
        ))}
      </nav>
    </aside>
  );
}

export default Sidebar;