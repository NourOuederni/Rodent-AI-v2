// supabase/functions/create-user/index.ts
// Deploy:  supabase functions deploy create-user
//
// Called from the app's Admin panel with the ADMIN's JWT.
// Verifies the caller is an admin, then creates the auth user
// with the service role (only the service role may create users).
//
// POST body: { "username": "amine2", "password": "secret", "role": "user" }

import { createClient } from "jsr:@supabase/supabase-js@2";

Deno.serve(async (req) => {
  if (req.method !== "POST")
    return new Response("method not allowed", { status: 405 });

  const authHeader = req.headers.get("Authorization") ?? "";
  const jwt = authHeader.replace("Bearer ", "");
  if (!jwt) return new Response("missing token", { status: 401 });

  const url = Deno.env.get("SUPABASE_URL")!;
  const anon = Deno.env.get("SUPABASE_ANON_KEY")!;
  const service = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;

  // Identify the caller from their JWT.
  const asCaller = createClient(url, anon, {
    global: { headers: { Authorization: `Bearer ${jwt}` } },
  });
  const { data: { user } } = await asCaller.auth.getUser();
  if (!user) return new Response("invalid token", { status: 401 });

  // Verify admin role.
  const admin = createClient(url, service);
  const { data: profile } = await admin
    .from("profiles").select("role").eq("id", user.id).single();
  if (profile?.role !== "admin")
    return new Response("admins only", { status: 403 });

  const { username, password, role } = await req.json();
  if (!username || !password)
    return new Response("username and password required", { status: 400 });

  // Usernames map to synthetic emails: <username>@rodentwatch.app
  const { data, error } = await admin.auth.admin.createUser({
    email: `${String(username).toLowerCase().trim()}@rodentwatch.app`,
    password: String(password),
    email_confirm: true,
    user_metadata: { username: String(username).trim(), role: role === "admin" ? "admin" : "user" },
  });
  if (error) return new Response(error.message, { status: 400 });

  return Response.json({ ok: true, id: data.user.id });
});
