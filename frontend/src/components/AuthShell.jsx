import BrandLockup from "./BrandLockup";

const VIDEO_URL = "https://d8j0ntlcm91z4.cloudfront.net/user_38xzZboKViGWJOttwIXH07lWA1P/hf_20260506_081238_406ed0e3-5d83-436e-a512-0bbff7ec5b95.mp4";
const VIDEO_ENABLED = import.meta.env.VITE_DISABLE_AUTH_VIDEO !== "true";

function AuthShell({ children, showVideo = true }) {
  const reducedMotion = typeof window !== "undefined"
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  return (
    <main className="auth-shell">
      <div className="auth-viewport" aria-hidden="true">
        {showVideo && VIDEO_ENABLED && !reducedMotion && (
          <video autoPlay muted loop playsInline preload="metadata">
            <source src={VIDEO_URL} type="video/mp4" />
          </video>
        )}
        <div className="auth-viewport-shade" />
        <BrandLockup />
        <p>SECURE ACCESS TERMINAL · EVIDENCE-DRIVEN GROWTH</p>
      </div>
      <section className="auth-terminal">{children}</section>
    </main>
  );
}

export default AuthShell;
