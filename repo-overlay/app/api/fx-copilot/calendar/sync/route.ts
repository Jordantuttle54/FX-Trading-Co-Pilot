import { NextResponse } from "next/server";
import { syncEconomicCalendar } from "@/lib/fx-copilot/calendarSync";

export const dynamic = "force-dynamic";
export const maxDuration = 60;

function isAuthorised(req: Request) {
  const secret = process.env.CRON_SECRET;
  if (!secret) return true;
  return req.headers.get("authorization") === `Bearer ${secret}`
    || req.headers.get("x-cron-secret") === secret
    || req.headers.get("user-agent")?.includes("vercel-cron");
}

export async function GET(req: Request) {
  if (!isAuthorised(req)) {
    return NextResponse.json({ ok: false, error: "Unauthorized calendar sync" }, { status: 401 });
  }

  try {
    const events = await syncEconomicCalendar();
    return NextResponse.json({ ok: true, count: events.length, events });
  } catch (error) {
    console.error("Economic calendar sync failed", error);
    return NextResponse.json({
      ok: false,
      error: error instanceof Error ? error.message : "Calendar sync failed"
    }, { status: 500 });
  }
}
