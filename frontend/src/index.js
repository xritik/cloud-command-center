import { StrictMode, useState, useEffect } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Auth from "./Auth";
import Setup from "./Setup";
import Profile from "./Profile";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";

// ── Logout confirmation popup ─────────────────────────────────────────────────
function LogoutModal({ onKeep, onDelete, onCancel }) {
  const S = {
    bg:"#050e09", bgPanel:"#040d07", bgCard:"#070f0a",
    border:"#0f2a1a", border2:"#1e3a2e",
    green:"#00e5a0", greenDim:"#4ade80", greenMid:"#2d6b4a",
    text:"#e2fef0", textMid:"#c8e6d8", textFaint:"#2d6b4a",
    red:"#ff4d6d", mono:"'IBM Plex Mono','Courier New',monospace",
  };
  return (
    <div style={{ position:"fixed", inset:0, background:"#000000cc", zIndex:999, display:"flex", alignItems:"center", justifyContent:"center", fontFamily:S.mono, padding:16 }}>
      <div style={{ background:S.bgPanel, border:`1px solid ${S.border2}`, borderRadius:16, padding:"28px 24px", maxWidth:420, width:"100%", boxShadow:`0 0 40px #00000088` }}>

        <div style={{ fontSize:16, color:S.text, fontWeight:700, marginBottom:10 }}>Before you go...</div>
        <div style={{ fontSize:13, color:S.textMid, lineHeight:1.75, marginBottom:20 }}>
          Do you want to <strong style={{ color:S.green }}>keep your AWS credentials</strong> saved in our database for next time?
        </div>

        <div style={{ background:S.bgCard, border:`1px solid ${S.border}`, borderRadius:10, padding:"12px 14px", marginBottom:20, fontSize:11, color:S.textFaint, lineHeight:1.6 }}>
          <strong style={{ color:S.greenDim }}>Keep:</strong> Your AWS keys stay encrypted in Atlas — login and query instantly next time.<br/>
          <strong style={{ color:"#fbbf24" }}>Delete:</strong> AWS credentials removed from Atlas. Your username and password remain safe.
        </div>

        <div style={{ display:"flex", flexDirection:"column", gap:10 }}>
          <button onClick={onKeep}
            style={{ padding:"12px 0", background:S.green, border:"none", borderRadius:10, cursor:"pointer", color:S.bg, fontSize:12, fontWeight:700, fontFamily:S.mono, letterSpacing:1, transition:"all 0.2s" }}>
            ✓ YES, KEEP MY CREDENTIALS
          </button>
          <button onClick={onDelete}
            style={{ padding:"12px 0", background:"none", border:"1px solid #fbbf24", borderRadius:10, cursor:"pointer", color:"#fbbf24", fontSize:12, fontWeight:700, fontFamily:S.mono, letterSpacing:1, transition:"all 0.2s" }}>
            🗑 NO, DELETE MY AWS CREDENTIALS
          </button>
          <button onClick={onCancel}
            style={{ padding:"10px 0", background:"none", border:`1px solid ${S.border}`, borderRadius:10, cursor:"pointer", color:S.textFaint, fontSize:11, fontFamily:S.mono, letterSpacing:1 }}>
            CANCEL — STAY LOGGED IN
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Root component ────────────────────────────────────────────────────────────
function Root() {
  const [token, setToken]           = useState(() => localStorage.getItem("aqp_token") || "");
  const [username, setUsername]     = useState(() => localStorage.getItem("aqp_user") || "");
  const [page, setPage]             = useState("loading"); // loading | auth | setup | console | profile
  const [showLogoutModal, setShowLogoutModal] = useState(false);

  // Check if user has AWS accounts after login
  useEffect(() => {
    if (!token) { setPage("auth"); return; }
    fetch(`${BACKEND_URL}/accounts`, {
      headers: { "Authorization": `Bearer ${token}` }
    })
      .then(r => {
        if (r.status === 401) { handleForceLogout(); return null; }
        return r.json();
      })
      .then(data => {
        if (!data) return;
        setPage(data.count > 0 ? "console" : "setup");
      })
      .catch(() => setPage("setup")); // if backend down still show setup
  }, [token]);

  const handleLogin = (tok, user) => {
    localStorage.setItem("aqp_token", tok);
    localStorage.setItem("aqp_user", user);
    setToken(tok);
    setUsername(user);
    // page will update via useEffect above
  };

  const handleForceLogout = () => {
    localStorage.removeItem("aqp_token");
    localStorage.removeItem("aqp_user");
    setToken(""); setUsername(""); setPage("auth");
  };

  const handleLogoutRequest = () => {
    setShowLogoutModal(true);
  };

  const handleKeepAndLogout = () => {
    // Keep credentials, just logout
    setShowLogoutModal(false);
    localStorage.removeItem("aqp_token");
    localStorage.removeItem("aqp_user");
    setToken(""); setUsername(""); setPage("auth");
  };

  const handleDeleteAndLogout = async () => {
    // Delete AWS credentials only, keep username/password
    try {
      await fetch(`${BACKEND_URL}/profile/credentials`, {
        method: "DELETE",
        headers: { "Authorization": `Bearer ${token}` }
      });
    } catch(e) { /* proceed anyway */ }
    setShowLogoutModal(false);
    localStorage.removeItem("aqp_token");
    localStorage.removeItem("aqp_user");
    setToken(""); setUsername(""); setPage("auth");
  };

  const handleSetupComplete = () => {
    setPage("console");
  };

  const handleUsernameChange = (newToken, newUsername) => {
    localStorage.setItem("aqp_token", newToken);
    localStorage.setItem("aqp_user", newUsername);
    setToken(newToken);
    setUsername(newUsername);
  };

  if (page === "loading") {
    return (
      <div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:"100vh", background:"#050e09", fontFamily:"monospace", color:"#00e5a0", fontSize:12, letterSpacing:2 }}>
        LOADING...
      </div>
    );
  }

  return (
    <>
      {showLogoutModal && (
        <LogoutModal
          onKeep={handleKeepAndLogout}
          onDelete={handleDeleteAndLogout}
          onCancel={() => setShowLogoutModal(false)}
        />
      )}

      {page === "auth" && (
        <Auth onLogin={handleLogin} />
      )}

      {page === "setup" && (
        <Setup token={token} username={username} onComplete={handleSetupComplete} />
      )}

      {page === "profile" && (
        <Profile
          token={token}
          username={username}
          onBack={() => setPage("console")}
          onLogout={handleLogoutRequest}
          onUsernameChange={handleUsernameChange}
        />
      )}

      {page === "console" && (
        <App
          token={token}
          username={username}
          onLogout={handleLogoutRequest}
          onProfile={() => setPage("profile")}
        />
      )}
    </>
  );
}

createRoot(document.getElementById("root")).render(
  <StrictMode><Root /></StrictMode>
);