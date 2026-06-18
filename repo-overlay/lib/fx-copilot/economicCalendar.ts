import {
  actionForImportance,
  blackoutAfterMinutes,
  blackoutBeforeMinutes,
  calendarLookaheadDays,
  calendarLookbackHours,
  calendarProvider,
  countryCurrencyMap,
  currenciesFromPair,
  normalisePair,
  watchedCurrencies
} from "./config";
import type {
  CalendarImportance,
  CalendarRiskDecision,
  CalendarRiskWindow,
  EconomicCalendarEvent,
  EconomicCalendarProvider
} from "./types";

function isoDateOnly(date: Date) {
  return date.toISOString().slice(0, 10);
}

function safeDate(value: unknown) {
  if (!value) return new Date().toISOString();
  const parsed = new Date(String(value));
  if (!Number.isNaN(parsed.getTime())) return parsed.toISOString();
  return new Date().toISOString();
}

function numericText(value: unknown): string | number | null {
  if (value === undefined || value === null || value === "") return null;
  if (typeof value === "number") return value;
  const valueText = String(value).trim();
  if (!valueText) return null;
  const numeric = Number(valueText.replace(/[%,$£€]/g, ""));
  return Number.isFinite(numeric) ? numeric : valueText;
}

function importanceFromAny(value: unknown, category?: string): CalendarImportance {
  const text = String(value || "").toLowerCase();
  const cat = String(category || "").toLowerCase();

  if (["3", "high", "critical"].includes(text)) return "high";
  if (["2", "medium"].includes(text)) return "medium";
  if (["1", "low"].includes(text)) return "low";

  const criticalTerms = ["interest rate decision", "fomc", "monetary policy", "non farm payroll", "non-farm payroll", "cpi", "inflation rate", "boe", "ecb", "fed"];
  if (criticalTerms.some((term) => cat.includes(term) || text.includes(term))) return "critical";

  const highTerms = ["gdp", "unemployment", "retail sales", "pmi", "ppi", "wages", "jobless", "consumer confidence"];
  if (highTerms.some((term) => cat.includes(term) || text.includes(term))) return "high";

  return "medium";
}

function countryToCurrency(country: string) {
  return countryCurrencyMap()[country] || "";
}

function currencyFromFmpCountry(country: string, event?: string) {
  const text = `${country} ${event || ""}`.toLowerCase();
  if (text.includes("united states") || text.includes("us ")) return "USD";
  if (text.includes("united kingdom") || text.includes("uk ")) return "GBP";
  if (text.includes("euro") || text.includes("germany") || text.includes("france") || text.includes("italy") || text.includes("spain")) return "EUR";
  if (text.includes("japan")) return "JPY";
  if (text.includes("switzerland")) return "CHF";
  if (text.includes("australia")) return "AUD";
  if (text.includes("new zealand")) return "NZD";
  if (text.includes("canada")) return "CAD";
  if (text.includes("china")) return "CNH";
  return countryToCurrency(country);
}

function toExternalId(parts: unknown[]) {
  return parts.map((part) => String(part || "").replace(/\W+/g, "-")).join("-").slice(0, 160);
}

function dedupeEvents(events: EconomicCalendarEvent[]) {
  const seen = new Set<string>();
  return events.filter((event) => {
    const key = `${event.provider}:${event.externalId}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function demoEvents(): EconomicCalendarEvent[] {
  const now = new Date();
  const makeTime = (hours: number) => new Date(now.getTime() + hours * 60 * 60 * 1000).toISOString();
  const fetchedAt = new Date().toISOString();

  return [
    {
      externalId: "demo-us-cpi",
      provider: "demo",
      title: "US CPI Inflation Rate",
      country: "United States",
      currency: "USD",
      category: "Inflation Rate",
      eventTime: makeTime(3),
      period: "Demo",
      importance: "critical",
      status: "scheduled",
      previous: "3.4%",
      forecast: "3.3%",
      actual: null,
      unit: "%",
      fetchedAt
    },
    {
      externalId: "demo-uk-boe",
      provider: "demo",
      title: "Bank of England Interest Rate Decision",
      country: "United Kingdom",
      currency: "GBP",
      category: "Interest Rate Decision",
      eventTime: makeTime(20),
      period: "Demo",
      importance: "critical",
      status: "scheduled",
      previous: "5.25%",
      forecast: "5.25%",
      actual: null,
      unit: "%",
      fetchedAt
    },
    {
      externalId: "demo-ez-pmi",
      provider: "demo",
      title: "Euro Area Manufacturing PMI",
      country: "Euro Area",
      currency: "EUR",
      category: "PMI",
      eventTime: makeTime(30),
      period: "Demo",
      importance: "high",
      status: "scheduled",
      previous: "49.8",
      forecast: "50.1",
      actual: null,
      unit: null,
      fetchedAt
    }
  ];
}

async function fetchTradingEconomicsEvents(): Promise<EconomicCalendarEvent[]> {
  const key = process.env.TRADING_ECONOMICS_KEY || process.env.TRADING_ECONOMICS_CLIENT_KEY;
  const countries = process.env.FX_CALENDAR_COUNTRIES || "United States,United Kingdom,Euro Area,Japan,Switzerland,Australia,New Zealand,Canada";
  const now = new Date();
  const start = new Date(now.getTime() - calendarLookbackHours() * 60 * 60 * 1000);
  const end = new Date(now.getTime() + calendarLookaheadDays() * 24 * 60 * 60 * 1000);

  if (!key) return [];

  const base = "https://api.tradingeconomics.com/calendar";
  const params = new URLSearchParams({
    c: key,
    country: countries,
    d1: isoDateOnly(start),
    d2: isoDateOnly(end),
    format: "json"
  });

  const response = await fetch(`${base}?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`Trading Economics calendar fetch failed: ${response.status}`);

  const payload = await response.json() as Array<Record<string, unknown>>;
  const fetchedAt = new Date().toISOString();

  return payload.map((item) => {
    const country = String(item.Country || item.country || "");
    const category = String(item.Category || item.Event || item.category || "Economic Event");
    const eventTime = safeDate(item.Date || item.LastUpdate || item.date);
    const externalId = String(item.CalendarId || item.Ticker || toExternalId([country, category, eventTime]));
    const actual = numericText(item.Actual);
    const currency = String(item.Currency || countryToCurrency(country) || currencyFromFmpCountry(country, category));

    return {
      externalId,
      provider: "trading_economics" as const,
      title: category,
      country,
      currency,
      category,
      eventTime,
      period: String(item.Reference || item.Period || "") || null,
      importance: importanceFromAny(item.Importance, category),
      status: actual !== null ? "released" : "scheduled",
      previous: numericText(item.Previous),
      forecast: numericText(item.Forecast),
      actual,
      revised: numericText(item.Revised),
      unit: String(item.Unit || "") || null,
      sourceUrl: "https://tradingeconomics.com/calendar",
      fetchedAt
    };
  }).filter((event) => event.currency);
}

async function fetchFmpEvents(): Promise<EconomicCalendarEvent[]> {
  const key = process.env.FMP_API_KEY;
  if (!key) return [];

  const now = new Date();
  const start = new Date(now.getTime() - calendarLookbackHours() * 60 * 60 * 1000);
  const end = new Date(now.getTime() + calendarLookaheadDays() * 24 * 60 * 60 * 1000);

  const params = new URLSearchParams({
    from: isoDateOnly(start),
    to: isoDateOnly(end),
    apikey: key
  });

  const response = await fetch(`https://financialmodelingprep.com/stable/economic-calendar?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`FMP calendar fetch failed: ${response.status}`);

  const payload = await response.json() as Array<Record<string, unknown>>;
  const fetchedAt = new Date().toISOString();

  return payload.map((item) => {
    const title = String(item.event || item.title || "Economic Event");
    const country = String(item.country || item.region || "");
    const eventTime = safeDate(item.date);
    const currency = String(item.currency || currencyFromFmpCountry(country, title));
    const actual = numericText(item.actual);

    return {
      externalId: toExternalId([country, title, eventTime]),
      provider: "financial_modeling_prep" as const,
      title,
      country,
      currency,
      category: title,
      eventTime,
      period: String(item.period || "") || null,
      importance: importanceFromAny(item.impact || item.importance, title),
      status: actual !== null ? "released" : "scheduled",
      previous: numericText(item.previous),
      forecast: numericText(item.estimate || item.forecast),
      actual,
      revised: numericText(item.revised),
      unit: String(item.unit || "") || null,
      sourceUrl: "https://site.financialmodelingprep.com/developer/docs/stable/economics-calendar",
      fetchedAt
    };
  }).filter((event) => event.currency);
}

export async function fetchEconomicCalendar(provider: EconomicCalendarProvider = calendarProvider()) {
  let events: EconomicCalendarEvent[] = [];

  if (provider === "trading_economics") {
    events = await fetchTradingEconomicsEvents();
    if (!events.length && process.env.FMP_API_KEY) events = await fetchFmpEvents();
  } else if (provider === "financial_modeling_prep") {
    events = await fetchFmpEvents();
    if (!events.length && (process.env.TRADING_ECONOMICS_KEY || process.env.TRADING_ECONOMICS_CLIENT_KEY)) events = await fetchTradingEconomicsEvents();
  } else {
    events = demoEvents();
  }

  if (!events.length) events = demoEvents();

  const currencySet = new Set(watchedCurrencies());
  return dedupeEvents(events)
    .filter((event) => currencySet.has(event.currency))
    .sort((a, b) => new Date(a.eventTime).getTime() - new Date(b.eventTime).getTime());
}

export function buildRiskWindow(event: EconomicCalendarEvent): CalendarRiskWindow {
  const eventMs = new Date(event.eventTime).getTime();
  const before = blackoutBeforeMinutes(event.importance);
  const after = blackoutAfterMinutes(event.importance);
  const action = actionForImportance(event.importance);

  return {
    eventId: event.id,
    externalId: event.externalId,
    title: event.title,
    currency: event.currency,
    country: event.country,
    category: event.category,
    importance: event.importance,
    eventTime: event.eventTime,
    blackoutStart: new Date(eventMs - before * 60 * 1000).toISOString(),
    blackoutEnd: new Date(eventMs + after * 60 * 1000).toISOString(),
    action,
    reason: `${event.currency} ${event.importance} impact event: ${event.title}`
  };
}

function riskFromWindows(windows: CalendarRiskWindow[]) {
  if (windows.some((window) => window.importance === "critical")) return "critical" as const;
  if (windows.some((window) => window.importance === "high")) return "high" as const;
  if (windows.some((window) => window.importance === "medium")) return "medium" as const;
  return "low" as const;
}

export function evaluateCalendarRisk(pair: string, events: EconomicCalendarEvent[], nowDate = new Date()): CalendarRiskDecision {
  const normalised = normalisePair(pair);
  const currencies = new Set(currenciesFromPair(normalised));
  const now = nowDate.getTime();

  const windows = events
    .filter((event) => currencies.has(event.currency))
    .map(buildRiskWindow)
    .sort((a, b) => new Date(a.blackoutStart).getTime() - new Date(b.blackoutStart).getTime());

  const activeWindows = windows.filter((window) => {
    return now >= new Date(window.blackoutStart).getTime() && now <= new Date(window.blackoutEnd).getTime();
  });

  const upcomingWindows = windows.filter((window) => {
    const start = new Date(window.blackoutStart).getTime();
    return start > now && start <= now + 24 * 60 * 60 * 1000;
  }).slice(0, 10);

  if (activeWindows.some((window) => window.action === "close_only")) {
    return {
      decision: "close_only",
      riskLevel: "critical",
      pair: normalised,
      now: nowDate.toISOString(),
      message: `${normalised} is in a critical economic-calendar blackout. New live entries should be blocked; close/reduce-only actions may continue.`,
      activeWindows,
      upcomingWindows,
      controls: ["Block new entries", "Allow close/reduce-only actions", "Require manual override for live trades", "Log event ID and reason"]
    };
  }

  if (activeWindows.some((window) => window.action === "pause_new_entries" || window.action === "manual_review_only")) {
    return {
      decision: "block_new_entries",
      riskLevel: "high",
      pair: normalised,
      now: nowDate.toISOString(),
      message: `${normalised} has active high-impact calendar risk. Pause new entries until the blackout ends.`,
      activeWindows,
      upcomingWindows,
      controls: ["Pause new entries", "Check spreads/slippage", "Require manual acknowledgement", "Log blackout window"]
    };
  }

  if (activeWindows.some((window) => window.action === "reduce_risk")) {
    return {
      decision: "reduce_risk",
      riskLevel: "medium",
      pair: normalised,
      now: nowDate.toISOString(),
      message: `${normalised} has active medium-impact calendar risk. Reduce risk if trading continues.`,
      activeWindows,
      upcomingWindows,
      controls: ["Reduce position size", "Avoid adding exposure", "Keep stop loss active"]
    };
  }

  if (upcomingWindows.some((window) => window.importance === "critical" || window.importance === "high")) {
    return {
      decision: "watch",
      riskLevel: riskFromWindows(upcomingWindows),
      pair: normalised,
      now: nowDate.toISOString(),
      message: `${normalised} has upcoming high-impact calendar events in the next 24 hours.`,
      activeWindows,
      upcomingWindows,
      controls: ["Prepare blackout", "Avoid opening positions that overlap event windows", "Tighten audit requirements"]
    };
  }

  return {
    decision: "allow",
    riskLevel: "low",
    pair: normalised,
    now: nowDate.toISOString(),
    message: `${normalised} has no active economic-calendar blackout.`,
    activeWindows,
    upcomingWindows,
    controls: ["Respect max daily loss", "Respect max exposure per currency"]
  };
}
