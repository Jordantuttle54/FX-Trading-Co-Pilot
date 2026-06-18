import type { CalendarImportance, CalendarTradingAction, EconomicCalendarProvider } from "./types";

export const DEFAULT_WATCHED_PAIRS = [
  "EUR/USD",
  "GBP/USD",
  "USD/JPY",
  "USD/CHF",
  "AUD/USD",
  "NZD/USD",
  "USD/CAD",
  "EUR/GBP",
  "EUR/JPY",
  "GBP/JPY"
];

export const DEFAULT_MAJOR_CURRENCIES = ["USD", "GBP", "EUR", "JPY", "CHF", "AUD", "NZD", "CAD"];

export function watchedPairs() {
  const raw = process.env.FX_COPILOT_WATCHED_PAIRS;
  if (!raw) return DEFAULT_WATCHED_PAIRS;
  return raw.split(",").map((pair) => normalisePair(pair.trim())).filter(Boolean);
}

export function watchedCurrencies() {
  const fromPairs = new Set(watchedPairs().flatMap(currenciesFromPair));
  const raw = process.env.FX_COPILOT_WATCHED_CURRENCIES;
  if (raw) {
    raw.split(",").map((currency) => currency.trim().toUpperCase()).filter(Boolean).forEach((currency) => fromPairs.add(currency));
  }
  return Array.from(fromPairs);
}

export function currenciesFromPair(pair: string) {
  return normalisePair(pair).split("/").filter(Boolean);
}

export function normalisePair(pair: string) {
  const value = pair.toUpperCase().replace("-", "/").replace(" ", "");
  if (value.includes("/")) return value;
  if (value.length === 6) return `${value.slice(0, 3)}/${value.slice(3)}`;
  return value;
}

export function fxCopilotMode() {
  const mode = process.env.FX_COPILOT_MODE;
  if (mode === "execution_assist" || mode === "risk_guard" || mode === "advisory") return mode;
  return "risk_guard";
}

export function autoPublishEnabled() {
  return process.env.FX_COPILOT_AUTO_PUBLISH === "true";
}

export function calendarProvider(): EconomicCalendarProvider {
  const provider = process.env.FX_CALENDAR_PROVIDER;
  if (provider === "trading_economics" || provider === "financial_modeling_prep" || provider === "demo") return provider;
  if (process.env.TRADING_ECONOMICS_KEY || process.env.TRADING_ECONOMICS_CLIENT_KEY) return "trading_economics";
  if (process.env.FMP_API_KEY) return "financial_modeling_prep";
  return "demo";
}

export function calendarLookbackHours() {
  return Number(process.env.FX_CALENDAR_LOOKBACK_HOURS || 12);
}

export function calendarLookaheadDays() {
  return Number(process.env.FX_CALENDAR_LOOKAHEAD_DAYS || 14);
}

export function blackoutBeforeMinutes(importance: CalendarImportance) {
  if (importance === "critical") return Number(process.env.FX_CALENDAR_CRITICAL_BEFORE_MINUTES || 120);
  if (importance === "high") return Number(process.env.FX_CALENDAR_HIGH_BEFORE_MINUTES || 60);
  if (importance === "medium") return Number(process.env.FX_CALENDAR_MEDIUM_BEFORE_MINUTES || 20);
  return Number(process.env.FX_CALENDAR_LOW_BEFORE_MINUTES || 0);
}

export function blackoutAfterMinutes(importance: CalendarImportance) {
  if (importance === "critical") return Number(process.env.FX_CALENDAR_CRITICAL_AFTER_MINUTES || 120);
  if (importance === "high") return Number(process.env.FX_CALENDAR_HIGH_AFTER_MINUTES || 60);
  if (importance === "medium") return Number(process.env.FX_CALENDAR_MEDIUM_AFTER_MINUTES || 15);
  return Number(process.env.FX_CALENDAR_LOW_AFTER_MINUTES || 0);
}

export function actionForImportance(importance: CalendarImportance): CalendarTradingAction {
  if (importance === "critical") return "close_only";
  if (importance === "high") return "pause_new_entries";
  if (importance === "medium") return "reduce_risk";
  return "watch";
}

export function countryCurrencyMap() {
  return {
    "United States": "USD",
    "United Kingdom": "GBP",
    "Euro Area": "EUR",
    Germany: "EUR",
    France: "EUR",
    Italy: "EUR",
    Spain: "EUR",
    Japan: "JPY",
    Switzerland: "CHF",
    Australia: "AUD",
    "New Zealand": "NZD",
    Canada: "CAD",
    China: "CNH"
  } as Record<string, string>;
}
