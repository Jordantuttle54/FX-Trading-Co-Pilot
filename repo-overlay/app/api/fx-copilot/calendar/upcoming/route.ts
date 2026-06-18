import { NextRequest, NextResponse } from "next/server";
import { getCalendarEvents } from "@/lib/fx-copilot/calendarStorage";
import { watchedCurrencies } from "@/lib/fx-copilot/config";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const hours = Number(req.nextUrl.searchParams.get("hours") || 72);
    const currencies = req.nextUrl.searchParams.get("currencies")?.split(",").map((value) => value.trim().toUpperCase()).filter(Boolean) || watchedCurrencies();
    const importance = req.nextUrl.searchParams.get("importance")?.split(",").map((value) => value.trim()).filter(Boolean);

    const now = new Date();
    const to = new Date(now.getTime() + hours * 60 * 60 * 1000);
    const events = await getCalendarEvents({
      from: now.toISOString(),
      to: to.toISOString(),
      currencies,
      importance,
      limit: 250
    });

    return NextResponse.json({ ok: true, events });
  } catch (error) {
    console.error("Economic calendar upcoming failed", error);
    return NextResponse.json({
      ok: false,
      error: error instanceof Error ? error.message : "Could not load economic calendar"
    }, { status: 500 });
  }
}
