export type FxBias = "bullish" | "bearish" | "neutral" | "mixed";
export type FxImpactLevel = "low" | "medium" | "high" | "critical";
export type FxBriefingStatus = "draft" | "published" | "archived";
export type FxCopilotMode = "advisory" | "risk_guard" | "execution_assist";

export type NewsArticle = {
  id: string;
  title: string;
  summary: string;
  url: string;
  source: string;
  publishedAt: string;
};

export type FxImpactItem = {
  id: string;
  headline: string;
  source: string;
  url: string;
  publishedAt: string;
  affectedCurrencies: string[];
  affectedPairs: string[];
  eventType: string;
  bias: FxBias;
  impactLevel: FxImpactLevel;
  confidence: number;
  timeHorizon: "intraday" | "swing" | "weekly" | "unknown";
  reasoning: string;
  suggestedPlatformState: "normal" | "watch" | "reduce_risk" | "pause_new_trades" | "manual_review_only";
};

export type FxBriefing = {
  id?: string;
  generatedAt: string;
  status: FxBriefingStatus;
  mode: FxCopilotMode;
  overallRisk: FxImpactLevel;
  summary: string;
  items: FxImpactItem[];
  riskFlags: string[];
  approvedAt?: string | null;
  approvalNotes?: string | null;
};

export type EconomicCalendarProvider = "trading_economics" | "financial_modeling_prep" | "demo";
export type EconomicEventStatus = "scheduled" | "released" | "revised" | "cancelled" | "tentative";
export type CalendarImportance = "low" | "medium" | "high" | "critical";
export type CalendarTradingAction = "normal" | "watch" | "reduce_risk" | "pause_new_entries" | "manual_review_only" | "close_only";

export type EconomicCalendarEvent = {
  id?: string;
  externalId: string;
  provider: EconomicCalendarProvider;
  title: string;
  country: string;
  currency: string;
  category: string;
  eventTime: string;
  period?: string | null;
  importance: CalendarImportance;
  status: EconomicEventStatus;
  previous?: string | number | null;
  forecast?: string | number | null;
  actual?: string | number | null;
  revised?: string | number | null;
  unit?: string | null;
  sourceUrl?: string | null;
  fetchedAt: string;
  updatedAt?: string;
};

export type CalendarRiskWindow = {
  eventId?: string;
  externalId: string;
  title: string;
  currency: string;
  country: string;
  category: string;
  importance: CalendarImportance;
  eventTime: string;
  blackoutStart: string;
  blackoutEnd: string;
  action: CalendarTradingAction;
  reason: string;
};

export type CalendarRiskDecision = {
  decision: "allow" | "watch" | "reduce_risk" | "block_new_entries" | "close_only" | "paper_only";
  riskLevel: FxImpactLevel;
  pair: string;
  now: string;
  message: string;
  activeWindows: CalendarRiskWindow[];
  upcomingWindows: CalendarRiskWindow[];
  controls: string[];
};

export type TradeRiskCheckInput = {
  pair: string;
  side?: "buy" | "sell" | "long" | "short" | "unknown";
  strategy?: string;
  intendedRiskPct?: number;
  entryReason?: string;
};

export type TradeRiskDecision = {
  decision: "allow" | "reduce_risk" | "block" | "paper_only";
  riskLevel: FxImpactLevel;
  message: string;
  matchedItems: FxImpactItem[];
  calendar?: CalendarRiskDecision;
  controls: string[];
};
