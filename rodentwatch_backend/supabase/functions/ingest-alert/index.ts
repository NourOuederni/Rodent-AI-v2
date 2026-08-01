// supabase/functions/ingest-alert/index.ts
// Deploy:  supabase functions deploy ingest-alert --no-verify-jwt
//
// Called by a node (dev, over home WiFi) or by the LoRa gateway (production).
// Authenticates with the node's api_key — NOT a user JWT.
//
// POST body:
// {
//   "node_id": "node-01",
//   "api_key": "....uuid....",
//   "node_alert_id": 42,
//   "node_uptime_s": 123456,
//   "peak_score": 0.87,
//   "rat_count": 1,
//   "positives": 6,
//   "shots": 10,
//   "files": ["R42_0.jpg", "R42_1.jpg"],
//   "heartbeat_only": false        // true = just update last_seen
// }

import { createClient } from "jsr:@supabase/supabase-js@2";

Deno.serve(async (req) => {
  if (req.method !== "POST")
    return new Response("method not allowed", { status: 405 });

  let body: Record<string, unknown>;
  try { body = await req.json(); }
  catch { return new Response("bad json", { status: 400 }); }

  const nodeId = String(body.node_id ?? "");
  const apiKey = String(body.api_key ?? "");
  if (!nodeId || !apiKey)
    return new Response("node_id and api_key required", { status: 400 });

  // Service role client — bypasses RLS; this function IS the gate.
  const db = createClient(
    Deno.env.get("SUPABASE_URL")!,
    Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!,
  );

  // Authenticate the hardware.
  const { data: node, error: nodeErr } = await db
    .from("nodes").select("id, api_key").eq("id", nodeId).single();
  if (nodeErr || !node || node.api_key !== apiKey)
    return new Response("unauthorized", { status: 401 });

  // Heartbeat always.
  await db.from("nodes").update({
    last_seen: new Date().toISOString(),
    ...(body.firmware_version ? { firmware_version: String(body.firmware_version) } : {}),
    ...(body.model_version ? { model_version: String(body.model_version) } : {}),
  }).eq("id", nodeId);

  if (body.heartbeat_only === true)
    return Response.json({ ok: true, heartbeat: true });

  // Insert the alert (idempotent on node_id + node_alert_id).
  const { data: alert, error: alertErr } = await db.from("alerts").upsert({
    node_id: nodeId,
    node_alert_id: Number(body.node_alert_id ?? 0),
    node_uptime_s: Number(body.node_uptime_s ?? 0),
    peak_score: Number(body.peak_score ?? 0),
    rat_count: Number(body.rat_count ?? 0),
    positives: Number(body.positives ?? 0),
    shots: Number(body.shots ?? 0),
  }, { onConflict: "node_id,node_alert_id" }).select().single();

  if (alertErr) return new Response(alertErr.message, { status: 500 });

  // Image metadata.
  const files = Array.isArray(body.files) ? body.files : [];
  if (files.length) {
    await db.from("images").upsert(
      files.map((f) => ({ alert_id: alert.id, filename: String(f) })),
      { onConflict: "alert_id,filename", ignoreDuplicates: true },
    );
  }

  return Response.json({ ok: true, alert_id: alert.id });
});
