import type { NewsArticle } from "./types";

function safeDate(value: unknown) {
  if (!value || typeof value !== "string") return new Date().toISOString();
  const parsed = new Date(value);
  if (!Number.isNaN(parsed.getTime())) return parsed.toISOString();

  const match = value.match(/^(\d{4})(\d{2})(\d{2})T?(\d{2})(\d{2})(\d{2})/);
  if (match) {
    const [, y, m, d, hh, mm, ss] = match;
    return new Date(`${y}-${m}-${d}T${hh}:${mm}:${ss}Z`).toISOString();
  }

  return new Date().toISOString();
}

function articleId(prefix: string, url: string, index: number) {
  return `${prefix}-${index}-${Buffer.from(url).toString("base64url").slice(0, 12)}`;
}

export async function fetchGdeltNews(): Promise<NewsArticle[]> {
  const query = [
    "forex",
    "currency",
    "central bank",
    "interest rates",
    "inflation",
    "jobs report",
    "GDP",
    "oil prices",
    "geopolitical risk"
  ].join(" OR ");

  const url = `https://api.gdeltproject.org/api/v2/doc/doc?query=${encodeURIComponent(query)}&mode=artlist&format=json&maxrecords=30&sort=DateDesc`;

  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`GDELT fetch failed: ${response.status}`);

  const payload = (await response.json()) as { articles?: Array<Record<string, unknown>> };
  return (payload.articles || []).map((item, index) => {
    const urlValue = String(item.url || "");
    const title = String(item.title || "Untitled market update");
    return {
      id: articleId("gdelt", urlValue || title, index),
      title,
      summary: String(item.seendate || item.domain || ""),
      url: urlValue,
      source: String(item.domain || "GDELT"),
      publishedAt: safeDate(item.seendate)
    };
  }).filter((article) => article.url && article.title);
}

export async function fetchAlphaVantageNews(): Promise<NewsArticle[]> {
  const key = process.env.ALPHA_VANTAGE_API_KEY;
  if (!key) return [];

  const url = `https://www.alphavantage.co/query?function=NEWS_SENTIMENT&topics=forex,economy_monetary,financial_markets&sort=LATEST&limit=30&apikey=${encodeURIComponent(key)}`;
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`Alpha Vantage fetch failed: ${response.status}`);

  const payload = (await response.json()) as { feed?: Array<Record<string, unknown>> };
  return (payload.feed || []).map((item, index) => {
    const urlValue = String(item.url || "");
    const title = String(item.title || "Untitled market update");
    return {
      id: articleId("alpha", urlValue || title, index),
      title,
      summary: String(item.summary || ""),
      url: urlValue,
      source: String(item.source || "Alpha Vantage"),
      publishedAt: safeDate(item.time_published)
    };
  }).filter((article) => article.url && article.title);
}

export async function fetchWorldFxNews(): Promise<NewsArticle[]> {
  const settled = await Promise.allSettled([fetchGdeltNews(), fetchAlphaVantageNews()]);
  const articles = settled.flatMap((result) => result.status === "fulfilled" ? result.value : []);

  const seen = new Set<string>();
  return articles.filter((article) => {
    const key = article.url || article.title;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  }).slice(0, 40);
}
