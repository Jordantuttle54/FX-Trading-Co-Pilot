import { NextRequest, NextResponse } from "next/server";
import { getLatestBriefing } from "@/lib/fx-copilot/storage";
import type { FxBriefingStatus } from "@/lib/fx-copilot/types";

export const dynamic = "force-dynamic";

function statusFromParam(value: string | null): FxBriefingStatus | undefined {
  if (value === "draft" || value === "published" || value === "archived") return value;
  return undefined;
}

export async function GET(req: NextRequest) {
  try {
    const status = statusFromParam(req.nextUrl.searchParams.get("status"));
    const briefing = await getLatestBriefing(status);
    return NextResponse.json({ ok: true, briefing });
  } catch (error) {
    console.error("FX co-pilot latest failed", error);
    return NextResponse.json({
      ok: false,
      error: error instanceof Error ? error.message : "Could not load latest FX briefing"
    }, { status: 500 });
  }
}
