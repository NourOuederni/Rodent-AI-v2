-- ============================================================
-- RodentWatch — seed (run in SQL Editor, step 3)
-- ============================================================

-- Demo fleet so the app has something to show.
insert into public.nodes (id, name, location_label, ap_ssid, ap_password, firmware_version, model_version)
values
  ('node-01', 'Node 01', 'Test bench',     'RodentNode-01', 'rodent-01-pass', '1.2.0', 'FOMO v3'),
  ('node-02', 'Node 02', 'Storeroom A',    'RodentNode-02', 'rodent-02-pass', '1.2.0', 'FOMO v3'),
  ('node-03', 'Node 03', 'Storeroom B',    'RodentNode-03', 'rodent-03-pass', '1.1.0', 'FOMO v2');

-- ────────────────────────────────────────────────────────────
-- FIRST ADMIN — do this once, in the Dashboard (not SQL):
--   Authentication → Users → Add user:
--     email:    admin@rodentwatch.app
--     password: (choose one)
--     ✔ Auto-confirm user
-- Then run this to promote it:
-- ────────────────────────────────────────────────────────────
-- update public.profiles set role = 'admin', username = 'admin'
-- where id = (select id from auth.users where email = 'admin@rodentwatch.app');

-- Retrieve a node's API key (paste into its firmware):
-- select id, api_key from public.nodes;
