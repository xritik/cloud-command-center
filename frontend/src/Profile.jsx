import { useState, useEffect } from "react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";

const S = {
  bg:"#050e09", bgPanel:"#040d07", bgCard:"#070f0a",
  border:"#0f2a1a", border2:"#1e3a2e",
  green:"#00e5a0", greenDim:"#4ade80", greenMid:"#2d6b4a",
  text:"#e2fef0", textMid:"#c8e6d8", textFaint:"#2d6b4a",
  red:"#ff4d6d", amber:"#fbbf24",
  mono:"'IBM Plex Mono','Courier New',monospace",
};

const REGIONS = [
  "ap-south-1","ap-south-2","ap-southeast-1","ap-southeast-2",
  "ap-northeast-1","ap-northeast-2","ap-northeast-3",
  "us-east-1","us-east-2","us-west-1","us-west-2",
  "eu-west-1","eu-west-2","eu-west-3","eu-central-1",
  "ca-central-1","sa-east-1","af-south-1","me-south-1"
];

const Field = ({ label, children }) => (
  <div style={{ marginBottom:14 }}>
    <div style={{ fontSize:10, color:S.greenMid, letterSpacing:1, marginBottom:6 }}>{label}</div>
    {children}
  </div>
);

const Input = ({ value, onChange, type="text", placeholder="", show=null, setShow=null, disabled=false }) => (
  <div style={{ position:"relative" }}>
    <input
      type={show === false ? "password" : "text"}
      value={value} onChange={onChange} placeholder={placeholder} disabled={disabled}
      style={{ width:"100%", background: disabled ? "#030806" : S.bgCard, border:`1px solid ${S.border2}`, borderRadius:8, padding:"11px 40px 11px 14px", color: disabled ? S.greenMid : S.text, fontSize:13, outline:"none", fontFamily:S.mono, boxSizing:"border-box", transition:"border-color 0.2s", cursor: disabled ? "not-allowed" : "text" }}
      onFocus={e => !disabled && (e.target.style.borderColor=S.greenMid)}
      onBlur={e  => e.target.style.borderColor=S.border2}
    />
    {setShow && (
      <span onClick={() => setShow(!show)} style={{ position:"absolute", right:12, top:"50%", transform:"translateY(-50%)", cursor:"pointer", color:S.greenMid, fontSize:12, userSelect:"none" }}>
        {show ? "🙈" : "👁"}
      </span>
    )}
  </div>
);

const Btn = ({ onClick, disabled, children, variant="primary", small=false }) => {
  const bg = variant === "danger" ? (disabled ? "#1a0509" : "#ff4d6d") : variant === "secondary" ? "transparent" : (disabled ? S.bgCard : S.green);
  const col = variant === "danger" ? (disabled ? "#4a1525" : S.bg) : variant === "secondary" ? S.greenDim : (disabled ? S.greenMid : S.bg);
  const brd = variant === "secondary" ? `1px solid ${S.border2}` : variant === "danger" ? `1px solid #4a1525` : "none";
  return (
    <button onClick={onClick} disabled={disabled}
      style={{ padding: small ? "7px 14px" : "11px 20px", background:bg, border:brd, borderRadius:8, cursor:disabled?"not-allowed":"pointer", color:col, fontSize: small ? 11 : 12, fontWeight:700, fontFamily:S.mono, letterSpacing:1, transition:"all 0.2s" }}>
      {children}
    </button>
  );
};

const Toast = ({ msg, type }) => msg ? (
  <div style={{ position:"fixed", bottom:24, right:24, background: type==="error" ? "#1a0509" : "#0a1f12", border:`1px solid ${type==="error" ? "#4a1525" : S.border2}`, borderRadius:10, padding:"12px 18px", fontSize:12, color: type==="error" ? S.red : S.green, zIndex:999, fontFamily:S.mono }}>
    {type === "error" ? "✕ " : "✓ "}{msg}
  </div>
) : null;

export default function Profile({ token, username, onBack, onLogout, onUsernameChange }) {
  const [tab, setTab]           = useState("accounts"); // accounts | password | username
  const [accounts, setAccounts] = useState([]);
  const [loadingAcc, setLoadingAcc] = useState(true);

  // Password change
  const [curPwd, setCurPwd]     = useState(""); const [showCur, setShowCur] = useState(false);
  const [newPwd, setNewPwd]     = useState(""); const [showNew, setShowNew] = useState(false);
  const [confPwd, setConfPwd]   = useState(""); const [showConf, setShowConf] = useState(false);

  // Username change
  const [newUser, setNewUser]   = useState("");
  const [userPwd, setUserPwd]   = useState(""); const [showUP, setShowUP] = useState(false);

  // Add account
  const [showAdd, setShowAdd]   = useState(false);
  const [addLabel, setAddLabel] = useState("");
  const [addAK, setAddAK]       = useState("");
  const [addSK, setAddSK]       = useState(""); const [showAddSK, setShowAddSK] = useState(false);
  const [addRegion, setAddRegion] = useState("ap-south-1");

  // Edit account
  const [editId, setEditId]     = useState(null);
  const [editLabel, setEditLabel] = useState("");
  const [editAK, setEditAK]     = useState("");
  const [editSK, setEditSK]     = useState(""); const [showEditSK, setShowEditSK] = useState(false);
  const [editRegion, setEditRegion] = useState("");

  const [loading, setLoading]   = useState(false);
  const [toast, setToast]       = useState({ msg:"", type:"success" });

  const showToast = (msg, type="success") => {
    setToast({ msg, type });
    setTimeout(() => setToast({ msg:"", type:"success" }), 3000);
  };

  const api = async (path, method="GET", body=null) => {
    const res = await fetch(`${BACKEND_URL}${path}`, {
      method,
      headers: { "Content-Type":"application/json", "Authorization":`Bearer ${token}` },
      ...(body ? { body: JSON.stringify(body) } : {})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Request failed");
    return data;
  };

  useEffect(() => {
    api("/accounts").then(d => setAccounts(d.accounts)).catch(() => {}).finally(() => setLoadingAcc(false));
  }, []);

  const changePassword = async () => {
    if (newPwd !== confPwd) { showToast("Passwords don't match", "error"); return; }
    if (newPwd.length < 6) { showToast("Min 6 characters", "error"); return; }
    setLoading(true);
    try {
      await api("/profile/password", "PUT", { current_password: curPwd, new_password: newPwd });
      showToast("Password updated!");
      setCurPwd(""); setNewPwd(""); setConfPwd("");
    } catch(e) { showToast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const changeUsername = async () => {
    setLoading(true);
    try {
      const data = await api("/profile/username", "PUT", { new_username: newUser, current_password: userPwd });
      showToast("Username updated!");
      onUsernameChange(data.token, data.username);
      setNewUser(""); setUserPwd("");
    } catch(e) { showToast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const addAccount = async () => {
    setLoading(true);
    try {
      await api("/accounts/add", "POST", { label: addLabel, access_key: addAK, secret_key: addSK, region: addRegion });
      showToast("Account added!");
      setShowAdd(false); setAddLabel(""); setAddAK(""); setAddSK("");
      const d = await api("/accounts");
      setAccounts(d.accounts);
    } catch(e) { showToast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const deleteAccount = async (id) => {
    if (!window.confirm("Delete this AWS account?")) return;
    setLoading(true);
    try {
      await api(`/accounts/${id}`, "DELETE");
      showToast("Account deleted");
      setAccounts(prev => prev.filter(a => a.id !== id));
    } catch(e) { showToast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const saveEdit = async () => {
    setLoading(true);
    try {
      const body = {};
      if (editLabel)  body.label      = editLabel;
      if (editAK)     body.access_key = editAK;
      if (editSK)     body.secret_key = editSK;
      if (editRegion) body.region     = editRegion;
      await api(`/accounts/${editId}`, "PUT", body);
      showToast("Account updated!");
      setEditId(null);
      const d = await api("/accounts");
      setAccounts(d.accounts);
    } catch(e) { showToast(e.message, "error"); }
    finally { setLoading(false); }
  };

  const TABS = ["accounts","password","username"];

  return (
    <div style={{ display:"flex", flexDirection:"column", height:"100vh", background:S.bg, fontFamily:S.mono, color:S.textMid, overflow:"hidden" }}>

      {/* Header */}
      <div style={{ padding:"12px 20px", borderBottom:`1px solid ${S.border}`, display:"flex", alignItems:"center", gap:12, background:S.bgPanel, flexShrink:0 }}>
        <button onClick={onBack} style={{ background:"none", border:`1px solid ${S.border2}`, borderRadius:6, padding:"5px 12px", cursor:"pointer", color:S.greenDim, fontSize:11, fontFamily:S.mono, letterSpacing:1 }}>← BACK</button>
        <div style={{ flex:1 }}>
          <div style={{ fontSize:12, color:S.green, fontWeight:700, letterSpacing:2 }}>PROFILE SETTINGS</div>
          <div style={{ fontSize:10, color:S.textFaint }}>Manage your account · {username}</div>
        </div>
        <button onClick={onLogout} style={{ background:"none", border:"1px solid #4a1525", borderRadius:6, padding:"5px 12px", cursor:"pointer", color:S.red, fontSize:11, fontFamily:S.mono, letterSpacing:1 }}>LOGOUT</button>
      </div>

      {/* Tabs */}
      <div style={{ display:"flex", gap:4, padding:"12px 20px 0", borderBottom:`1px solid ${S.border}`, background:S.bgPanel, flexShrink:0 }}>
        {TABS.map(t => (
          <button key={t} onClick={() => setTab(t)}
            style={{ padding:"8px 16px", borderRadius:"6px 6px 0 0", border:`1px solid ${tab===t ? S.border2 : "transparent"}`, borderBottom: tab===t ? `1px solid ${S.bg}` : "none", background: tab===t ? S.bg : "transparent", color: tab===t ? S.green : S.greenMid, fontSize:11, fontWeight:700, fontFamily:S.mono, cursor:"pointer", letterSpacing:1, marginBottom:-1 }}>
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex:1, overflowY:"auto", padding:"24px 20px" }}>

        {/* ── ACCOUNTS TAB ── */}
        {tab === "accounts" && (
          <div style={{ maxWidth:600 }}>
            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:16 }}>
              <div style={{ fontSize:11, color:S.textFaint, letterSpacing:1 }}>AWS ACCOUNTS ({accounts.length})</div>
              <Btn onClick={() => setShowAdd(!showAdd)} small variant="secondary">{showAdd ? "✕ CANCEL" : "+ ADD ACCOUNT"}</Btn>
            </div>

            {/* Add account form */}
            {showAdd && (
              <div style={{ background:S.bgPanel, border:`1px solid ${S.border2}`, borderRadius:12, padding:"18px 16px", marginBottom:16 }}>
                <div style={{ fontSize:10, color:S.green, letterSpacing:2, marginBottom:14 }}>NEW AWS ACCOUNT</div>
                <Field label="LABEL"><Input value={addLabel} onChange={e=>setAddLabel(e.target.value)} placeholder="e.g. Production" /></Field>
                <Field label="ACCESS KEY ID"><Input value={addAK} onChange={e=>setAddAK(e.target.value)} placeholder="AKIA..." /></Field>
                <Field label="SECRET ACCESS KEY"><Input value={addSK} onChange={e=>setAddSK(e.target.value)} show={showAddSK} setShow={setShowAddSK} placeholder="••••••••" /></Field>
                <Field label="DEFAULT REGION">
                  <select value={addRegion} onChange={e=>setAddRegion(e.target.value)}
                    style={{ width:"100%", background:S.bgCard, border:`1px solid ${S.border2}`, borderRadius:8, padding:"11px 14px", color:S.text, fontSize:13, outline:"none", fontFamily:S.mono, cursor:"pointer" }}>
                    {REGIONS.map(r => <option key={r} value={r} style={{ background:S.bgCard }}>{r}</option>)}
                  </select>
                </Field>
                <Btn onClick={addAccount} disabled={loading || !addAK || !addSK}>
                  {loading ? "Verifying..." : "SAVE ACCOUNT"}
                </Btn>
              </div>
            )}

            {/* Account list */}
            {loadingAcc ? (
              <div style={{ color:S.textFaint, fontSize:12 }}>Loading accounts...</div>
            ) : accounts.length === 0 ? (
              <div style={{ color:S.textFaint, fontSize:12, padding:"20px 0" }}>No AWS accounts added yet.</div>
            ) : accounts.map(acc => (
              <div key={acc.id} style={{ background:S.bgPanel, border:`1px solid ${editId===acc.id ? S.border2 : S.border}`, borderRadius:12, padding:"14px 16px", marginBottom:10 }}>
                {editId === acc.id ? (
                  <>
                    <div style={{ fontSize:10, color:S.green, letterSpacing:2, marginBottom:12 }}>EDIT ACCOUNT</div>
                    <Field label="LABEL"><Input value={editLabel} onChange={e=>setEditLabel(e.target.value)} placeholder={acc.label} /></Field>
                    <Field label="NEW ACCESS KEY (leave blank to keep)"><Input value={editAK} onChange={e=>setEditAK(e.target.value)} placeholder="AKIA..." /></Field>
                    <Field label="NEW SECRET KEY (leave blank to keep)"><Input value={editSK} onChange={e=>setEditSK(e.target.value)} show={showEditSK} setShow={setShowEditSK} placeholder="••••••••" /></Field>
                    <Field label="REGION">
                      <select value={editRegion || acc.region} onChange={e=>setEditRegion(e.target.value)}
                        style={{ width:"100%", background:S.bgCard, border:`1px solid ${S.border2}`, borderRadius:8, padding:"11px 14px", color:S.text, fontSize:13, outline:"none", fontFamily:S.mono, cursor:"pointer" }}>
                        {REGIONS.map(r => <option key={r} value={r} style={{ background:S.bgCard }}>{r}</option>)}
                      </select>
                    </Field>
                    <div style={{ display:"flex", gap:8 }}>
                      <Btn onClick={saveEdit} disabled={loading} small>SAVE</Btn>
                      <Btn onClick={() => setEditId(null)} small variant="secondary">CANCEL</Btn>
                    </div>
                  </>
                ) : (
                  <div style={{ display:"flex", alignItems:"center", gap:12 }}>
                    <div style={{ flex:1 }}>
                      <div style={{ fontSize:13, color:S.text, fontWeight:700 }}>{acc.label}</div>
                      <div style={{ fontSize:10, color:S.greenMid, marginTop:3 }}>Account: {acc.account_id} · Region: {acc.region}</div>
                      <div style={{ fontSize:10, color:S.textFaint, marginTop:1 }}>Added: {new Date(acc.added_at).toLocaleDateString()}</div>
                    </div>
                    <div style={{ display:"flex", gap:6 }}>
                      <Btn small variant="secondary" onClick={() => { setEditId(acc.id); setEditLabel(acc.label); setEditRegion(acc.region); setEditAK(""); setEditSK(""); }}>EDIT</Btn>
                      <Btn small variant="danger" onClick={() => deleteAccount(acc.id)}>DEL</Btn>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {/* ── PASSWORD TAB ── */}
        {tab === "password" && (
          <div style={{ maxWidth:420 }}>
            <div style={{ fontSize:11, color:S.textFaint, letterSpacing:1, marginBottom:18 }}>CHANGE PASSWORD</div>
            <Field label="CURRENT PASSWORD"><Input value={curPwd} onChange={e=>setCurPwd(e.target.value)} show={showCur} setShow={setShowCur} placeholder="Current password" /></Field>
            <Field label="NEW PASSWORD"><Input value={newPwd} onChange={e=>setNewPwd(e.target.value)} show={showNew} setShow={setShowNew} placeholder="Min 6 characters" /></Field>
            <Field label="CONFIRM NEW PASSWORD"><Input value={confPwd} onChange={e=>setConfPwd(e.target.value)} show={showConf} setShow={setShowConf} placeholder="Repeat new password" /></Field>
            <Btn onClick={changePassword} disabled={loading || !curPwd || !newPwd || !confPwd}>
              {loading ? "Updating..." : "UPDATE PASSWORD →"}
            </Btn>
          </div>
        )}

        {/* ── USERNAME TAB ── */}
        {tab === "username" && (
          <div style={{ maxWidth:420 }}>
            <div style={{ fontSize:11, color:S.textFaint, letterSpacing:1, marginBottom:18 }}>CHANGE USERNAME</div>
            <div style={{ background:"#0a2a1a", border:`1px solid ${S.border2}`, borderRadius:8, padding:"10px 14px", marginBottom:16, fontSize:11, color:S.greenMid }}>
              Current username: <strong style={{ color:S.green }}>{username}</strong>
            </div>
            <Field label="NEW USERNAME"><Input value={newUser} onChange={e=>setNewUser(e.target.value)} placeholder="Min 3 characters" /></Field>
            <Field label="CONFIRM WITH PASSWORD"><Input value={userPwd} onChange={e=>setUserPwd(e.target.value)} show={showUP} setShow={setShowUP} placeholder="Your current password" /></Field>
            <Btn onClick={changeUsername} disabled={loading || !newUser || !userPwd}>
              {loading ? "Updating..." : "UPDATE USERNAME →"}
            </Btn>
          </div>
        )}
      </div>

      <Toast msg={toast.msg} type={toast.type} />

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap');
        * { box-sizing:border-box; }
        ::-webkit-scrollbar { width:4px; }
        ::-webkit-scrollbar-thumb { background:${S.border2}; border-radius:2px; }
        input::placeholder { color:${S.greenMid}; opacity:0.5; }
        button:not(:disabled):active { transform:scale(0.97); }
      `}</style>
    </div>
  );
}