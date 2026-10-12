-- ============================================================
-- RodentWatch — RLS policies (run in SQL Editor, step 2)
-- The role split is enforced HERE, at the database, not in the app.
-- ============================================================

-- Helper: is the calling user an admin?
create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (
    select 1 from public.profiles
    where id = auth.uid() and role = 'admin'
  );
$$;

alter table public.profiles enable row level security;
alter table public.maps     enable row level security;
alter table public.nodes    enable row level security;
alter table public.alerts   enable row level security;
alter table public.images   enable row level security;
alter table public.sessions enable row level security;

-- ── profiles ──
create policy "profiles: read all"            on public.profiles
  for select to authenticated using (true);
create policy "profiles: admin manages"       on public.profiles
  for all to authenticated using (public.is_admin()) with check (public.is_admin());

-- ── maps: everyone reads, only admins write ──
create policy "maps: read all"                on public.maps
  for select to authenticated using (true);
create policy "maps: admin insert"            on public.maps
  for insert to authenticated with check (public.is_admin());
create policy "maps: admin update"            on public.maps
  for update to authenticated using (public.is_admin());
create policy "maps: admin delete"            on public.maps
  for delete to authenticated using (public.is_admin());

-- ── nodes: everyone reads the fleet, only admins register/delete ──
-- Note: ap_password + api_key are still visible to any signed-in user with
-- plain select; the app needs ap creds for QR join, so this is accepted for v1.
create policy "nodes: read all"               on public.nodes
  for select to authenticated using (true);
create policy "nodes: admin insert"           on public.nodes
  for insert to authenticated with check (public.is_admin());
create policy "nodes: admin update"           on public.nodes
  for update to authenticated using (public.is_admin());
create policy "nodes: admin delete"           on public.nodes
  for delete to authenticated using (public.is_admin());

-- ── alerts: everyone reads; any user may mark checked; only the check
--    fields may effectively change (enforced by a trigger below);
--    inserts come ONLY from the ingest edge function (service role bypasses RLS)
create policy "alerts: read all"              on public.alerts
  for select to authenticated using (true);
create policy "alerts: users update checks"   on public.alerts
  for update to authenticated using (true) with check (true);
create policy "alerts: admin delete"          on public.alerts
  for delete to authenticated using (public.is_admin());

-- Guard: non-admin updates may only change status/checked_by/checked_at,
-- and checked_by must be the caller.
create or replace function public.guard_alert_update()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if public.is_admin() then return new; end if;
  if new.node_id       is distinct from old.node_id
  or new.node_alert_id is distinct from old.node_alert_id
  or new.raised_at     is distinct from old.raised_at
  or new.peak_score    is distinct from old.peak_score
  or new.rat_count     is distinct from old.rat_count then
    raise exception 'only check status may be changed';
  end if;
  if new.status in ('checked','false_alarm') and new.checked_by is distinct from auth.uid() then
    raise exception 'checked_by must be the calling user';
  end if;
  return new;
end $$;

create trigger alerts_guard before update on public.alerts
  for each row execute function public.guard_alert_update();

-- ── images ──
create policy "images: read all"              on public.images
  for select to authenticated using (true);
create policy "images: users mark viewed"     on public.images
  for update to authenticated using (true) with check (true);

-- ── sessions: users insert their own, read all ──
create policy "sessions: read all"            on public.sessions
  for select to authenticated using (true);
create policy "sessions: own insert"          on public.sessions
  for insert to authenticated with check (user_id = auth.uid());
