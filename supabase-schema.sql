create table if not exists public.machine_observations (
  id bigint generated always as identity primary key,
  machine_id integer not null,
  location_slug text not null default 'leonardtown',
  machine_type text not null default 'dryers',
  status text not null check (status in ('available', 'occupied', 'out_of_order')),
  minutes_remaining integer check (minutes_remaining is null or minutes_remaining >= 0),
  observed_at timestamptz not null,
  error text,
  url text,
  created_at timestamptz not null default now()
);

alter table public.machine_observations
  add column if not exists location_slug text not null default 'leonardtown';

alter table public.machine_observations
  add column if not exists machine_type text not null default 'dryers';

create index if not exists machine_observations_machine_time_idx
  on public.machine_observations (machine_id, observed_at desc);

create index if not exists machine_observations_status_time_idx
  on public.machine_observations (status, observed_at desc);

create index if not exists machine_observations_scope_time_idx
  on public.machine_observations (location_slug, machine_type, machine_id, observed_at desc);

alter table public.machine_observations enable row level security;

grant usage on schema public to service_role;
grant select, insert on table public.machine_observations to service_role;
grant usage, select on sequence public.machine_observations_id_seq to service_role;
