import { NextResponse } from "next/server";
import { calendarProvider } from "@/lib/fx-copilot/config";

export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json({
    ok: true,
    checks: {
      openai: Boolean(process.env.OPENAI_API_KEY),
      supabaseUrl: Boolean(process.env.NEXT_PUBLIC_SUPABASE_URL),
      supabaseServiceRole: Boolean(process.env.SUPABASE_SERVICE_ROLE_KEY),
      cronSecret: Boolean(process.env.CRON_SECRET),
      adminKey: Boolean(process.env.FX_COPILOT_ADMIN_KEY),
      alphaVantage: Boolean(process.env.ALPHA_VANTAGE_API_KEY),
      tradingEconomics: Boolean(process.env.TRADING_ECONOMICS_KEY || process.env.TRADING_ECONOMICS_CLIENT_KEY),
      fmp: Boolean(process.env.FMP_API_KEY)
    },
    mode: process.env.FX_COPILOT_MODE || "risk_guard",
    autoPublish: process.env.FX_COPILOT_AUTO_PUBLISH === "true",
    calendarProvider: calendarProvider()
  });
}
