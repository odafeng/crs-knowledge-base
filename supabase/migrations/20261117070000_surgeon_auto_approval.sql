-- H10 #168: approve colorectal surgeons automatically when the society's doctor map lists the name at the hospital
-- and the applicant signed in from a mailbox at that hospital's domain (ADR-0022). The application remembers only
-- whether the mailbox matched, for the maintainer's queue; the address itself is never stored.

alter table app.surgeon_applications add column hospital_email boolean not null default false;

-- Automatic approvals are audited like the maintainer's, with no decider.
alter table app.surgeon_verification_events drop constraint surgeon_verification_events_action_check;
alter table app.surgeon_verification_events
  add constraint surgeon_verification_events_action_check
  check (action in ('approve', 'reject', 'revoke', 'auto_approve'));
