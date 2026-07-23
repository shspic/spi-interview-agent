import BrandLockup from "./BrandLockup";

const VIDEO_URL = "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260506_081238_406ed0e3-5d83-436e-a512-0bbff7ec5b95.mp4";
const VIDEO_ENABLED = import.meta.env.VITE_DISABLE_AUTH_VIDEO !== "true";
const FEATURES = [
  "基于简历、项目和岗位要求生成针对性问题",
  "追问围绕个人职责、技术决策和可验证结果推进",
  "识别资料冲突与无依据表达，降低面试风险",
  "生成五维评分、优化回答和下一步改进任务",
  "保留训练历史，让每一次成长都有迹可循",
];

function AuthShell({ children, showVideo = true }) {
  const reducedMotion = typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  return (
    <main className="auth-shell">
      <div className="auth-viewport">
        <div className="auth-viewport-media" aria-hidden="true">
          {showVideo && VIDEO_ENABLED && !reducedMotion && (
            <video autoPlay muted loop playsInline preload="metadata">
              <source src={VIDEO_URL} type="video/mp4" />
            </video>
          )}
          <div className="auth-viewport-shade" />
        </div>
        <div className="auth-viewport-content">
          <BrandLockup />
          <div className="auth-story">
            <h1>从真实资料出发，完成一场可复盘的面试训练</h1>
            <p>
              AURORA 面向 AI 应用开发、Python 后端、RAG 与 Agent 岗位，
              将资料准备、模拟面试、证据核验、能力评价和改进复练连接为一条完整路径。
            </p>
          </div>
          <div className="auth-feature-window" tabIndex="0" aria-label="AURORA 训练能力">
            <ul className="auth-feature-list">
              {FEATURES.map((feature, index) => (
                <li key={feature}><span>{String(index + 1).padStart(2, "0")}</span>{feature}</li>
              ))}
            </ul>
          </div>
          <p className="auth-viewport-code">SECURE ACCESS TERMINAL · EVIDENCE-DRIVEN GROWTH</p>
        </div>
      </div>
      <section className="auth-terminal">{children}</section>
    </main>
  );
}

export default AuthShell;
