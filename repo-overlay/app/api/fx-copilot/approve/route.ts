import { NextRequest, NextResponse } from "next/server";
import { approveBriefing, logFxCopilotAudit } from "@/lib/fx-copilot/storage";

export const dynamic = "force-dynamic";

function isAdmin(req: NextRequest) {
  const adminKey = process.env.FX_COPILOT_ADMIN_KEY;
  if (!adminKey) return false;

  const bearer = req.headers.get("authorization");
  const xAdminKey = req.headers.get("x-admin-key");

  return bearer === `Bearer ${adminKey}` || xAdminKey === adminKey;
}

export async function POST(req: NextRequest) {
  if (!isAdmin(req)) {
    return NextResponse.json({ ok: false, error: "Unauthorized approval request" }, { status: 401 });
  }

  try {
    const body = await req.json().catch(() => ({})) as { id?: string; notes?: string };
    const briefing = await approveBriefing(body.id, body.notes);
    await logFxCopilotAudit("briefing_approved", { briefingId: briefing.id, notes: body.notes || null });
    return NextResponse.json({ ok: true, briefing });
  } catch (error) {
    console.error("FX co-pilot approval failed", error);
    return NextResponse.json({
      ok: false,
      error: error instanceof Error ? error.message : "Approval failed"
    }, { status: 500 });
  }
}
