import { NextResponse } from "next/server";
import { runFxCopilotScan } from "@/lib/fx-copilot/runScan";
import { syncEconomicCalendar } from "@/lib/fx-copilot/calendarSync";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

function isAuthorised(req: Request) {
  const secret = process.env.CRON_SECRET;
  if (!secret) return true;

  const bearer = req.headers.get("authorization");
  const xSecret = req.headers.get("x-cron-secret");

  return bearer === `Bearer ${secret}` || xSecret === secret || req.headers.get("user-agent")?.includes("vercel-cron");
}

export async function GET(req: Request) {
  if (!isAuthorised(req)) {
    return NextResponse.json({ ok: false, error: "Unauthorized cron request" }, { status: 401 });
  }

  try {
    const [calendarEvents, briefing] = await Promise.all([
      syncEconomicCalendar(),
      runFxCopilotScan()
    ]);

    return NextResponse.json({
      ok: true,
      calendar: {
        syncedCount: calendarEvents.length,
        highImpactCount: calendarEvents.filter((event) => event.importance === "high" || event.importance === "critical").length
      },
      briefing
    });
  } catch (error) {
    console.error("FX co-pilot cron failed", error);
    return NextResponse.json({
      ok: false,
      error: error instanceof Error ? error.message : "FX co-pilot scan failed"
    }, { status: 500 });
  }
}
