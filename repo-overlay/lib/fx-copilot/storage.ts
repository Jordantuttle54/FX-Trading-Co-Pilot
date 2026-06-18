import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import type { FxBriefing } from "./types";

type BriefingRow = {
  id: string;
  generated_at: string;
  status: FxBriefing["status"];
  mode: FxBriefing["mode"];
  overall_risk: FxBriefing["overallRisk"];
  summary: string;
  items: FxBriefing["items"];
  risk_flags: string[];
  approved_at?: string | null;
  approval_notes?: string | null;
};

function fromRow(row: BriefingRow): FxBriefing {
  return {
    id: row.id,
    generatedAt: row.generated_at,
    status: row.status,
    mode: row.mode,
    overallRisk: row.overall_risk,
    summary: row.summary,
    items: row.items || [],
    riskFlags: row.risk_flags || [],
    approvedAt: row.approved_at,
    approvalNotes: row.approval_notes
  };
}

export async function saveBriefing(briefing: FxBriefing) {
  const supabase = getSupabaseAdmin();
  const { data, error } = await supabase
    .from("fx_copilot_briefings")
    .insert({
      generated_at: briefing.generatedAt,
      status: briefing.status,
      mode: briefing.mode,
      overall_risk: briefing.overallRisk,
      summary: briefing.summary,
      items: briefing.items,
      risk_flags: briefing.riskFlags
    })
    .select("*")
    .single();

  if (error) throw error;
  return fromRow(data as BriefingRow);
}

export async function getLatestBriefing(status?: FxBriefing["status"]) {
  const supabase = getSupabaseAdmin();
  let query = supabase.from("fx_copilot_briefings").select("*").order("generated_at", { ascending: false }).limit(1);
  if (status) query = query.eq("status", status);

  const { data, error } = await query.maybeSingle();
  if (error) throw error;
  return data ? fromRow(data as BriefingRow) : null;
}

export async function approveBriefing(id?: string, notes?: string) {
  const supabase = getSupabaseAdmin();
  const target = id ? { id } : await getLatestBriefing("draft");
  const targetId = typeof target === "object" && target ? target.id : id;
  if (!targetId) throw new Error("No draft briefing available to approve");

  const { data, error } = await supabase
    .from("fx_copilot_briefings")
    .update({
      status: "published",
      approved_at: new Date().toISOString(),
      approval_notes: notes || "Approved from FX co-pilot API"
    })
    .eq("id", targetId)
    .select("*")
    .single();

  if (error) throw error;
  return fromRow(data as BriefingRow);
}

export async function logFxCopilotAudit(eventType: string, payload: Record<string, unknown>) {
  const supabase = getSupabaseAdmin();
  await supabase.from("fx_copilot_audit").insert({
    event_type: eventType,
    payload
  });
}
