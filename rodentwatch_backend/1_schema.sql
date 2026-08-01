-- ============================================================
-- RodentWatch — Supabase schema (run in SQL Editor, step 1)
-- Implements the final ERD: profiles, nodes, maps, alerts,
-- images, sessions + node API keys for hardware ingestion.
-- ============================================================

-- profiles: one row per auth user, carries username + role.
create table public.profiles (
  id         uuid primary key references auth.users(id) on delete cascade,
  username   text unique not null,
  role       text not null default 'user' check (role in ('admin','user')),
  created_at timestamptz not null default now()
);

-- Auto-create a profile whenever an auth user is created.
-- Username and role are read from the signup metadata.
create or replace function public.handle_new_user()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id, username, role)
  values (
    new.id,
    coalesce(new.raw_user_meta_data->>'username', split_part(new.email,'@',1)),
    coalesce(new.raw_user_meta_data->>'role', 'user')
  );
  return new;
end $$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- maps: admin-uploaded site plans (image stored in Supabase Storage).
create table public.maps (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  image_url  text,
  added_by   uuid references public.profiles(id),
  created_at timestamptz not null default now()
);

-- nodes: the fleet. api_key authenticates the hardware (node or gateway).
create table public.nodes (
  id               text primary key,            -- e.g. 'node-01'
  name             text not null,
  location_label   text,
  ap_ssid          text,
  ap_password      text,
  api_key          uuid not null default gen_random_uuid(),
  map_id           uuid references public.maps(id) on delete set null,
  map_x            real,
  map_y            real,
  last_seen        timestamptz,
  firmware_version text,
  model_version    text,
  created_at       timestamptz not null default now()
);

-- alerts: raised by nodes, checked by users.
create table public.alerts (
  id             uuid primary key default gen_random_uuid(),
  node_id        text not null references public.nodes(id) on delete cascade,
  node_alert_id  int not null,
  raised_at      timestamptz not null default now(),  -- gateway/server time
  node_uptime_s  int,
  peak_score     real,
  rat_count      int,
  positives      int,
  shots          int,
  status         text not null default 'unchecked'
                 check (status in ('unchecked','checked','false_alarm')),
  checked_by     uuid references public.profiles(id),
  checked_at     timestamptz,
  unique (node_id, node_alert_id)
);

-- images: metadata of shots saved on the node's SD (files stay on the node).
create table public.images (
  id         uuid primary key default gen_random_uuid(),
  alert_id   uuid not null references public.alerts(id) on delete cascade,
  filename   text not null,
  peak_score real,
  viewed     boolean not null default false
);

-- sessions: log of user connections to nodes.
create table public.sessions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references public.profiles(id) on delete cascade,
  node_id      text not null references public.nodes(id) on delete cascade,
  connected_at timestamptz not null default now()
);

-- Indexes for the queries every screen runs.
create index alerts_status_idx    on public.alerts (status);
create index alerts_node_idx      on public.alerts (node_id, raised_at desc);
create index alerts_raised_idx    on public.alerts (raised_at desc);
create index sessions_user_idx    on public.sessions (user_id, connected_at desc);
create index nodes_last_seen_idx  on public.nodes (last_seen desc);

-- Realtime: let the app subscribe to alert inserts/updates and node heartbeats.
alter publication supabase_realtime add table public.alerts;
alter publication supabase_realtime add table public.nodes;
