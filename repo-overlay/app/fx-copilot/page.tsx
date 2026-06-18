"use client";

import { useEffect, useState } from "react";

type Briefing = {
  id?: string;
  generatedAt: string;
  status: string;
  mode: string;
  overallRisk: string;
  summary: string;
  riskFlags: string[];
  items: Array<{
    id: string;
    headline: string;
    source: string;
    url: string;
    publishedAt: string;
    affectedCurrencies: string[];
    affectedPairs: string[];
    eventType: string;
    bias: string;
    impactLevel: string;
    confidence: number;
    timeHorizon: string;
    reasoning: string;
    suggestedPlatformState: string;
  }>;
};

export default function FxCopilotPage() {
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [status, setStatus] = useState("Loading FX co-pilot...");
  const [pair, setPair] = useState("GBP/USD");
  const [riskDecision, setRiskDecision] = useState<Record<string, unknown> | null>(null);

  async function loadBriefing() {
    try {
      const response = await fetch("/api/fx-copilot/latest", { cache: "no-store" });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "Could not load briefing");
      setBriefing(result.briefing);
      setStatus(result.briefing ? "Live FX co-pilot loaded" : "No FX co-pilot briefing yet. Run the cron endpoint first.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not load FX co-pilot");
    }
  }

  async function checkPairRisk() {
    const response = await fetch("/api/fx-copilot/risk-check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pair, side: "unknown", entryReason: "Manual dashboard check" })
    });
    const result = await response.json();
    setRiskDecision(result.decision || result);
  }

  useEffect(() => {
    loadBriefing();
    const timer = window.setInterval(loadBriefing, 60000);
    return () => window.clearInterval(timer);
  }, []);

  const riskTone = briefing?.overallRisk === "critical" || briefing?.overallRisk === "high" ? "#fb7185" : briefing?.overallRisk === "medium" ? "#facc15" : "#4ade80";

  return (
    <main style={{ minHeight: "100vh", padding: 24, background: "linear-gradient(180deg,#050814,#07111f)", color: "#eef5ff", fontFamily: "Inter, system-ui, sans-serif" }}>
      <section style={{ maxWidth: 1180, margin: "0 auto" }}>
        <p style={{ color: "#93a4bd", marginBottom: 8 }}>AI FX Trading Platform</p>
        <h1 style={{ fontSize: 42, lineHeight: 1.05, margin: 0 }}>FX News Co-Pilot & Risk Guard</h1>
        <p style={{ color: "#b8c7dc", maxWidth: 780 }}>
          Live market context for world news, macro events and currency risk. The risk-check endpoint combines news and economic-calendar blackouts before your execution engine places a trade.
        </p>
        <p><a href="/fx-copilot/calendar" style={{ color: "#93c5fd" }}>Open Economic Calendar Guard</a></p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(240px,1fr))", gap: 16, marginTop: 24 }}>
          <div style={cardStyle}><span style={labelStyle}>Status</span><h2 style={{ margin: "8px 0" }}>{status}</h2></div>
          <div style={cardStyle}><span style={labelStyle}>Overall risk</span><h2 style={{ color: riskTone, textTransform: "uppercase", margin: "8px 0" }}>{briefing?.overallRisk || "Waiting"}</h2></div>
          <div style={cardStyle}><span style={labelStyle}>Mode</span><h2 style={{ margin: "8px 0" }}>{briefing?.mode || "risk_guard"}</h2></div>
          <div style={cardStyle}><span style={labelStyle}>Last generated</span><h2 style={{ margin: "8px 0" }}>{briefing ? new Date(briefing.generatedAt).toLocaleString("en-GB") : "Not yet"}</h2></div>
        </div>

        <section style={{ ...cardStyle, marginTop: 16 }}>
          <span style={labelStyle}>Current briefing</span>
          <p style={{ fontSize: 18 }}>{briefing?.summary || "No briefing available yet."}</p>
          {!!briefing?.riskFlags?.length && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {briefing.riskFlags.map((flag) => <span key={flag} style={pillStyle}>{flag}</span>)}
            </div>
          )}
        </section>

        <section style={{ ...cardStyle, marginTop: 16 }}>
          <span style={labelStyle}>Combined trade risk check</span>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 12 }}>
            <input value={pair} onChange={(event) => setPair(event.target.value)} style={inputStyle} />
            <button onClick={checkPairRisk} style={buttonStyle}>Check pair risk</button>
          </div>
          {riskDecision && (
            <pre style={{ whiteSpace: "pre-wrap", background: "rgba(15,23,42,.8)", padding: 16, borderRadius: 14, overflowX: "auto" }}>
              {JSON.stringify(riskDecision, null, 2)}
            </pre>
          )}
        </section>

        <section style={{ marginTop: 16 }}>
          <h2>Latest market-impact items</h2>
          <div style={{ display: "grid", gap: 12 }}>
            {(briefing?.items || []).map((item) => (
              <article key={item.id} style={cardStyle}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                  <span style={labelStyle}>{item.source} · {new Date(item.publishedAt).toLocaleString("en-GB")}</span>
                  <span style={pillStyle}>{item.impactLevel} · {Math.round(item.confidence * 100)}%</span>
                </div>
                <h3 style={{ marginBottom: 8 }}>{item.headline}</h3>
                <p style={{ color: "#b8c7dc" }}>{item.reasoning}</p>
                <p style={{ color: "#93a4bd" }}>Pairs: {item.affectedPairs.join(", ") || "N/A"} · Bias: {item.bias} · Platform: {item.suggestedPlatformState}</p>
                {item.url && <a href={item.url} target="_blank" rel="noreferrer" style={{ color: "#93c5fd" }}>Open source</a>}
              </article>
            ))}
          </div>
        </section>
      </section>
    </main>
  );
}

const cardStyle: React.CSSProperties = {
  border: "1px solid rgba(148,163,184,.18)",
  borderRadius: 18,
  padding: 18,
  background: "rgba(15,23,42,.72)",
  boxShadow: "0 20px 70px rgba(0,0,0,.25)"
};

const labelStyle: React.CSSProperties = {
  color: "#93a4bd",
  fontSize: 13,
  textTransform: "uppercase",
  letterSpacing: ".08em"
};

const pillStyle: React.CSSProperties = {
  border: "1px solid rgba(148,163,184,.22)",
  borderRadius: 999,
  padding: "6px 10px",
  background: "rgba(30,41,59,.82)",
  color: "#dbeafe",
  fontSize: 13
};

const inputStyle: React.CSSProperties = {
  border: "1px solid rgba(148,163,184,.22)",
  borderRadius: 12,
  padding: "12px 14px",
  background: "#020617",
  color: "#eef5ff",
  minWidth: 180
};

const buttonStyle: React.CSSProperties = {
  border: 0,
  borderRadius: 12,
  padding: "12px 16px",
  background: "#2563eb",
  color: "#fff",
  cursor: "pointer",
  fontWeight: 700
};
