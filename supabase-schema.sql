create table if not exists public.machine_observations (
  id bigint generated always as identity primary key,
  machine_id integer not null,
  status text not null check (status in ('available', 'occupied', 'out_of_order')),
  minutes_remaining integer check (minutes_remaining is null or minutes_remaining >= 0),
  observed_at timestamptz not null,
  error text,
  url text,
  created_at timestamptz not null default now()
);

create index if not exists machine_observations_machine_time_idx
  on public.machine_observations (machine_id, observed_at desc);

create index if not exists machine_observations_status_time_idx
  on public.machine_observations (status, observed_at desc);

alter table public.machine_observations enable row level security;
