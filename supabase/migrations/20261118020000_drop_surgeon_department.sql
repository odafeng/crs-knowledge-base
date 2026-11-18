-- H5 #127: the surgeon application no longer asks for a department. Only colorectal surgeons and their trainees apply,
-- so the field told the maintainer nothing and was one more personal detail to hold (ADR-0022, 2026-11-18).
alter table app.surgeon_applications drop column department;
