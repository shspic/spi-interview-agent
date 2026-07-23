function AuroraTaskLoader({ label, detail = "请保持当前页面打开，完成后将自动更新。" }) {
  if (!label) return null;

  return (
    <div className="aurora-task-loader" role="status" aria-live="polite" aria-busy="true">
      <span className="aurora-loader-orbit" aria-hidden="true">
        <span />
      </span>
      <span className="aurora-loader-copy">
        <strong>{label}</strong>
        <small>{detail}</small>
      </span>
    </div>
  );
}

export default AuroraTaskLoader;
