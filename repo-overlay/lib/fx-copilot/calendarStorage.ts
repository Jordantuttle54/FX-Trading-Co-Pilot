import { getSupabaseAdmin } from "@/lib/supabaseAdmin";
import type { EconomicCalendarEvent } from "./types";

type EventRow = {
  id: string;
  external_id: string;
  provider: EconomicCalendarEvent["provider"];
  title: string;
  country: string;
  currency: string;
  category: string;
  event_time: string;
  period?: string | null;
  importance: EconomicCalendarEvent["importance"];
  status: EconomicCalendarEvent["status"];
  previous?: string | number | null;
  forecast?: string | number | null;
  actual?: string | number | null;
  revised?: string | number | null;
  unit?: string | null;
  source_url?: string | null;
  fetched_at: string;
  updated_at: string;
};

function fromRow(row: EventRow): EconomicCalendarEvent {
  return {
    id: row.id,
    externalId: row.external_id,
    provider: row.provider,
    title: row.title,
    country: row.country,
    currency: row.currency,
    category: row.category,
    eventTime: row.event_time,
    period: row.period,
    importance: row.importance,
    status: row.status,
    previous: row.previous,
    forecast: row.forecast,
    actual: row.actual,
    revised: row.revised,
    unit: row.unit,
    sourceUrl: row.source_url,
    fetchedAt: row.fetched_at,
    updatedAt: row.updated_at
  };
}

export async function upsertCalendarEvents(events: EconomicCalendarEvent[]) {
  if (!events.length) return [];

  const supabase = getSupabaseAdmin();
  const rows = events.map((event) => ({
    external_id: event.externalId,
    provider: event.provider,
    title: event.title,
    country: event.country,
    currency: event.currency,
    category: event.category,
    event_time: event.eventTime,
    period: event.period || null,
    importance: event.importance,
    status: event.status,
    previous: event.previous ?? null,
    forecast: event.forecast ?? null,
    actual: event.actual ?? null,
    revised: event.revised ?? null,
    unit: event.unit || null,
    source_url: event.sourceUrl || null,
    fetched_at: event.fetchedAt
  }));

  const { data, error } = await supabase
    .from("fx_economic_calendar_events")
    .upsert(rows, { onConflict: "provider,external_id" })
    .select("*");

  if (error) throw error;
  return (data || []).map((row) => fromRow(row as EventRow));
}

export async function getCalendarEvents(options?: {
  from?: string;
  to?: string;
  currencies?: string[];
  importance?: string[];
  limit?: number;
}) {
  const supabase = getSupabaseAdmin();
  let query = supabase
    .from("fx_economic_calendar_events")
    .select("*")
    .order("event_time", { ascending: true })
    .limit(options?.limit || 250);

  if (options?.from) query = query.gte("event_time", options.from);
  if (options?.to) query = query.lte("event_time", options.to);
  if (options?.currencies?.length) query = query.in("currency", options.currencies);
  if (options?.importance?.length) query = query.in("importance", options.importance);

  const { data, error } = await query;
  if (error) throw error;
  return (data || []).map((row) => fromRow(row as EventRow));
}

export async function getUpcomingCalendarEvents(hours = 48, currencies?: string[]) {
  const now = new Date();
  const to = new Date(now.getTime() + hours * 60 * 60 * 1000);
  return getCalendarEvents({
    from: now.toISOString(),
    to: to.toISOString(),
    currencies,
    limit: 200
  });
}
