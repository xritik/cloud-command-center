import { useState } from "react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";

const S = {
  bg:        "#050e09",
  bgPanel:   "#040d07",
  bgCard:    "#070f0a",
  border:    "#0f2a1a",
  border2:   "#1e3a2e",
  green:     "#00e5a0",
  greenDim:  "#4ade80",
  greenMid:  "#2d6b4a",
  text:      "#e2fef0",
  textMid:   "#c8e6d8",
  textFaint: "#2d6b4a",
  red:       "#ff4d6d",
  mono:      "'IBM Plex Mono', 'Courier New', monospace",
};

export default function Auth({ onLogin }) {
  const [mode, setMode]       = useState("login"); // "login" | "signup"
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState("");

  const submit = async () => {
    setError(""); setSuccess("");
    if (!username.trim() || !password.trim()) {
      setError("Please fill in both fields."); return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/auth/${mode}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Something went wrong");
      setSuccess(data.message);
      setTimeout(() => onLogin(data.token, data.username), 600);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const handleKey = (e) => { if (e.key === "Enter") submit(); };

  return (
    <div style={{ display:"flex", alignItems:"center", justifyContent:"center", minHeight:"100vh", background:S.bg, fontFamily:S.mono, padding:"16px 0", overflowY:"auto" }}>

      {/* Background grid effect */}
      <div style={{ position:"fixed", inset:0, backgroundImage:`linear-gradient(${S.border} 1px, transparent 1px), linear-gradient(90deg, ${S.border} 1px, transparent 1px)`, backgroundSize:"40px 40px", opacity:0.3, pointerEvents:"none" }} />

      <div style={{ width:"100%", maxWidth:420, padding:"0 16px", position:"relative", zIndex:1 }}>

        {/* Logo */}
        <div style={{ textAlign:"center", marginBottom:36 }}>
          <div style={{ fontSize:"clamp(24px, 8vw, 36px)", color:S.green, letterSpacing:4, fontWeight:700, textShadow:`0 0 30px ${S.green}44` }}>⬡ AWS</div>
          <div style={{ fontSize:"clamp(9px, 2.5vw, 11px)", color:S.greenMid, letterSpacing:3, marginTop:6 }}>CLOUD COMMAND CENTER</div>
        </div>

        {/* Card */}
        <div style={{ background:S.bgPanel, border:`1px solid ${S.border2}`, borderRadius:16, padding:"clamp(20px, 5vw, 32px) clamp(16px, 5vw, 28px)", boxShadow:`0 0 40px #00e5a008` }}>

          {/* Tab toggle */}
          <div style={{ display:"flex", marginBottom:28, background:S.bgCard, borderRadius:10, padding:4, border:`1px solid ${S.border}` }}>
            {["login","signup"].map(m => (
              <button key={m} onClick={() => { setMode(m); setError(""); setSuccess(""); }}
                style={{ flex:1, padding:"9px 0", borderRadius:8, border:"none", cursor:"pointer", fontFamily:S.mono, fontSize:12, fontWeight:700, letterSpacing:1, transition:"all 0.2s",
                  background: mode === m ? S.green : "transparent",
                  color:      mode === m ? S.bg    : S.greenMid,
                }}>
                {m.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Fields */}
          <div style={{ marginBottom:16 }}>
            <div style={{ fontSize:10, color:S.greenMid, letterSpacing:1, marginBottom:6 }}>USERNAME</div>
            <input
              value={username}
              onChange={e => setUsername(e.target.value)}
              onKeyDown={handleKey}
              placeholder="e.g. Joy"
              autoFocus
              style={{ width:"100%", background:S.bgCard, border:`1px solid ${S.border2}`, borderRadius:8, padding:"13px 14px", color:S.text, fontSize:16, outline:"none", fontFamily:S.mono, boxSizing:"border-box", transition:"border-color 0.2s" }}
              onFocus={e => e.target.style.borderColor = S.greenMid}
              onBlur={e  => e.target.style.borderColor = S.border2}
            />
          </div>

          <div style={{ marginBottom:24 }}>
            <div style={{ fontSize:10, color:S.greenMid, letterSpacing:1, marginBottom:6 }}>PASSWORD</div>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Min 6 characters"
              style={{ width:"100%", background:S.bgCard, border:`1px solid ${S.border2}`, borderRadius:8, padding:"13px 14px", color:S.text, fontSize:16, outline:"none", fontFamily:S.mono, boxSizing:"border-box", transition:"border-color 0.2s" }}
              onFocus={e => e.target.style.borderColor = S.greenMid}
              onBlur={e  => e.target.style.borderColor = S.border2}
            />
          </div>

          {/* Error / Success */}
          {error && (
            <div style={{ background:"#1a0509", border:`1px solid #4a1525`, borderRadius:8, padding:"10px 14px", marginBottom:16, fontSize:12, color:S.red }}>
              ✕ {error}
            </div>
          )}
          {success && (
            <div style={{ background:"#0a1f12", border:`1px solid ${S.border2}`, borderRadius:8, padding:"10px 14px", marginBottom:16, fontSize:12, color:S.green }}>
              ✓ {success}
            </div>
          )}

          {/* Submit button */}
          <button onClick={submit} disabled={loading}
            style={{ width:"100%", padding:"15px 0", background: loading ? S.bgCard : S.green, border:"none", borderRadius:10, cursor: loading ? "not-allowed" : "pointer", color: loading ? S.greenMid : S.bg, fontSize:13, fontWeight:700, fontFamily:S.mono, letterSpacing:1, transition:"all 0.2s" }}>
            {loading ? "Please wait..." : mode === "login" ? "LOGIN →" : "CREATE ACCOUNT →"}
          </button>

          {/* Switch mode hint */}
          <div style={{ textAlign:"center", marginTop:18, fontSize:11, color:S.textFaint }}>
            {mode === "login"
              ? <>No account? <span onClick={() => { setMode("signup"); setError(""); }} style={{ color:S.greenDim, cursor:"pointer", textDecoration:"underline" }}>Sign up</span></>
              : <>Have an account? <span onClick={() => { setMode("login"); setError(""); }} style={{ color:S.greenDim, cursor:"pointer", textDecoration:"underline" }}>Log in</span></>
            }
          </div>
        </div>

        <div style={{ textAlign:"center", marginTop:20, fontSize:10, color:S.border2 }}>
          Powered by Groq · AWS Boto3 · MongoDB Atlas
        </div>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap');
        * { box-sizing: border-box; }
        input::placeholder { color: ${S.greenMid}; opacity: 0.6; }
        button:not(:disabled):active { transform: scale(0.98); }
        @media (max-width: 480px) {
          * { -webkit-tap-highlight-color: transparent; }
          input, button { touch-action: manipulation; }
        }
      `}</style>
    </div>
  );
}