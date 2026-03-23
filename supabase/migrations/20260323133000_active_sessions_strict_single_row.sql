-- Enforce strict single active session row per user.
-- 1) Add updated_at
-- 2) Deduplicate existing rows (keep newest per user_id by updated_at)
-- 3) Ensure unique(user_id)
-- 4) Optional index on session_token

alter table if exists public.active_sessions
    add column if not exists updated_at timestamptz;

update public.active_sessions
set updated_at = coalesce(updated_at, created_at, now())
where updated_at is null;

alter table if exists public.active_sessions
    alter column updated_at set default now();

alter table if exists public.active_sessions
    alter column updated_at set not null;

with ranked as (
    select
        id,
        row_number() over (
            partition by user_id
            order by updated_at desc, created_at desc, id desc
        ) as rn
    from public.active_sessions
)
delete from public.active_sessions s
using ranked r
where s.id = r.id
  and r.rn > 1;

do $$
begin
    if not exists (
        select 1
        from pg_constraint c
        join pg_attribute a
          on a.attrelid = c.conrelid
         and a.attnum = any(c.conkey)
        where c.conrelid = 'public.active_sessions'::regclass
          and c.contype = 'u'
          and a.attname = 'user_id'
    ) then
        alter table public.active_sessions
            add constraint active_sessions_user_id_unique unique (user_id);
    end if;
end $$;

create index if not exists active_sessions_session_token_idx
    on public.active_sessions (session_token);

