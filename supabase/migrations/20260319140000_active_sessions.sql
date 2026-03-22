-- Single active session per user (server-validated via service role)
-- Run in Supabase SQL editor or via supabase db push

create extension if not exists "uuid-ossp";

create table if not exists public.active_sessions (
    id uuid primary key default uuid_generate_v4(),
    user_id uuid not null references auth.users (id) on delete cascade,
    session_token text not null,
    created_at timestamptz not null default now(),
    constraint active_sessions_one_per_user unique (user_id)
);

create index if not exists active_sessions_user_id_idx on public.active_sessions (user_id);

alter table public.active_sessions enable row level security;

-- Logged-in users may only read/write their own row (for frontend delete + insert on login)
create policy "Users can select own active session"
    on public.active_sessions
    for select
    to authenticated
    using (auth.uid() = user_id);

create policy "Users can insert own active session"
    on public.active_sessions
    for insert
    to authenticated
    with check (auth.uid() = user_id);

create policy "Users can delete own active session"
    on public.active_sessions
    for delete
    to authenticated
    using (auth.uid() = user_id);

create policy "Users can update own active session"
    on public.active_sessions
    for update
    to authenticated
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

-- Service role (backend) bypasses RLS and is used for API request validation
