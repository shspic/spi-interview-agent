function StatePanel({ tone = "neutral", title, description, actionLabel, onAction }) {
  return (
    <div className={`state-panel ${tone}`} role={tone === "error" ? "alert" : "status"}>
      <div>
        <strong>{title}</strong>
        {description && <p>{description}</p>}
      </div>
      {actionLabel && onAction && (
        <button type="button" onClick={onAction}>{actionLabel}</button>
      )}
    </div>
  );
}

export default StatePanel;
