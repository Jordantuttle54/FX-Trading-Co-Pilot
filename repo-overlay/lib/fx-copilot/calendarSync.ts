import { fetchEconomicCalendar } from "./economicCalendar";
import { upsertCalendarEvents } from "./calendarStorage";
import { logFxCopilotAudit } from "./storage";

export async function syncEconomicCalendar() {
  const events = await fetchEconomicCalendar();
  const saved = await upsertCalendarEvents(events);

  await logFxCopilotAudit("calendar_synced", {
    fetchedCount: events.length,
    savedCount: saved.length,
    currencies: Array.from(new Set(saved.map((event) => event.currency))),
    highImpactCount: saved.filter((event) => event.importance === "high" || event.importance === "critical").length
  });

  return saved;
}
