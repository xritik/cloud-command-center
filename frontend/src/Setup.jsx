import { useState } from "react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";

const S = {
  bg:"#050e09", bgPanel:"#040d07", bgCard:"#070f0a",
  border:"#0f2a1a", border2:"#1e3a2e",
  green:"#00e5a0", greenDim:"#4ade80", greenMid:"#2d6b4a",
  text:"#e2fef0", textMid:"#c8e6d8", textFaint:"#2d6b4a",
  red:"#ff4d6d", mono:"'IBM Plex Mono','Courier New',monospace",
};

const REGIONS = [
  "ap-south-1","ap-south-2","ap-southeast-1","ap-southeast-2",
  "ap-northeast-1","ap-northeast-2","ap-northeast-3",
  "us-east-1","us-east-2","us-west-1","us-west-2",
  "eu-west-1","eu-west-2","eu-west-3","eu-central-1",
  "ca-central-1","sa-east-1","af-south-1","me-south-1"
];

export default function Setup({ token, username, onComplete }) {
  const [label, setLabel]         = useState("My AWS Account");
  const [accessKey, setAccessKey] = useState("");
  const [secretKey, setSecretKey] = useState("");
  const [region, setRegion]       = useState("ap-south-1");
  const [showSecret, setShowSecret] = useState(false);
  const [loading, setLoading]     = useState(false);
  const [error, setError]         = useState("");
  const [testing, setTesting]     = useState(false);
  const [testResult, setTestResult] = useState(null);

  const testCreds = async () => {
    if (!accessKey.trim() || !secretKey.trim()) { setError("Fill in both keys first."); return; }
    setTesting(true); setError(""); setTestResult(null);
    try {
      const res = await fetch(`${BACKEND_URL}/accounts/add`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify({ label, access_key: accessKey, secret_key: secretKey, region }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Failed");
      setTestResult({ valid: true, account_id: data.account_id });
      setTimeout(() => onComplete(), 800);
    } catch (e) {
      setError(e.message);
      setTestResult({ valid: false });
    } finally {
      setTesting(false);
    }
  };

  const inp = (val, set, type="text", ph="", show=null, setShow=null) => (
    <div style={{ position:"relative" }}>
      <input
        type={show === false ? "password" : "text"}
        value={val}
        onChange={e => set(e.target.value)}
        placeholder={ph}
        style={{ width:"100%", background:S.bgCard, border:`1px solid ${S.border2}`, borderRadius:8, padding:"12px 40px 12px 14px", color:S.text, fontSize:14, outline:"none", fontFamily:S.mono, boxSizing:"border-box", transition:"border-color 0.2s" }}
        onFocus={e => e.target.style.borderColor=S.greenMid}
        onBlur={e  => e.target.style.borderColor=S.border2}
      />
      {setShow && (
        <span onClick={() => setShow(!show)}
          style={{ position:"absolute", right:12, top:"50%", transform:"translateY(-50%)", cursor:"pointer", color:S.greenMid, fontSize:13, userSelect:"none" }}>
          {show ? "🙈" : "👁"}
        </span>
      )}
    </div>
  );

  return (
    <div style={{ display:"flex", alignItems:"center", justifyContent:"center", minHeight:"100vh", background:S.bg, fontFamily:S.mono, padding:16 }}>
      <div style={{ position:"fixed", inset:0, backgroundImage:`linear-gradient(${S.border} 1px,transparent 1px),linear-gradient(90deg,${S.border} 1px,transparent 1px)`, backgroundSize:"40px 40px", opacity:0.3, pointerEvents:"none" }} />

      <div style={{ width:"100%", maxWidth:480, position:"relative", zIndex:1 }}>
        {/* Header */}
        <div style={{ textAlign:"center", marginBottom:28 }}>
          <div style={{ fontSize:"clamp(22px,6vw,32px)", color:S.green, fontWeight:700, letterSpacing:3, textShadow:`0 0 20px ${S.green}44` }}>⬡ AWS</div>
          <div style={{ fontSize:11, color:S.greenMid, letterSpacing:2, marginTop:4 }}>CONNECT YOUR AWS ACCOUNT</div>
          <div style={{ marginTop:10, fontSize:12, color:S.textFaint }}>
            Hey <strong style={{ color:S.green }}>{username}</strong> — add your AWS credentials to get started
          </div>
        </div>

        {/* Card */}
        <div style={{ background:S.bgPanel, border:`1px solid ${S.border2}`, borderRadius:16, padding:"28px 24px" }}>

          {/* Info banner */}
          <div style={{ background:"#0a2a1a", border:`1px solid ${S.border2}`, borderRadius:8, padding:"10px 14px", marginBottom:20, fontSize:11, color:S.greenMid, lineHeight:1.6 }}>
            🔒 Your credentials are <strong style={{ color:S.green }}>AES-256 encrypted</strong> before being stored in our database. We never store them in plain text.
          </div>

          {/* Label */}
          <div style={{ marginBottom:14 }}>
            <div style={{ fontSize:10, color:S.greenMid, letterSpacing:1, marginBottom:6 }}>ACCOUNT LABEL</div>
            {inp(label, setLabel, "text", "e.g. Production, Dev, Client-XYZ")}
          </div>

          {/* Access Key */}
          <div style={{ marginBottom:14 }}>
            <div style={{ fontSize:10, color:S.greenMid, letterSpacing:1, marginBottom:6 }}>AWS ACCESS KEY ID</div>
            {inp(accessKey, setAccessKey, "text", "AKIA...")}
          </div>

          {/* Secret Key */}
          <div style={{ marginBottom:14 }}>
            <div style={{ fontSize:10, color:S.greenMid, letterSpacing:1, marginBottom:6 }}>AWS SECRET ACCESS KEY</div>
            {inp(secretKey, setSecretKey, "password", "••••••••••••••••", showSecret, setShowSecret)}
          </div>

          {/* Region */}
          <div style={{ marginBottom:22 }}>
            <div style={{ fontSize:10, color:S.greenMid, letterSpacing:1, marginBottom:6 }}>DEFAULT REGION</div>
            <select value={region} onChange={e => setRegion(e.target.value)}
              style={{ width:"100%", background:S.bgCard, border:`1px solid ${S.border2}`, borderRadius:8, padding:"12px 14px", color:S.text, fontSize:13, outline:"none", fontFamily:S.mono, cursor:"pointer" }}>
              {REGIONS.map(r => <option key={r} value={r} style={{ background:S.bgCard }}>{r}</option>)}
            </select>
          </div>

          {/* Error */}
          {error && (
            <div style={{ background:"#1a0509", border:"1px solid #4a1525", borderRadius:8, padding:"10px 14px", marginBottom:14, fontSize:12, color:S.red }}>
              ✕ {error}
            </div>
          )}

          {/* Test result */}
          {testResult?.valid && (
            <div style={{ background:"#0a1f12", border:`1px solid ${S.border2}`, borderRadius:8, padding:"10px 14px", marginBottom:14, fontSize:12, color:S.green }}>
              ✓ Connected! Account ID: {testResult.account_id} — redirecting...
            </div>
          )}

          {/* Submit */}
          <button onClick={testCreds} disabled={loading || testing || testResult?.valid}
            style={{ width:"100%", padding:"14px 0", background: (loading||testing||testResult?.valid) ? S.bgCard : S.green, border:"none", borderRadius:10, cursor:(loading||testing||testResult?.valid)?"not-allowed":"pointer", color:(loading||testing||testResult?.valid)?S.greenMid:S.bg, fontSize:13, fontWeight:700, fontFamily:S.mono, letterSpacing:1, transition:"all 0.2s" }}>
            {testing ? "Verifying credentials..." : testResult?.valid ? "✓ Connected!" : "CONNECT & CONTINUE →"}
          </button>

          <div style={{ textAlign:"center", marginTop:14, fontSize:11, color:S.textFaint }}>
            You can add more accounts later from the console
          </div>
        </div>

        <div style={{ textAlign:"center", marginTop:16, fontSize:10, color:S.border2 }}>
          Powered by Groq · AWS Boto3 · MongoDB Atlas
        </div>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700&display=swap');
        * { box-sizing:border-box; }
        input::placeholder { color:${S.greenMid}; opacity:0.5; }
        button:not(:disabled):active { transform:scale(0.98); }
      `}</style>
    </div>
  );
}