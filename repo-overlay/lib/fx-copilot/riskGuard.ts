import { getCalendarEvents } from "./calendarStorage";
import { evaluateCalendarRisk } from "./economicCalendar";
import { currenciesFromPair, normalisePair } from "./config";
import type { FxBriefing, FxImpactItem, TradeRiskCheckInput, TradeRiskDecision } from "./types";

function riskRank(level: string) {
  if (level === "critical") return 4;
  if (level === "high") return 3;
  if (level === "medium") return 2;
  return 1;
}

function matchesPair(item: FxImpactItem, pair: string) {
  const normalised = normalisePair(pair);
  const currencies = currenciesFromPair(normalised);
  return item.affectedPairs.map(normalisePair).includes(normalised)
    || currencies.some((currency) => item.affectedCurrencies.includes(currency));
}

export async function evaluateCombinedTradeRisk(input: TradeRiskCheckInput, briefing: FxBriefing | null): Promise<TradeRiskDecision> {
  const now = new Date();
  const from = new Date(now.getTime() - 6 * 60 * 60 * 1000).toISOString();
  const to = new Date(now.getTime() + 48 * 60 * 60 * 1000).toISOString();
  const calendarEvents = await getCalendarEvents({ from, to, currencies: currenciesFromPair(input.pair), limit: 100 });
  const calendar = evaluateCalendarRisk(input.pair, calendarEvents, now);

  if (calendar.decision === "close_only" || calendar.decision === "block_new_entries") {
    return {
      decision: "block",
      riskLevel: calendar.riskLevel,
      message: calendar.message,
      matchedItems: [],
      calendar,
      controls: calendar.controls
    };
  }

  if (!briefing) {
    return {
      decision: calendar.decision === "reduce_risk" || calendar.decision === "watch" ? "reduce_risk" : "paper_only",
      riskLevel: calendar.riskLevel === "low" ? "medium" : calendar.riskLevel,
      message: briefing ? calendar.message : "No FX news briefing is available yet. Use paper/manual-review mode unless the execution engine has another trusted data source.",
      matchedItems: [],
      calendar,
      controls: [...calendar.controls, "Require manual review when news briefing is missing"]
    };
  }

  const matchedItems = briefing.items
    .filter((item) => matchesPair(item, input.pair))
    .sort((a, b) => riskRank(b.impactLevel) - riskRank(a.impactLevel))
    .slice(0, 8);

  const highest = matchedItems[0]?.impactLevel || briefing.overallRisk;
  const hasCritical = briefing.overallRisk === "critical" || matchedItems.some((item) => item.impactLevel === "critical" && item.confidence >= 0.7);
  const hasHigh = briefing.overallRisk === "high" || matchedItems.some((item) => item.impactLevel === "high" && item.confidence >= 0.65);
  const pauseRequested = matchedItems.some((item) => item.suggestedPlatformState === "pause_new_trades" || item.suggestedPlatformState === "manual_review_only");

  if (hasCritical || pauseRequested) {
    return {
      decision: "block",
      riskLevel: hasCritical ? "critical" : highest,
      message: `${normalisePair(input.pair)} is blocked for live execution until manual review because current market/news risk is elevated.`,
      matchedItems,
      calendar,
      controls: ["Block new live entries", "Allow close/reduce-only actions", "Record audit reason", "Require manual approval", ...calendar.controls]
    };
  }

  if (hasHigh || calendar.decision === "reduce_risk" || calendar.decision === "watch") {
    return {
      decision: "reduce_risk",
      riskLevel: hasHigh ? "high" : calendar.riskLevel,
      message: `${normalisePair(input.pair)} may proceed only with reduced risk and manual acknowledgement.`,
      matchedItems,
      calendar,
      controls: ["Reduce position size", "Check spread/slippage", "Avoid martingale/revenge trades", "Log reason before execution", ...calendar.controls]
    };
  }

  return {
    decision: "allow",
    riskLevel: highest,
    message: `${normalisePair(input.pair)} passed the current FX news and economic-calendar guard.`,
    matchedItems,
    calendar,
    controls: ["Respect max daily loss", "Respect max exposure per currency", "Keep stop loss active", ...calendar.controls]
  };
}
