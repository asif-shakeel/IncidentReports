import { useState, useEffect, useMemo } from "react";

// --- IRH Frontend (login-first flow) ---
//  • Gate all features behind login (no manual token field)
//  • Clean messages instead of raw JSON
//  • County dropdown + manual fallback
//  • Datetime input validation

const COUNTIES = [
  "Alameda","Alpine","Amador","Butte","Calaveras","Colusa","Contra Costa","Del Norte","El Dorado",
  "Fresno","Glenn","Humboldt","Imperial","Inyo","Kern","Kings","Lake","Lassen","Los Angeles",
  "Madera","Marin","Mariposa","Mendocino","Merced","Modoc","Mono","Monterey","Napa","Nevada",
  "Orange","Placer","Plumas","Riverside","Sacramento","San Benito","San Bernardino","San Diego",
  "San Francisco","San Joaquin","San Luis Obispo","San Mateo","Santa Barbara","Santa Clara","Santa Cruz",
  "Shasta","Sierra","Siskiyou","Solano","Sonoma","Stanislaus","Sutter","Tehama","Trinity","Tulare",
  "Tuolumne","Ventura","Yolo","Yuba"
];

export default function App() {
  const [apiBase, setApiBase] = useState(localStorage.getItem("apiBase") || "https://incidentreports-1.onrender.com");
  const [token, setToken] = useState(localStorage.getItem("token") || "");

  // login state
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authMsg, setAuthMsg] = useState("");

  // request form state
  const [address, setAddress] = useState("");
  const [datetime, setDatetime] = useState("");
  const [countyMode, setCountyMode] = useState("dropdown");
  const [countySelect, setCountySelect] = useState("San Diego");
  const [countyText, setCountyText] = useState("");

  // UX messages
  const [notice, setNotice] = useState("");

  useEffect(() => { localStorage.setItem("apiBase", apiBase); }, [apiBase]);
  useEffect(() => { if (token) localStorage.setItem("token", token); }, [token]);

  const county = countyMode === "dropdown" ? countySelect : countyText.trim();
  const dtValid = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(datetime);
  const canSend = Boolean(address.trim() && dtValid && county);

  async function login() {
    setAuthMsg("");
    try {
      const res = await fetch(`${apiBase}/token`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ username, password })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || "Login failed");
      setToken(data.access_token);
      setAuthMsg("✅ Logged in.");
    } catch (err) {
      setAuthMsg("❌ " + err.message);
    }
  }

  async function createRequest() {
    setNotice("");
    try {
      const res = await fetch(`${apiBase}/incident_request`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ incident_address: address, incident_datetime: datetime, county })
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data?.detail || res.statusText);
      setNotice("✅ Request sent.");
      // optionally clear fields after success:
      // setAddress(""); setDatetime(""); if (countyMode==="text") setCountyText("");
    } catch (err) {
      setNotice("❌ " + err.message);
    }
  }

  async function ping() {
    try {
      const res = await fetch(`${apiBase}/ping`);
      setNotice(res.ok ? "Ping ok" : `Ping failed (${res.status})`);
    } catch {
      setNotice("Ping failed (network)");
    }
  }

  async function health() {
    try {
      const res = await fetch(`${apiBase}/healthz`);
      const txt = await res.text();
      setNotice(res.ok ? `Health: ${txt}` : `Health failed (${res.status})`);
    } catch {
      setNotice("Health failed (network)");
    }
  }

  const curlDemo = useMemo(() => (
    `curl -X POST ${apiBase}/incident_request \\\n  -H "Content-Type: application/json" \\\n  -H "Authorization: Bearer <token>" \\\n  -d '{"incident_address":"${address}","incident_datetime":"${datetime}","county":"${county}"}'`
  ), [apiBase, address, datetime, county]);

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">IncidentReportHub</h1>

      {/* API base selector */}
      <div className="space-y-2">
        <label className="block">API Base</label>
        <input className="border p-1 w-full" value={apiBase} onChange={e=>setApiBase(e.target.value)} />
        <div className="text-xs" style={{color:'#6b7280'}}>E.g., http://localhost:8000 or https://incidentreports-1.onrender.com</div>
      </div>

      {/* LOGIN FIRST */}
      {!token && (
        <div className="border p-4 rounded space-y-3">
          <h2 className="font-semibold">Login</h2>
          <input className="border p-1 w-full" placeholder="username" value={username} onChange={e=>setUsername(e.target.value)} />
          <input type="password" className="border p-1 w-full" placeholder="password" value={password} onChange={e=>setPassword(e.target.value)} />
          <button className="bg-blue-500 text-white px-3 py-1" onClick={login}>Login</button>
          {authMsg && <div className="text-sm">{authMsg}</div>}
          <div className="text-xs" style={{color:'#6b7280'}}>
            Don’t have an account? Use the backend <code>/register</code> once, then return here.
          </div>
        </div>
      )}

      {/* MAIN UI only after login */}
      {token && (
        <>
          <div className="border p-4 rounded space-y-3">
            <h2 className="font-semibold">Create Incident Request</h2>
            <input className="border p-1 w-full" placeholder="Address (e.g., 3801 10th St)" value={address} onChange={e=>setAddress(e.target.value)} />

            <div>
              <input className="border p-1 w-full" placeholder="Date/Time (YYYY-MM-DD HH:MM)" value={datetime} onChange={e=>setDatetime(e.target.value)} />
              {!datetime ? (
                <div className="text-xs" style={{color:'#6b7280'}}>Example: 2025-08-01 10:00</div>
              ) : (!dtValid ? (
                <div className="text-xs" style={{color:'#ef4444'}}>Format must be YYYY-MM-DD HH:MM</div>
              ) : null)}
            </div>

            <div className="space-y-2">
              <div className="text-sm font-medium">County</div>
              <div className="text-xs" style={{color:'#6b7280'}}>Choose from list or switch to manual entry.</div>

              <div className="flex gap-3 items-center flex-wrap">
                <label className="flex items-center gap-1 text-sm">
                  <input type="radio" name="cmode" checked={countyMode==='dropdown'} onChange={()=>setCountyMode('dropdown')} />
                  Dropdown
                </label>
                <label className="flex items-center gap-1 text-sm">
                  <input type="radio" name="cmode" checked={countyMode==='text'} onChange={()=>setCountyMode('text')} />
                  Other (type)
                </label>
              </div>

              {countyMode === 'dropdown' ? (
                <select className="border p-1 w-full" value={countySelect} onChange={e=>setCountySelect(e.target.value)}>
                  {COUNTIES.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              ) : (
                <input className="border p-1 w-full" placeholder="Type county name" value={countyText} onChange={e=>setCountyText(e.target.value)} />
              )}
            </div>

            <div className="flex items-center gap-2">
              <button className="bg-green-500 text-white px-3 py-1" onClick={createRequest} disabled={!canSend}>
                {canSend ? "Send Request" : "Fill all fields correctly"}
              </button>
              <button className="bg-gray-500 text-white px-3 py-1" onClick={()=>{ setToken(""); localStorage.removeItem("token"); setAuthMsg("Logged out."); }}>Logout</button>
            </div>

            <div className="text-xs mt-2" style={{color:'#6b7280'}}>CURL (for debugging only):</div>
            <pre className="text-xs border rounded p-2 overflow-auto">{curlDemo}</pre>
          </div>

          <div className="border p-4 rounded space-y-2">
            <h2 className="font-semibold">Diagnostics</h2>
            <button className="bg-gray-500 text-white px-3 py-1 mr-2" onClick={ping}>GET /ping</button>
            <button className="bg-gray-500 text-white px-3 py-1" onClick={health}>GET /healthz</button>
          </div>
        </>
      )}

      {notice && (
        <div className="border p-3 rounded" style={{background:'#f9fafb'}}>{notice}</div>
      )}
    </div>
  );
}
