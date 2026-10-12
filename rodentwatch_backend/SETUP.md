# RodentWatch backend — setup guide

## 1. Create the Supabase project
1. supabase.com → New project (free tier). Pick a region close to Tunisia (eu-central).
2. Wait for provisioning, then note from Settings → API:
   - Project URL   (https://xxxx.supabase.co)
   - anon public key

## 2. Database (SQL Editor, run in order)
1. Run `1_schema.sql`   — tables, triggers, indexes, realtime
2. Run `2_rls.sql`      — role enforcement at the database
3. Run `3_seed.sql`     — demo fleet

## 3. First admin account
1. Dashboard → Authentication → Users → Add user
   - email: admin@rodentwatch.app  (usernames map to <name>@rodentwatch.app)
   - password: your choice, Auto-confirm ON
2. SQL Editor:
   update public.profiles set role='admin', username='admin'
   where id = (select id from auth.users where email='admin@rodentwatch.app');

## 4. Edge functions (needs the Supabase CLI once)
```
npm i -g supabase
supabase login
supabase link --project-ref YOUR-PROJECT-REF
supabase functions deploy ingest-alert --no-verify-jwt
supabase functions deploy create-user
```
(--no-verify-jwt on ingest-alert: hardware authenticates with its api_key,
not a user token. create-user keeps JWT verification ON.)

## 5. App wiring
1. `npx expo install @supabase/supabase-js react-native-url-polyfill`
2. Copy in from app/:
   - src/api/supabase.js      (fill URL + anon key at the top)
   - src/store/db.js          (replaces the mock)
   - src/screens/Admin.js     (replaces the mock version)
   - App.js                   (replaces the root)
3. `npx expo start` — log in with  admin / your-password.
   The demo fleet from the seed appears; alerts arrive in realtime.

## 6. Firmware
1. Get node-01's key:  SQL →  select id, api_key from nodes;
2. Add `cloud_post.h` to the sketch folder, fill URL + node id + key.
3. Wire the 3 calls per the header comment (include, runBurst, loop).
4. Flash. Watch serial for `[cloud] POST -> 200`.

## 7. End-to-end test
- Trigger a burst (`/api/burst` or wait for the timer) with a rat scene.
- Expected: serial shows POST 200 → alert row appears in the table →
  every logged-in phone vibrates + shows the banner within ~2 s →
  mark it checked on one phone → the other phone shows "✓ by <name>".

## Notes
- The LoRa gateway later calls the SAME ingest-alert endpoint with the
  node's api_key — zero backend changes when the radio arrives.
- The app's offline check-queue keeps working: if checkAlert fails
  (no internet on a node's AP), it queues and Profile → Sync now pushes it.
- Change your WiFi password; it appeared in shared files during development.
