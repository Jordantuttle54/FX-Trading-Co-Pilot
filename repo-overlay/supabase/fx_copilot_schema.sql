create extension if not exists "pgcrypto";

create table if not exists public.fx_copilot_briefings (
  id uuid primary key default gen_random_uuid(),
  generated_at timestamptz not null default now(),
  status text not null default 'draft' check (status in ('draft', 'published', 'archived')),
  mode text not null default 'risk_guard' check (mode in ('advisory', 'risk_guard', 'execution_assist')),
  overall_risk text not null default 'medium' check (overall_risk in ('low', 'medium', 'high', 'critical')),
  summary text not null,
  items jsonb not null default '[]'::jsonb,
  risk_flags jsonb not null default '[]'::jsonb,
  approved_at timestamptz,
  approval_notes text,
  created_at timestamptz not null default now()
);

create table if not exists public.fx_economic_calendar_events (
  id uuid primary key default gen_random_uuid(),
  external_id text not null,
  provider text not null check (provider in ('trading_economics', 'financial_modeling_prep', 'demo')),
  title text not null,
  country text not null,
  currency text not null,
  category text not null,
  event_time timestamptz not null,
  period text,
  importance text not null default 'medium' check (importance in ('low', 'medium', 'high', 'critical')),
  status text not null default 'scheduled' check (status in ('scheduled', 'released', 'revised', 'cancelled', 'tentative')),
  previous jsonb,
  forecast jsonb,
  actual jsonb,
  revised jsonb,
  unit text,
  source_url text,
  fetched_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(provider, external_id)
);

create table if not exists public.fx_copilot_audit (
  id uuid primary key default gen_random_uuid(),
  event_type text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists fx_copilot_briefings_generated_at_idx
  on public.fx_copilot_briefings (generated_at desc);

create index if not exists fx_copilot_briefings_status_idx
  on public.fx_copilot_briefings (status);

create index if not exists fx_economic_calendar_event_time_idx
  on public.fx_economic_calendar_events (event_time asc);

create index if not exists fx_economic_calendar_currency_idx
  on public.fx_economic_calendar_events (currency);

create index if not exists fx_economic_calendar_importance_idx
  on public.fx_economic_calendar_events (importance);

create or replace function public.fx_set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists fx_economic_calendar_events_updated_at on public.fx_economic_calendar_events;

create trigger fx_economic_calendar_events_updated_at
before update on public.fx_economic_calendar_events
for each row
execute function public.fx_set_updated_at();

alter table public.fx_copilot_briefings enable row level security;
alter table public.fx_economic_calendar_events enable row level security;
alter table public.fx_copilot_audit enable row level security;

-- Server-side API routes use SUPABASE_SERVICE_ROLE_KEY and bypass RLS.
-- Do not expose service role keys to the browser.
