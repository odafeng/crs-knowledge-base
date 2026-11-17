-- H5 #127: colorectal surgeon membership (ADR-0022). A signed-in reader applies with their real name, hospital,
-- department and the last three digits of their certificate number; the maintainer checks them against the public
-- registers and approves or rejects. The application is deleted the moment it is decided: only the membership and
-- an audit trail without any of those details remain. No national ID and no documents are ever collected.

alter table app.accounts add column surgeon_since timestamptz;

create table app.surgeon_applications (
  account_id uuid primary key references app.accounts (id) on delete cascade,
  real_name text not null check (char_length(btrim(real_name)) between 1 and 40),
  hospital text not null check (char_length(btrim(hospital)) between 1 and 80),
  department text not null check (char_length(btrim(department)) between 1 and 40),
  certificate_digits text not null check (certificate_digits ~ '^[0-9]{3}$'),
  submitted_at timestamptz not null default now()
);

create table app.surgeon_verification_events (
  id bigint generated always as identity primary key,
  -- Kept after the account is gone: the trail of who granted what outlives both accounts.
  account_id uuid references app.accounts (id) on delete set null,
  action text not null check (action in ('approve', 'reject', 'revoke')),
  decided_by uuid references app.accounts (id) on delete set null,
  decided_at timestamptz not null default now()
);

-- A deleted account loses its membership and its pending application at once, not 90 days later at purge.
create function app.drop_surgeon_data_on_account_delete() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.deleted_at is not null and old.deleted_at is null then
    delete from app.surgeon_applications where account_id = new.id;
    new.surgeon_since := null;
  end if;
  return new;
end $$;

create trigger accounts_drop_surgeon_data
before update of deleted_at on app.accounts
for each row execute function app.drop_surgeon_data_on_account_delete();

alter table app.surgeon_applications enable row level security;
alter table app.surgeon_verification_events enable row level security;
revoke all on app.surgeon_applications, app.surgeon_verification_events from public, anon, authenticated, service_role;
grant select, insert, update, delete on app.surgeon_applications to guthub_api;
grant select, insert (account_id, action, decided_by) on app.surgeon_verification_events to guthub_api;
create policy guthub_api_access on app.surgeon_applications to guthub_api using (true) with check (true);
create policy guthub_api_access on app.surgeon_verification_events to guthub_api using (true) with check (true);
