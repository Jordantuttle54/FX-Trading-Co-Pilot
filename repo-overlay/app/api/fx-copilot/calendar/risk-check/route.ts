import { NextRequest, NextResponse } from "next/server";
import { getCalendarEvents } from "@/lib/fx-copilot/calendarStorage";
import { evaluateCalendarRisk } from "@/lib/fx-copilot/economicCalendar";
import { currenciesFromPair } from "@/lib/fx-copilot/config";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const pair = req.nextUrl.searchParams.get("pair") || "GBP/USD";
    const now = new Date();
    const from = new Date(now.getTime() - 6 * 60 * 60 * 1000);
    const to = new Date(now.getTime() + 48 * 60 * 60 * 1000);

    const events = await getCalendarEvents({
      from: from.toISOString(),
      to: to.toISOString(),
      currencies: currenciesFromPair(pair),
      limit: 120
    });

    const decision = evaluateCalendarRisk(pair, events, now);
    return NextResponse.json({ ok: true, decision, eventCount: events.length });
  } catch (error) {
    console.error("Calendar risk check failed", error);
    return NextResponse.json({
      ok: false,
      error: error instanceof Error ? error.message : "Calendar risk check failed"
    }, { status: 500 });
  }
}
