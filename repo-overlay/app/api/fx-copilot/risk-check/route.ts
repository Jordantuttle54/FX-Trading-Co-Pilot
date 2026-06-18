import { NextRequest, NextResponse } from "next/server";
import { evaluateCombinedTradeRisk } from "@/lib/fx-copilot/riskGuard";
import { getLatestBriefing } from "@/lib/fx-copilot/storage";
import type { TradeRiskCheckInput } from "@/lib/fx-copilot/types";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  try {
    const body = (await req.json()) as TradeRiskCheckInput;
    if (!body.pair) {
      return NextResponse.json({ ok: false, error: "pair is required" }, { status: 400 });
    }

    const briefing = await getLatestBriefing("published") || await getLatestBriefing("draft");
    const decision = await evaluateCombinedTradeRisk(body, briefing);

    return NextResponse.json({ ok: true, decision, briefingId: briefing?.id || null });
  } catch (error) {
    console.error("FX co-pilot risk check failed", error);
    return NextResponse.json({
      ok: false,
      error: error instanceof Error ? error.message : "Risk check failed"
    }, { status: 500 });
  }
}
