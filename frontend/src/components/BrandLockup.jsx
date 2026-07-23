function BrandLockup({ compact = false }) {
  return (
    <div className={compact ? "brand-lockup compact" : "brand-lockup"}>
      <img src="/aurora-logo.svg" alt="AURORA 环轨标志" />
      <div>
        <strong>AURORA</strong>
        <span>AI Interview Intelligence</span>
        {!compact && <small>让潜力被看见，让成长有迹可循</small>}
      </div>
    </div>
  );
}

export default BrandLockup;
