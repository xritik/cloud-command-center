import { useState, useRef, useEffect, useCallback } from "react";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";

// ── Fully agentic architecture ────────────────────────────────────────────────
// There is no fixed tool list anymore. Every query goes to the backend's
// /agent route, where an LLM generates, validates, and safely executes
// fresh Boto3 code for that specific question. See backend/agent.py.

// ── Single agent call ─────────────────────────────────────────────────────────
const callAgent = async (query, tok, region = "ap-south-1", account = null) => {
  const res = await fetch(`${BACKEND_URL}/agent`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Authorization": `Bearer ${tok}` },
    body: JSON.stringify({
      query,
      region,
      account_id: account?.id || "",
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Agent backend error ${res.status}`);
  }
  return res.json();
};

// ── UI Components ────────────────────────────────────────────────────────────
const S = {
  // colours
  bg:        "#050e09",
  bgPanel:   "#040d07",
  bgCard:    "#040d07",
  bgRow:     "#070f0a",
  border:    "#0f2a1a",
  border2:   "#1e3a2e",
  green:     "#00e5a0",
  greenDim:  "#4ade80",
  greenMid:  "#2d6b4a",
  greenFade: "#1e3a2e",
  text:      "#e2fef0",
  textMid:   "#c8e6d8",
  textDim:   "#7abf96",
  textFaint: "#2d6b4a",
  red:       "#ff4d6d",
  yellow:    "#fbbf24",
  blue:      "#7dd3fc",
  mono:      "'IBM Plex Mono', 'Courier New', monospace",
};

const chip = (state) => {
  const map = { running: S.green, stopped: S.red, pending: S.yellow, terminated: "#555" };
  const c = map[state] || "#888";
  return (
    <span style={{ display:"inline-flex", alignItems:"center", gap:5, padding:"2px 10px", borderRadius:20, background:`${c}18`, border:`1px solid ${c}40`, color:c, fontSize:11, fontFamily:S.mono, fontWeight:600, letterSpacing:1 }}>
      <span style={{ width:6, height:6, borderRadius:"50%", background:c, boxShadow: state==="running" ? `0 0 6px ${c}` : "none" }} />
      {state}
    </span>
  );
};

const cpuColor = (v) => v > 80 ? S.red : v > 60 ? S.yellow : S.green;

const StatusBadge = ({ s }) => {
  const c = s === "ok" ? S.green : s === "not-applicable" ? "#555" : S.red;
  return <span style={{ fontSize:11, color:c, fontFamily:S.mono }}>{s}</span>;
};

// Generic key-value card grid
const KVGrid = ({ pairs }) => (
  <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:8 }}>
    {pairs.map(([k, v]) => (
      <div key={k} style={{ background:"#0a1a12", border:`1px solid ${S.border}`, borderRadius:8, padding:"10px 14px" }}>
        <div style={{ fontSize:10, color:S.greenDim, letterSpacing:1, marginBottom:4 }}>{k.toUpperCase()}</div>
        <div style={{ fontSize:13, color:S.text, fontFamily:S.mono, wordBreak:"break-all" }}>{String(v)}</div>
      </div>
    ))}
  </div>
);

// Render tool result as rich table or card
const ResultTable = ({ data }) => {
  if (!data || typeof data !== "object")
    return <pre style={{ color:S.greenDim, fontSize:12, margin:0 }}>{JSON.stringify(data, null, 2)}</pre>;

  if (data.error)
    return <div style={{ color:S.red, fontSize:12, fontFamily:S.mono }}>{data.error}</div>;

  // Instance list
  if (data.instances !== undefined) {
    if (data.instances.length === 0)
      return <div style={{ color:S.textFaint, fontSize:12, fontFamily:S.mono }}>No instances matched.</div>;
    return (
      <div style={{ overflowX:"auto" }}>
        <table style={{ width:"100%", borderCollapse:"collapse", fontSize:12, fontFamily:S.mono }}>
          <thead>
            <tr style={{ borderBottom:`1px solid ${S.border}` }}>
              {["Name","ID","State","Type","Public IP","Private IP","AZ", data.instances[0]?.cpu_avg !== undefined ? "CPU %" : null]
                .filter(Boolean)
                .map(h => (
                  <th key={h} style={{ padding:"8px 12px", textAlign:"left", color:S.greenDim, fontWeight:600, fontSize:11, letterSpacing:1, whiteSpace:"nowrap" }}>{h}</th>
                ))}
            </tr>
          </thead>
          <tbody>
            {data.instances.map((inst, i) => (
              <tr key={inst.id} style={{ borderBottom:`1px solid #0d1f17`, background: i%2===0 ? "transparent" : S.bgRow }}>
                <td style={{ padding:"8px 12px", color:S.text, fontWeight:600 }}>{inst.name}</td>
                <td style={{ padding:"8px 12px", color:"#52c77a" }}>{inst.id}</td>
                <td style={{ padding:"8px 12px" }}>{chip(inst.state)}</td>
                <td style={{ padding:"8px 12px", color:S.textDim }}>{inst.type}</td>
                <td style={{ padding:"8px 12px", color:S.blue }}>{inst.public_ip}</td>
                <td style={{ padding:"8px 12px", color:"#94a3b8" }}>{inst.private_ip}</td>
                <td style={{ padding:"8px 12px", color:"#94a3b8" }}>{inst.az}</td>
                {inst.cpu_avg !== undefined && (
                  <td style={{ padding:"8px 12px", color:cpuColor(inst.cpu_avg), fontWeight:600 }}>{inst.cpu_avg}%</td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        <div style={{ marginTop:8, fontSize:11, color:S.textFaint }}>{data.count} instance{data.count!==1?"s":""}</div>
      </div>
    );
  }

  // Single instance
  if (data.instance) {
    const inst = data.instance;
    return (
      <KVGrid pairs={[
        ["Name", inst.name], ["Instance ID", inst.id], ["State", chip(inst.state)],
        ["Type", inst.type], ["Public IP", inst.public_ip], ["Private IP", inst.private_ip],
        ["AZ", inst.az], ["VPC", inst.vpc_id], ["Subnet", inst.subnet_id], ["Key Pair", inst.key_name],
      ]} />
    );
  }

  // CPU metrics
  if (data.cpu_avg !== undefined) {
    return (
      <div style={{ display:"flex", gap:12, flexWrap:"wrap" }}>
        {[["Avg CPU", `${data.cpu_avg}%`, cpuColor(data.cpu_avg)], ["Max CPU", `${data.cpu_max}%`, cpuColor(data.cpu_max)], ["Period", `${data.period_hours}h`, S.textDim]].map(([k,v,c]) => (
          <div key={k} style={{ background:"#0a1a12", border:`1px solid ${S.border}`, borderRadius:8, padding:"12px 18px", minWidth:100 }}>
            <div style={{ fontSize:10, color:S.greenDim, letterSpacing:1, marginBottom:6 }}>{k}</div>
            <div style={{ fontSize:22, color:c, fontWeight:700, fontFamily:S.mono }}>{v}</div>
          </div>
        ))}
        {data.message && <div style={{ color:S.yellow, fontSize:12, fontFamily:S.mono, alignSelf:"center" }}>{data.message}</div>}
      </div>
    );
  }

  // Instance status
  if (data.instance_status !== undefined) {
    return (
      <div style={{ display:"flex", gap:10, flexWrap:"wrap" }}>
        {[["State", chip(data.state)], ["Instance checks", <StatusBadge s={data.instance_status} />], ["System checks", <StatusBadge s={data.system_status} />]].map(([k,v]) => (
          <div key={k} style={{ background:"#0a1a12", border:`1px solid ${S.border}`, borderRadius:8, padding:"10px 16px" }}>
            <div style={{ fontSize:10, color:S.greenDim, letterSpacing:1, marginBottom:6 }}>{k}</div>
            <div>{v}</div>
          </div>
        ))}
      </div>
    );
  }

  // Security groups
  if (data.groups) {
    return (
      <div>
        {data.groups.map(sg => (
          <div key={sg.id} style={{ background:"#0a1a12", border:`1px solid ${S.border}`, borderRadius:8, padding:"10px 14px", marginBottom:8 }}>
            <div style={{ display:"flex", gap:10, alignItems:"center", marginBottom:8 }}>
              <span style={{ color:S.green, fontWeight:700, fontSize:12, fontFamily:S.mono }}>{sg.name}</span>
              <span style={{ color:S.textFaint, fontSize:11, fontFamily:S.mono }}>{sg.id}</span>
              <span style={{ color:"#94a3b8", fontSize:11 }}>{sg.description}</span>
            </div>
            {sg.inbound_rules.length > 0 && (
              <div>
                <div style={{ fontSize:10, color:S.greenDim, letterSpacing:1, marginBottom:4 }}>INBOUND RULES</div>
                {sg.inbound_rules.map((r, i) => (
                  <div key={i} style={{ fontSize:11, fontFamily:S.mono, color:S.textMid, marginBottom:2 }}>
                    {r.protocol === "-1" ? "All traffic" : `${r.protocol} ${r.from_port}→${r.to_port}`}
                    {r.cidr?.length > 0 && <span style={{ color:S.textFaint }}> · {r.cidr.join(", ")}</span>}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  }

  // Volumes
  if (data.volumes) {
    return (
      <table style={{ width:"100%", borderCollapse:"collapse", fontSize:12, fontFamily:S.mono }}>
        <thead>
          <tr style={{ borderBottom:`1px solid ${S.border}` }}>
            {["Volume ID","Size","Type","State","AZ","Encrypted","Attached To","Device"].map(h => (
              <th key={h} style={{ padding:"8px 12px", textAlign:"left", color:S.greenDim, fontSize:11, letterSpacing:1, whiteSpace:"nowrap" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.volumes.map((v, i) => (
            <tr key={v.id} style={{ borderBottom:`1px solid #0d1f17`, background: i%2===0 ? "transparent" : S.bgRow }}>
              <td style={{ padding:"8px 12px", color:"#52c77a" }}>{v.id}</td>
              <td style={{ padding:"8px 12px", color:S.text }}>{v.size_gb} GB</td>
              <td style={{ padding:"8px 12px", color:S.textDim }}>{v.type}</td>
              <td style={{ padding:"8px 12px", color:v.state==="in-use"?S.green:S.yellow }}>{v.state}</td>
              <td style={{ padding:"8px 12px", color:"#94a3b8" }}>{v.az}</td>
              <td style={{ padding:"8px 12px", color:v.encrypted?S.green:"#94a3b8" }}>{v.encrypted?"Yes":"No"}</td>
              <td style={{ padding:"8px 12px", color:S.textDim }}>{v.attached_to}</td>
              <td style={{ padding:"8px 12px", color:"#94a3b8" }}>{v.device}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  // Memory metrics
  if (data.mem_avg !== undefined) {
    return (
      <div style={{ display:"flex", gap:12 }}>
        <div style={{ background:"#0a1a12", border:`1px solid ${S.border}`, borderRadius:8, padding:"12px 18px" }}>
          <div style={{ fontSize:10, color:S.greenDim, letterSpacing:1, marginBottom:6 }}>MEM USED</div>
          <div style={{ fontSize:22, color:cpuColor(data.mem_avg), fontWeight:700, fontFamily:S.mono }}>{data.mem_avg}%</div>
        </div>
        {data.message && <div style={{ color:S.yellow, fontSize:12, fontFamily:S.mono, alignSelf:"center" }}>{data.message}</div>}
      </div>
    );
  }

  // Fallback JSON
  return <pre style={{ color:S.greenDim, fontSize:11, margin:0, whiteSpace:"pre-wrap" }}>{JSON.stringify(data, null, 2)}</pre>;
};

// ── Suggestions ──────────────────────────────────────────────────────────────
const SUGGESTIONS = [
  "Show all running instances",
  "Public IP of Lab1",
  "Instances with CPU > 70%",
  "List all stopped instances",
  "Show all EBS volumes",
  "Security groups in my account",
  "Status of instance i-0abc123",
  "Memory usage of DB-Primary",
];

// ── Dot loader ───────────────────────────────────────────────────────────────
const Dots = () => (
  <span style={{ display:"inline-flex", gap:4 }}>
    {[0,1,2].map(i => (
      <span key={i} style={{ width:5, height:5, borderRadius:"50%", background:S.green, display:"inline-block",
        animation:`dotpulse 1.2s ${i*0.2}s ease-in-out infinite` }} />
    ))}
  </span>
);


// ── Inline text formatter ────────────────────────────────────────────────────
const InlineText = ({ text }) => {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g);
  return (
    <>
      {parts.map((part, i) => {
        if (part.startsWith("**") && part.endsWith("**"))
          return <strong key={i} style={{ color: S.text, fontWeight: 700 }}>{part.slice(2, -2)}</strong>;
        if (part.startsWith("`") && part.endsWith("`"))
          return <code key={i} style={{ background: "#0a1f12", border: `1px solid ${S.border2}`, borderRadius: 4, padding: "1px 6px", fontSize: 11, color: S.greenDim, fontFamily: S.mono }}>{part.slice(1, -1)}</code>;
        return <span key={i}>{part}</span>;
      })}
    </>
  );
};

// ── FormattedText: renders numbered lists, bullets, headers, paragraphs ───────
const FormattedText = ({ text }) => {
  if (!text) return null;
  const lines = text.split("\n");
  const elements = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) { elements.push(<div key={i} style={{ height: 8 }} />); i++; continue; }
    const numMatch = trimmed.match(/^(\d+)[.)]\s+(.+)/);
    if (numMatch) {
      elements.push(<div key={i} style={{ display:"flex", gap:10, marginBottom:6 }}>
        <span style={{ color:S.greenDim, fontWeight:700, minWidth:20, flexShrink:0 }}>{numMatch[1]}.</span>
        <span style={{ color:S.text, fontWeight:600 }}><InlineText text={numMatch[2]} /></span>
      </div>); i++; continue;
    }
    const bulletMatch = trimmed.match(/^[*\-•]\s+(.+)/);
    if (bulletMatch) {
      elements.push(<div key={i} style={{ display:"flex", gap:10, marginBottom:3, paddingLeft:16 }}>
        <span style={{ color:S.greenMid, flexShrink:0 }}>▸</span>
        <span style={{ color:S.textMid }}><InlineText text={bulletMatch[1]} /></span>
      </div>); i++; continue;
    }
    const headerMatch = trimmed.match(/^[-–]?\s*(.+):$/);
    if (headerMatch && trimmed.length < 40) {
      elements.push(<div key={i} style={{ color:S.greenDim, fontSize:11, fontWeight:700, letterSpacing:1, marginTop:10, marginBottom:4 }}>
        {headerMatch[1].toUpperCase()}
      </div>); i++; continue;
    }
    elements.push(<div key={i} style={{ color:S.textMid, marginBottom:2, lineHeight:1.75 }}><InlineText text={trimmed} /></div>);
    i++;
  }
  return <div>{elements}</div>;
};

// ── App ──────────────────────────────────────────────────────────────────────
export default function App({ token, username, onLogout, onProfile }) {
  const [messages, setMessages]       = useState([]);
  const [input, setInput]             = useState("");
  const [loading, setLoading]         = useState(false);
  const [toolActivity, setToolActivity] = useState(null);
  const [history, setHistory]         = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [isMobile, setIsMobile]       = useState(window.innerWidth < 768);
  const [accounts, setAccounts]       = useState([]);
  const [accountsLoading, setAccountsLoading] = useState(true);
  const [activeAccount, setActiveAccount] = useState(null);
  const [awsStatus, setAwsStatus]     = useState(null);
  const [selectedRegions, setSelectedRegions] = useState(["ap-south-1"]);
  const [regions, setRegions]               = useState([
    "ap-south-1","ap-south-2","ap-southeast-1","ap-southeast-2",
    "ap-northeast-1","ap-northeast-2","ap-northeast-3",
    "us-east-1","us-east-2","us-west-1","us-west-2",
    "eu-west-1","eu-west-2","eu-west-3","eu-central-1",
    "ca-central-1","sa-east-1","af-south-1","me-south-1"
  ]);
  const [regionDropOpen, setRegionDropOpen] = useState(false);
  const bottomRef = useRef(null);
  const inputRef  = useRef(null);

  // Check backend health + fetch regions on load
  useEffect(() => {
    fetch(`${BACKEND_URL}/health`)
      .then(r => r.json())
      .then(d => setAwsStatus(d))
      .catch(() => setAwsStatus({ aws_connected: false, error: "Backend unreachable" }));

    // Fetch saved AWS accounts and auto-select first one
    fetch(`${BACKEND_URL}/accounts`, {
      headers: { "Authorization": `Bearer ${token}` }
    })
      .then(r => r.json())
      .then(data => {
        if (data.accounts?.length > 0) {
          setAccounts(data.accounts);
          setActiveAccount(data.accounts[0]);
        }
      })
      .catch(() => {})
      .finally(() => setAccountsLoading(false));
    if (token) {
      fetch(`${BACKEND_URL}/regions`, {
        headers: { "Authorization": `Bearer ${token}` }
      })
        .then(r => r.json())
        .then(data => { if (data.regions) setRegions(data.regions); })
        .catch(() => {});
    }
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    const onResize = () => {
      const mobile = window.innerWidth < 768;
      setIsMobile(mobile);
      if (mobile) setSidebarOpen(false);
    };
    onResize();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    if (!regionDropOpen) return;
    const close = (e) => { if (!e.target.closest("[data-region-drop]")) setRegionDropOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [regionDropOpen]);

  const sendMessage = useCallback(async (text) => {
    const userText = (text || input).trim();
    if (!userText || loading || accountsLoading) return;
    setInput("");
    setLoading(true);
    setToolActivity({ name: "agent", args: { query: userText } });

    // Append to display messages
    setMessages(prev => [...prev, { type: "user", text: userText }]);

    // Use the first selected region for the agent (it operates per-region,
    // same as the backend's read-only Boto3 calls always have).
    const region = selectedRegions[0] || "ap-south-1";

    try {
      const agentResult = await callAgent(userText, token, region, activeAccount);

      const finalText = agentResult.reply
        || (agentResult.error ? `I couldn't complete that query: ${agentResult.error}` : "Done.");

      setMessages(prev => [...prev, {
        type: "assistant",
        text: finalText,
        generatedCode: agentResult.generated_code,
        rawResult: agentResult.result,
      }]);
      setHistory(prev => [{ query: userText, time: new Date().toLocaleTimeString() }, ...prev.slice(0, 29)]);
    } catch (err) {
      setMessages(prev => [...prev, { type: "error", text: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
      setToolActivity(null);
      inputRef.current?.focus();
    }
  }, [input, loading, selectedRegions, token, activeAccount, accountsLoading]);

  const handleKey = (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  };

  const clearChat = () => {
    setMessages([]);
  };

  // Reset displayed messages when region changes (each query is independent
  // now, so there's no conversation state to carry across a region switch).
  useEffect(() => {
    setMessages([]);
  }, [selectedRegions]);

  return (
    <div style={{ display:"flex", height:"100vh", background:S.bg, fontFamily:S.mono, color:S.textMid, overflow:"hidden" }}>

      {/* Mobile backdrop */}
      {isMobile && sidebarOpen && (
        <div onClick={() => setSidebarOpen(false)}
          style={{ position:"fixed", inset:0, background:"#000000aa", zIndex:10 }} />
      )}

      {/* ── Sidebar ── */}
      <div style={{
        width: sidebarOpen ? 262 : 0,
        minWidth: sidebarOpen ? 262 : 0,
        transition: "all 0.25s",
        overflow: "hidden",
        borderRight: `1px solid ${S.border}`,
        background: S.bgPanel,
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        ...(isMobile && sidebarOpen ? { position:"fixed", top:0, left:0, height:"100vh", zIndex:11, width:262, minWidth:262 } : {})
      }}>

        {/* Logo */}
        <div style={{ padding:"18px 16px 14px", borderBottom:`1px solid ${S.border}` }}>
          {/* <div style={{ fontSize:9, color:S.textFaint, letterSpacing:3, marginBottom:3 }}>CLOUD COMMAND CENTER</div> */}
          <div style={{ fontSize:18, color:S.green, fontWeight:700, letterSpacing:2 }}>CONSOLE</div>
          <div style={{ fontSize:10, color:S.textFaint, marginTop:4 }}>
            {awsStatus?.aws_connected
              ? <span style={{ color:S.greenDim }}>● Server connected</span>
              // ? <span style={{ color:S.greenDim }}>● Backend connected · {awsStatus.groq_keys} LLM key{awsStatus.groq_keys !== 1 ? "s" : ""}</span>
              : <span style={{ color:S.red }}>● Not connected</span>}
          </div>
          {/* <div style={{ fontSize:10, color:S.greenMid, marginTop:4 }}>
            Region: <span style={{ color:S.green }}>
              {selectedRegions.length === regions.length ? "All Regions" : selectedRegions.length === 1 ? selectedRegions[0] : `${selectedRegions.length} selected`}
            </span>
          </div> */}
          {/* <div style={{ fontSize:10, color:S.greenMid, marginTop:6, display:"flex", alignItems:"center", gap:5 }}>
            <span style={{ width:5, height:5, borderRadius:"50%", background:S.green, boxShadow:`0 0 5px ${S.green}` }} />
            Logged in as <strong style={{ color:S.green }}>{username}</strong>
          </div> */}
          {activeAccount && (
            <div style={{ fontSize:10, color:S.greenMid, marginTop:6 }}>
              AWS: <span style={{ color:S.green }}>{activeAccount.label}</span>
              {accounts.length > 1 && (
                <select
                  value={activeAccount.id}
                  onChange={e => setActiveAccount(accounts.find(a => a.id === e.target.value))}
                  style={{ marginLeft:6, background:S.bgCard, border:`1px solid ${S.border}`, borderRadius:4, color:S.greenDim, fontSize:9, fontFamily:S.mono, cursor:"pointer", outline:"none" }}>
                  {accounts.map(a => (
                    <option key={a.id} value={a.id} style={{ background:S.bgCard }}>{a.label}</option>
                  ))}
                </select>
              )}
            </div>
          )}
        </div>

        {/* Quick queries */}
        <div style={{ padding:"14px 12px 8px" }}>
          <div style={{ fontSize:9, color:S.textFaint, letterSpacing:2, marginBottom:10 }}>QUICK QUERIES</div>
          {SUGGESTIONS.map(s => (
            <button key={s} onClick={() => sendMessage(s)} disabled={loading || accountsLoading}
              style={{ display:"block", width:"100%", textAlign:"left", background:"none", border:`1px solid ${S.border}`, borderRadius:6, padding:"7px 10px", color:S.textDim, fontSize:11, cursor:"pointer", marginBottom:4, transition:"all 0.15s", fontFamily:S.mono, opacity:(loading||accountsLoading)?0.5:1 }}
              onMouseEnter={e => { e.currentTarget.style.background="#0a1f12"; e.currentTarget.style.color=S.green; e.currentTarget.style.borderColor=S.greenFade; }}
              onMouseLeave={e => { e.currentTarget.style.background="none"; e.currentTarget.style.color=S.textDim; e.currentTarget.style.borderColor=S.border; }}>
              {s}
            </button>
          ))}
        </div>

        {/* History */}
        <div style={{ flex:1, padding:"4px 12px", overflowY:"auto" }}>
          {history.length > 0 && (
            <>
              <div style={{ fontSize:9, color:S.textFaint, letterSpacing:2, margin:"10px 0 8px" }}>HISTORY</div>
              {history.map((h, i) => (
                <div key={i} onClick={() => sendMessage(h.query)} style={{ padding:"7px 8px", borderRadius:6, marginBottom:3, cursor:"pointer", transition:"background 0.15s" }}
                  onMouseEnter={e => e.currentTarget.style.background="#0a1f12"}
                  onMouseLeave={e => e.currentTarget.style.background="transparent"}>
                  <div style={{ fontSize:11, color:S.textDim, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>{h.query}</div>
                  <div style={{ fontSize:10, color:S.textFaint, marginTop:2 }}>{h.time} · {h.toolCount} tool{h.toolCount!==1?"s":""}</div>
                </div>
              ))}
            </>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding:"10px 14px", borderTop:`1px solid ${S.border}`, fontSize:10, color:S.textFaint }}>
          <div style={{ display:"flex", alignItems:"center", gap:6 }}>
            <span style={{ width:5, height:5, borderRadius:"50%", background:S.green, boxShadow:`0 0 5px ${S.green}` }} />
            Groq · LLaMA-3 70B · Tool Use
          </div>
        </div>
      </div>

      {/* ── Main ── */}
      <div style={{ flex:1, display:"flex", flexDirection:"column", overflow:"hidden" }}>

        {/* Header */}
        <div style={{ padding:"10px 18px", borderBottom:`1px solid ${S.border}`, display:"flex", alignItems:"center", gap:10, background:S.bgPanel, flexShrink:0 }}>
          <button onClick={() => setSidebarOpen(o => !o)} style={{ background:"none", border:`1px solid ${S.border2}`, borderRadius:6, padding:"5px 9px", cursor:"pointer", color:S.greenDim, fontSize:13, fontFamily:S.mono, flexShrink:0 }}>☰</button>
          <div style={{ flex:1, minWidth:0 }}>
            <div style={{ fontSize: isMobile ? 9 : 11, color:S.green, fontWeight:700, letterSpacing: isMobile ? 1 : 2, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap" }}>
              {isMobile ? "CMD CENTER" : "CLOUD COMMAND CENTER PLATFORM"}
            </div>
            {!isMobile && <div style={{ fontSize:10, color:S.textFaint }}>Natural language → Agent-generated Boto3 → AWS</div>}
          </div>
          <div style={{ display:"flex", gap: isMobile ? 5 : 8, alignItems:"center", flexShrink:0 }}>
            {!isMobile && ["EC2","CloudWatch","STS"].map(s => (
              <span key={s} style={{ fontSize:10, padding:"3px 8px", border:`1px solid ${S.greenFade}`, borderRadius:4, color:S.greenDim, letterSpacing:1 }}>{s}</span>
            ))}
            {!isMobile && <div style={{ width:1, height:20, background:S.border2 }} />}

            {/* ── Multi-region checkbox dropdown ── */}
            <div style={{ position:"relative" }} data-region-drop>
              <button onClick={() => setRegionDropOpen(o => !o)}
                style={{ background:"#070f0a", border:`1px solid ${regionDropOpen ? S.greenMid : S.border2}`, borderRadius:6, padding:"4px 8px", color:S.greenDim, fontSize:10, fontFamily:S.mono, cursor:"pointer", outline:"none", letterSpacing:1, transition:"all 0.2s", display:"flex", alignItems:"center", gap:4, whiteSpace:"nowrap", maxWidth: isMobile ? 110 : "none", overflow:"hidden" }}>
                <span style={{ color:S.green, flexShrink:0 }}>⬡</span>
                <span style={{ overflow:"hidden", textOverflow:"ellipsis", fontSize: isMobile ? 9 : 10 }}>
                  {selectedRegions.length === regions.length ? "All" : selectedRegions.length === 1 ? selectedRegions[0] : `${selectedRegions.length} Rgns`}
                </span>
                <span style={{ fontSize:8, opacity:0.6, flexShrink:0 }}>{regionDropOpen ? "▲" : "▼"}</span>
              </button>

              {regionDropOpen && (
                <div style={{ position:"absolute", top:"calc(100% + 6px)", right:0, background:S.bgPanel, border:`1px solid ${S.border2}`, borderRadius:10, padding:"8px 0", zIndex:200, minWidth:200, maxHeight:340, overflowY:"auto", boxShadow:"0 8px 32px #00000099" }}>
                  {/* ALL / RESET controls */}
                  <div style={{ display:"flex", alignItems:"center", gap:8, padding:"6px 14px 10px", borderBottom:`1px solid ${S.border}` }}>
                    <span onClick={() => setSelectedRegions([...regions])}
                      style={{ fontSize:10, color:S.green, cursor:"pointer", letterSpacing:1, fontWeight:700, border:`1px solid ${S.border2}`, borderRadius:4, padding:"2px 8px" }}>
                      ALL
                    </span>
                    <span onClick={() => setSelectedRegions(["ap-south-1"])}
                      style={{ fontSize:10, color:S.greenMid, cursor:"pointer", letterSpacing:1, border:`1px solid ${S.border}`, borderRadius:4, padding:"2px 8px" }}>
                      RESET
                    </span>
                    <span style={{ flex:1 }} />
                    <span style={{ fontSize:10, color:S.textFaint }}>{selectedRegions.length}/{regions.length}</span>
                  </div>
                  {/* Region list with checkboxes */}
                  {regions.map(r => (
                    <label key={r}
                      style={{ display:"flex", alignItems:"center", gap:10, padding:"7px 14px", cursor:"pointer", transition:"background 0.15s" }}
                      onMouseEnter={e => e.currentTarget.style.background="#0a1f12"}
                      onMouseLeave={e => e.currentTarget.style.background="transparent"}>
                      <input type="checkbox"
                        checked={selectedRegions.includes(r)}
                        onChange={() => setSelectedRegions(prev =>
                          prev.includes(r)
                            ? prev.length > 1 ? prev.filter(x => x !== r) : prev
                            : [...prev, r]
                        )}
                        style={{ accentColor:S.green, width:13, height:13, cursor:"pointer", flexShrink:0 }}
                      />
                      <span style={{ fontSize:11, color: selectedRegions.includes(r) ? S.green : S.textMid, fontFamily:S.mono }}>{r}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>

            <button onClick={clearChat} title="Clear chat"
              style={{ background:"none", border:`1px solid ${S.greenDim}`, borderRadius:6, padding:"4px 10px", cursor:"pointer", color:S.greenDim, fontSize:10, fontFamily:S.mono, marginLeft:4, letterSpacing:1, transition:"all 0.2s" }}
              onMouseEnter={e => { e.currentTarget.style.background="#4ade8022"; e.currentTarget.style.color=S.green; e.currentTarget.style.borderColor=S.green; }}
              onMouseLeave={e => { e.currentTarget.style.background="none"; e.currentTarget.style.color=S.greenDim; e.currentTarget.style.borderColor=S.greenDim; }}>
              {isMobile ? "CLR" : "CLEAR"}
            </button>
            {!isMobile && <div style={{ width:1, height:20, background:S.border2, margin:"0 4px" }} />}
            {/* {!isMobile && <span style={{ fontSize:10, color:S.greenMid, letterSpacing:1 }}>{username}</span>} */}
            <button onClick={onProfile} title="Profile"
              style={{ background:"none", border:`1px solid ${S.border2}`, borderRadius:6, padding:"4px 10px", cursor:"pointer", color:S.greenDim, fontSize:10, fontFamily:S.mono, letterSpacing:1, transition:"all 0.2s" }}
              onMouseEnter={e => { e.currentTarget.style.background="#0a1f12"; e.currentTarget.style.borderColor=S.greenMid; }}
              onMouseLeave={e => { e.currentTarget.style.background="none"; e.currentTarget.style.borderColor=S.border2; }}>
              {isMobile ? "⚙" : username}
            </button>
            <button onClick={onLogout} title="Logout"
              style={{ background:"none", border:`1px solid #4a1525`, borderRadius:6, padding:"4px 10px", cursor:"pointer", color:"#ff4d6d", fontSize:10, fontFamily:S.mono, letterSpacing:1, transition:"all 0.2s" }}
              onMouseEnter={e => { e.currentTarget.style.background="#1a0509"; }}
              onMouseLeave={e => { e.currentTarget.style.background="none"; }}>
              {isMobile ? "↩" : "LOGOUT"}
            </button>
          </div>
        </div>

        {/* Messages */}
        <div style={{ flex:1, overflowY:"auto", padding: isMobile ? "12px 12px" : "20px 24px" }}>
          {messages.length === 0 && (
            <div style={{ textAlign:"center", marginTop:80, color:S.textFaint }}>
              <div style={{ fontSize:40, marginBottom:16, opacity:0.15 }}>⬡</div>
              <div style={{ fontSize:13, marginBottom:6 }}>Ask anything about your AWS infrastructure</div>
              <div style={{ fontSize:11, color:S.border2 }}>Fully Agentic · Live-generated Boto3 · Real AWS Data</div>
            </div>
          )}

          {messages.map((msg, i) => (
            <div key={i} style={{ marginBottom:20, display:"flex", flexDirection:"column", alignItems: msg.type==="user" ? "flex-end" : "flex-start" }}>
              {msg.type === "user" && (
                <div style={{ maxWidth: isMobile ? "92%" : "65%", background:"#0a1f12", border:`1px solid ${S.greenFade}`, borderRadius:"12px 12px 2px 12px", padding:"10px 16px", fontSize: isMobile ? 12 : 13, color:S.text, lineHeight:1.6 }}>
                  {msg.text}
                </div>
              )}

              {msg.type === "assistant" && (
                <div style={{ maxWidth:"96%", width:"100%" }}>
                  <div style={{ fontSize:9, color:S.textFaint, letterSpacing:2, marginBottom:6 }}>ASSISTANT</div>

                  {/* LLM text response */}
                  <div style={{ background:S.bgCard, border:`1px solid ${S.border}`, borderRadius:"2px 12px 12px 12px", padding:"12px 16px", fontSize:13, color:S.textMid, lineHeight:1.75 }}>
                    <FormattedText text={msg.text} />
                  </div>

                  {/* Raw agent result, rendered with the generic shape-based table when possible */}
                  {msg.rawResult !== undefined && (
                    <details style={{ marginTop:8 }}>
                      <summary style={{ cursor:"pointer", fontSize:10, color:S.textFaint, letterSpacing:1 }}>
                        VIEW RAW RESULT
                      </summary>
                      <div style={{ background:S.bgCard, border:`1px solid ${S.border2}`, borderRadius:8, padding:"10px 14px", marginTop:6 }}>
                        <ResultTable data={msg.rawResult} />
                      </div>
                    </details>
                  )}
                </div>
              )}

              {msg.type === "error" && (
                <div style={{ background:"#1a0509", border:`1px solid #4a1525`, borderRadius:10, padding:"10px 16px", fontSize:12, color:S.red, fontFamily:S.mono }}>
                  {msg.text}
                </div>
              )}
            </div>
          ))}

          {/* Live tool-call indicator */}
          {loading && (
            <div style={{ display:"flex", alignItems:"center", gap:10, padding:"8px 0", marginBottom:8 }}>
              <Dots />
              <span style={{ fontSize: 11, color: "#2d6b4a" }}>Fetching your AWS data...</span>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input bar */}
        <div style={{ padding: isMobile ? "10px 12px" : "14px 20px", borderTop:`1px solid ${S.border}`, background:S.bgPanel, flexShrink:0 }}>
          <div style={{ display:"flex", gap:8, alignItems:"center" }}>
            <span style={{ color:S.textFaint, fontSize:13, userSelect:"none" }}>$</span>
            <input
              ref={inputRef}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Ask about your AWS infrastructure..."
              disabled={loading}
              autoFocus
              style={{ flex:1, background:"#070f0a", border:`1px solid ${S.border2}`, borderRadius:10, padding:"11px 14px", color:S.text, fontSize: isMobile ? 16 : 13, outline:"none", fontFamily:S.mono, transition:"border-color 0.2s" }}
              onFocus={e => e.target.style.borderColor=S.greenMid}
              onBlur={e  => e.target.style.borderColor=S.border2}
            />
            <button onClick={() => sendMessage()} disabled={loading || !input.trim()}
              style={{ background: (loading||!input.trim()) ? "#0a1f12" : S.green, border:"none", borderRadius:10, padding:"11px 20px", cursor:(loading||!input.trim())?"not-allowed":"pointer", color:(loading||!input.trim())?S.textFaint:S.bg, fontSize:13, fontWeight:700, transition:"all 0.2s", fontFamily:S.mono, flexShrink:0 }}>
              {loading ? <Dots /> : "RUN"}
            </button>
          </div>
          {!isMobile && <div style={{ marginTop:7, fontSize:10, color:S.border2 }}>Enter to send · Shift+Enter for newline · Backend: {BACKEND_URL}</div>}
        </div>
      </div>

      <style>{`
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: ${S.bgPanel}; }
        ::-webkit-scrollbar-thumb { background: ${S.border2}; border-radius: 2px; }
        @keyframes dotpulse {
          0%,100% { opacity:0.25; transform:scale(1); }
          50%      { opacity:1;    transform:scale(1.4); }
        }
        button:not(:disabled):active { transform:scale(0.96); }
        input::placeholder { color: ${S.textFaint}; }
        @media (max-width: 767px) {
          * { -webkit-tap-highlight-color: transparent; }
          input, button, select { touch-action: manipulation; }
        }
      `}</style>
    </div>
  );
}