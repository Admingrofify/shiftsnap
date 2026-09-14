-- ShiftSnap v2 schema: multi-worker timesheets on Postgres (Supabase free tier).
--
-- Run once in the Supabase SQL editor (safe to re-run: all idempotent).
--
-- Identity: Supabase Auth (email magic link). Each worker signs in with
-- their email; auth.users.id becomes workers.id, and Row Level Security
-- guarantees workers can only see their own shifts. The app connects with
-- the ANON key and the worker's own JWT — no service_role key needed.
--
-- Dashboard setup (one time): Authentication -> URL Configuration ->
--   Site URL = https://shiftssnap.com
--   Redirect URLs += https://shiftssnap.com/**
--
-- Note: time_in/time_out are `time` (not timestamptz) on purpose — shift math
-- is done per work-date and timezones only add bugs here. The work `date`
-- is stored separately.

create table if not exists workers (
  id uuid primary key references auth.users(id) on delete cascade,
  name text not null,
  email text,
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

-- Workers see only their own rows.
drop policy if exists "workers own shifts" on shifts;
create policy "workers own shifts" on shifts
  for all using (employee_id = auth.uid());

drop policy if exists "workers own profile" on workers;
create policy "workers own profile" on workers
  for all using (id = auth.uid());

-- Admins (listed in admins table) see everything, for team reports/export.
drop policy if exists "admins see all shifts" on shifts;
create policy "admins see all shifts" on shifts
  for all using (exists (select 1 from admins where worker_id = auth.uid()));

drop policy if exists "admins see all workers" on workers;
create policy "admins see all workers" on workers
  for select using (exists (select 1 from admins where worker_id = auth.uid()));

-- Admins can check their own admin row (needed for the in-app admin check).
drop policy if exists "users see own admin row" on admins;
create policy "users see own admin row" on admins
  for select using (worker_id = auth.uid());

-- To make someone an admin, run (as a SQL editor admin):
--   insert into admins (worker_id)
--   select id from workers where email = 'boss@company.com';
