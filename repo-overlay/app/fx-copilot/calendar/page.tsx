"use client";

import { useEffect, useMemo, useState } from "react";

type CalendarEvent = {
  id?: string;
  externalId: string;
  provider: string;
  title: string;
  country: string;
  currency: string;
  category: string;
  eventTime: string;
  period?: string | null;
  importance: string;
  status: string;
  previous?: string | number | null;
  forecast?: string | number | null;
  actual?: string | number | null;
  revised?: string | number | null;
  unit?: string | null;
};

const pairs = ["EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "NZD/USD", "USD/CAD", "EUR/GBP", "EUR/JPY", "GBP/JPY"];

function formatValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function countdown(date: string) {
  const diff = new Date(date).getTime() - Date.now();
  const abs = Math.abs(diff);
  const hours = Math.floor(abs / 3600000);
  const mins = Math.floor((abs % 3600000) / 60000);
  const prefix = diff >= 0 ? "in" : "released";
  return `${prefix} ${hours}h ${mins}m`;
}

export default function EconomicCalendarPage() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [status, setStatus] = useState("Loading economic calendar...");
  const [currency, setCurrency] = useState("ALL");
  const [importance, setImportance] = useState("ALL");
  const [pair, setPair] = useState("GBP/USD");
  const [risk, setRisk] = useState<Record<string, unknown> | null>(null);

  async function loadEvents() {
    try {
      const response = await fetch("/api/fx-copilot/calendar/upcoming?hours=168", { cache: "no-store" });
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "Calendar failed");
      setEvents(result.events || []);
      setStatus(`Loaded ${result.events?.length || 0} upcoming events`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not load economic calendar");
    }
  }

  async function syncEvents() {
    setStatus("Syncing economic calendar...");
    try {
      const response = await fetch("/api/fx-copilot/calendar/sync");
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error(result.error || "Sync failed");
      await loadEvents();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Sync failed");
    }
  }

  async function checkPair() {
    const response = await fetch(`/api/fx-copilot/calendar/risk-check?pair=${encodeURIComponent(pair)}`, { cache: "no-store" });
    const result = await response.json();
    setRisk(result.decision || result);
  }

  useEffect(() => {
    loadEvents();
    const timer = window.setInterval(loadEvents, 60000);
    return () => window.clearInterval(timer);
  }, []);

  const filtered = useMemo(() => {
    return events.filter((event) => {
      if (currency !== "ALL" && event.currency !== currency) return false;
      if (importance !== "ALL" && event.importance !== importance) return false;
      return true;
    });
  }, [events, currency, importance]);

  const currencies = Array.from(new Set(events.map((event) => event.currency))).sort();

  return (
    <main style={{ minHeight: "100vh", padding: 24, background: "linear-gradient(180deg,#050814,#07111f)", color: "#eef5ff", fontFamily: "Inter, system-ui, sans-serif" }}>
      <section style={{ maxWidth: 1240, margin: "0 auto" }}>
        <p style={labelStyle}>AI FX Trading Platform</p>
        <h1 style={{ fontSize: 42, lineHeight: 1.05, margin: 0 }}>Economic Calendar Guard</h1>
        <p style={{ color: "#b8c7dc", maxWidth: 820 }}>
          Scheduled macro events, high-impact blackout windows, pair-level risk checks, forecast/previous/actual tracking, and trading controls for your self-trading AI system.
        </p>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(220px,1fr))", gap: 16, marginTop: 24 }}>
          <div style={cardStyle}><span style={labelStyle}>Status</span><h2>{status}</h2></div>
          <div style={cardStyle}><span style={labelStyle}>Events shown</span><h2>{filtered.length}</h2></div>
          <div style={cardStyle}><span style={labelStyle}>High/Critical</span><h2>{events.filter((event) => event.importance === "high" || event.importance === "critical").length}</h2></div>
          <div style={cardStyle}><span style={labelStyle}>Provider</span><h2>{events[0]?.provider || "waiting"}</h2></div>
        </div>

        <section style={{ ...cardStyle, marginTop: 16 }}>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
            <select value={currency} onChange={(event) => setCurrency(event.target.value)} style={inputStyle}>
              <option value="ALL">All currencies</option>
              {currencies.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <select value={importance} onChange={(event) => setImportance(event.target.value)} style={inputStyle}>
              <option value="ALL">All impact</option>
              <option value="critical">Critical</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
            <button onClick={syncEvents} style={buttonStyle}>Sync now</button>
          </div>
        </section>

        <section style={{ ...cardStyle, marginTop: 16 }}>
          <span style={labelStyle}>Pair blackout check</span>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 12 }}>
            <select value={pair} onChange={(event) => setPair(event.target.value)} style={inputStyle}>
              {pairs.map((item) => <option key={item} value={item}>{item}</option>)}
            </select>
            <button onClick={checkPair} style={buttonStyle}>Check economic risk</button>
          </div>
          {risk && (
            <pre style={{ whiteSpace: "pre-wrap", background: "rgba(15,23,42,.8)", padding: 16, borderRadius: 14, overflowX: "auto" }}>
              {JSON.stringify(risk, null, 2)}
            </pre>
          )}
        </section>

        <section style={{ marginTop: 16 }}>
          <h2>Upcoming events</h2>
          <div style={{ display: "grid", gap: 10 }}>
            {filtered.map((event) => {
              const impactColor = event.importance === "critical" ? "#fb7185" : event.importance === "high" ? "#f97316" : event.importance === "medium" ? "#facc15" : "#4ade80";
              return (
                <article key={`${event.provider}-${event.externalId}`} style={cardStyle}>
                  <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                    <span style={labelStyle}>{event.currency} · {event.country} · {event.status}</span>
                    <span style={{ ...pillStyle, color: impactColor }}>{event.importance.toUpperCase()} · {countdown(event.eventTime)}</span>
                  </div>
                  <h3>{event.title}</h3>
                  <p style={{ color: "#93a4bd" }}>{new Date(event.eventTime).toLocaleString("en-GB")} · {event.period || "No period"}</p>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(130px,1fr))", gap: 10 }}>
                    <div style={miniStyle}><span style={labelStyle}>Previous</span><strong>{formatValue(event.previous)}</strong></div>
                    <div style={miniStyle}><span style={labelStyle}>Forecast</span><strong>{formatValue(event.forecast)}</strong></div>
                    <div style={miniStyle}><span style={labelStyle}>Actual</span><strong>{formatValue(event.actual)}</strong></div>
                    <div style={miniStyle}><span style={labelStyle}>Revised</span><strong>{formatValue(event.revised)}</strong></div>
                  </div>
                </article>
              );
            })}
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

const miniStyle: React.CSSProperties = {
  border: "1px solid rgba(148,163,184,.12)",
  borderRadius: 14,
  padding: 12,
  background: "rgba(2,6,23,.55)"
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
