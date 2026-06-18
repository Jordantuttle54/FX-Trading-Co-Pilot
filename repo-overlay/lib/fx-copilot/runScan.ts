import { autoPublishEnabled, fxCopilotMode } from "./config";
import { classifyFxImpact } from "./impactEngine";
import { fetchWorldFxNews } from "./sources";
import { logFxCopilotAudit, saveBriefing } from "./storage";
import type { FxBriefing } from "./types";

export async function runFxCopilotScan() {
  const articles = await fetchWorldFxNews();
  const analysis = await classifyFxImpact(articles);

  const briefing: FxBriefing = {
    generatedAt: new Date().toISOString(),
    status: autoPublishEnabled() ? "published" : "draft",
    mode: fxCopilotMode(),
    overallRisk: analysis.overallRisk,
    summary: analysis.summary,
    riskFlags: analysis.riskFlags,
    items: analysis.items
  };

  const saved = await saveBriefing(briefing);
  await logFxCopilotAudit("scan_completed", {
    briefingId: saved.id,
    articleCount: articles.length,
    itemCount: saved.items.length,
    overallRisk: saved.overallRisk,
    status: saved.status
  });

  return saved;
}
