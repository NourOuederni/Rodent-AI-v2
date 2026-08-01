-- ============================================================
-- RodentWatch — migration 4: track alerts whose images were deleted
-- Run this once in the Supabase SQL Editor.
-- ============================================================

alter table public.alerts
  add column if not exists images_deleted boolean not null default false;

-- Note: the existing guard trigger (2_rls.sql) already allows non-admins to
-- change status / checked_by / checked_at / images_deleted — it only blocks
-- edits to node_id, node_alert_id, raised_at, peak_score and rat_count.
