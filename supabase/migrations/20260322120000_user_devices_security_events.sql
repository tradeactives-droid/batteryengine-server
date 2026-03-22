-- Device tracking + optional security audit log (backend uses service role)

create extension if not exists "uuid-ossp";

-- One row per (user, device_id); updated on each authenticated API call with device headers
create table if not exists public.user_devices (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references auth.users (id) on delete cascade,
    device_id text not null,
    fingerprint text,
    ip_address text,
    user_agent text,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    constraint user_devices_user_device_unique unique (user_id, device_id)
);

create index if not exists user_devices_user_id_idx on public.user_devices (user_id);
create index if not exists user_devices_user_last_seen_idx on public.user_devices (user_id, last_seen_at desc);

alter table public.user_devices enable row level security;

create policy "Users can select own devices"
    on public.user_devices
    for select
    to authenticated
    using (auth.uid() = user_id);

create policy "Users can insert own device row"
    on public.user_devices
    for insert
    to authenticated
    with check (auth.uid() = user_id);

create policy "Users can update own device row"
    on public.user_devices
    for update
    to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

create policy "Users can delete own device row"
    on public.user_devices
    for delete
    to authenticated
    using (auth.uid() = user_id);

-- Optional: multi-device / sharing signals (written by backend only; no end-user RLS needed)
create table if not exists public.security_events (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid references auth.users (id) on delete set null,
    event_type text not null,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists security_events_user_id_idx on public.security_events (user_id);
create index if not exists security_events_created_at_idx on public.security_events (created_at desc);

alter table public.security_events enable row level security;

-- No policies for authenticated: only service role inserts/reads (dashboard/admin)
