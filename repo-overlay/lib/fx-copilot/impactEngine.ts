import OpenAI from "openai";
import { watchedPairs } from "./config";
import type { FxBriefing, FxImpactItem, NewsArticle } from "./types";

type AiBriefing = Pick<FxBriefing, "overallRisk" | "summary" | "riskFlags" | "items">;

const SYSTEM_PROMPT = `You are an FX market-risk analyst for a trading platform.
Classify world news by likely FX impact.
Never give guaranteed trading instructions.
Never say a user should buy or sell now.
Return JSON only with:
{
  "summary": "short platform-ready summary",
  "overallRisk": "low|medium|high|critical",
  "riskFlags": ["..."],
  "items": [{
    "headline": "...",
    "source": "...",
    "url": "...",
    "publishedAt": "...",
    "affectedCurrencies": ["USD"],
    "affectedPairs": ["GBP/USD"],
    "eventType": "central_bank|inflation|jobs|growth|energy|geopolitical|risk_sentiment|other",
    "bias": "bullish|bearish|neutral|mixed",
    "impactLevel": "low|medium|high|critical",
    "confidence": 0.0,
    "timeHorizon": "intraday|swing|weekly|unknown",
    "reasoning": "brief reason",
    "suggestedPlatformState": "normal|watch|reduce_risk|pause_new_trades|manual_review_only"
  }]
}`;

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function clampConfidence(value: unknown) {
  const numeric = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(numeric)) return 0.5;
  return Math.max(0, Math.min(1, numeric));
}

function isImpact(value: unknown): FxBriefing["overallRisk"] {
  return value === "critical" || value === "high" || value === "medium" || value === "low" ? value : "medium";
}

function normaliseItem(item: Record<string, unknown>, index: number): FxImpactItem {
  const url = String(item.url || "");
  return {
    id: `fx-impact-${index}-${Buffer.from(url || String(item.headline || index)).toString("base64url").slice(0, 10)}`,
    headline: String(item.headline || "Market update"),
    source: String(item.source || "Unknown source"),
    url,
    publishedAt: String(item.publishedAt || new Date().toISOString()),
    affectedCurrencies: asArray(item.affectedCurrencies).map(String).slice(0, 8),
    affectedPairs: asArray(item.affectedPairs).map(String).slice(0, 12),
    eventType: String(item.eventType || "other"),
    bias: item.bias === "bullish" || item.bias === "bearish" || item.bias === "neutral" || item.bias === "mixed" ? item.bias : "mixed",
    impactLevel: isImpact(item.impactLevel),
    confidence: clampConfidence(item.confidence),
    timeHorizon: item.timeHorizon === "intraday" || item.timeHorizon === "swing" || item.timeHorizon === "weekly" || item.timeHorizon === "unknown" ? item.timeHorizon : "unknown",
    reasoning: String(item.reasoning || "AI classified this as potentially relevant to watched FX pairs."),
    suggestedPlatformState: item.suggestedPlatformState === "pause_new_trades" || item.suggestedPlatformState === "manual_review_only" || item.suggestedPlatformState === "reduce_risk" || item.suggestedPlatformState === "normal" || item.suggestedPlatformState === "watch" ? item.suggestedPlatformState : "watch"
  };
}

function fallbackBriefing(articles: NewsArticle[]): AiBriefing {
  const watched = watchedPairs();
  const highRiskWords = ["rate", "inflation", "cpi", "jobs", "payroll", "central bank", "war", "oil", "tariff", "election"];
  const items = articles.slice(0, 12).map((article, index) => {
    const text = `${article.title} ${article.summary}`.toLowerCase();
    const high = highRiskWords.some((word) => text.includes(word));
    return normaliseItem({
      headline: article.title,
      source: article.source,
      url: article.url,
      publishedAt: article.publishedAt,
      affectedCurrencies: ["USD", "GBP", "EUR", "JPY"],
      affectedPairs: watched.slice(0, 5),
      eventType: high ? "macro" : "other",
      bias: "mixed",
      impactLevel: high ? "high" : "medium",
      confidence: high ? 0.62 : 0.45,
      timeHorizon: "intraday",
      reasoning: "Rule-based fallback used because AI classification was unavailable.",
      suggestedPlatformState: high ? "manual_review_only" : "watch"
    }, index);
  });

  return {
    overallRisk: items.some((item) => item.impactLevel === "high") ? "high" : "medium",
    summary: "FX co-pilot scanned market news. AI classification was unavailable, so a conservative rule-based briefing was generated.",
    riskFlags: ["AI classifier unavailable", "Manual review recommended"],
    items
  };
}

export async function classifyFxImpact(articles: NewsArticle[]): Promise<AiBriefing> {
  if (!process.env.OPENAI_API_KEY) return fallbackBriefing(articles);

  try {
    const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
    const model = process.env.FX_COPILOT_OPENAI_MODEL || "gpt-4o-mini";

    const completion = await openai.chat.completions.create({
      model,
      temperature: 0.2,
      response_format: { type: "json_object" },
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        {
          role: "user",
          content: JSON.stringify({
            watchedPairs: watchedPairs(),
            articles: articles.slice(0, 25)
          })
        }
      ]
    });

    const content = completion.choices[0]?.message?.content || "{}";
    const parsed = JSON.parse(content) as Record<string, unknown>;

    return {
      overallRisk: isImpact(parsed.overallRisk),
      summary: String(parsed.summary || "FX co-pilot briefing generated."),
      riskFlags: asArray(parsed.riskFlags).map(String).slice(0, 12),
      items: asArray(parsed.items).map((item, index) => normaliseItem(item as Record<string, unknown>, index))
    };
  } catch (error) {
    console.error("FX co-pilot classification failed", error);
    return fallbackBriefing(articles);
  }
}
