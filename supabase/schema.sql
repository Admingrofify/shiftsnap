-- ShiftSnap v2 schema: multi-worker timesheets on Postgres (Supabase free tier).
--
-- Run this once in the Supabase SQL editor (or paste into a migration).
-- The demo app connects with the SERVICE_ROLE key server-side and scopes
-- every query by worker in application code.
--
-- Upgrade path: point employee_id at auth.users instead of workers(id) and
-- switch the app to the anon key + Supabase Auth (magic link). The RLS
-- policies below are written for that world; with the service key they are
-- bypassed, so the app enforces worker scoping itself.
--
-- Note: time_in/time_out are `time` (not timestamptz) on purpose — shift math
-- is done per work-date and timezones only add bugs here. The work `date`
-- is stored separately.

create table if not exists workers (
  id uuid primary key default gen_random_uuid(),
  name text unique not null,
  created_at timestamptz default now()
);

create table if not exists shifts (
  id uuid primary key default gen_random_uuid(),
  employee_id uuid not null references workers(id) on delete cascade,
  date date not null,
  time_in time not null,
  time_out time,                       -- null = clocked in, not yet out
  break_start time,
  break_end time,
  lat float8,
  lng float8,
  accuracy_m float8,
  source text not null default 'chat'
    check (source in ('button', 'photo', 'chat')),
  comment text default '',
  created_at timestamptz default now()
);
create index if not exists shifts_employee_date on shifts(employee_id, date);

create table if not exists admins (
  worker_id uuid primary key references workers(id) on delete cascade
);

alter table workers enable row level security;
alter table shifts enable row level security;
alter table admins enable row level security;

-- No permissive policies yet: with RLS enabled and no policy, the anon key
-- is fully blocked and only the service_role key (server-side) can read/write.
-- When Supabase Auth is wired up, add e.g.:
--
--   create policy "workers see own shifts" on shifts
--     for all using (employee_id = auth.uid());
--   create policy "admins see all shifts" on shifts
--     for all using (exists (select 1 from admins where worker_id = auth.uid()));
