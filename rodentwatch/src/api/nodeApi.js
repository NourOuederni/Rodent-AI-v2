// src/api/nodeApi.js — the REAL connection to an ESP32 node's REST API.
// Everything the app knows about talking to hardware lives here.

export async function nodeStatus(ip, timeout = 6000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(`http://${ip}/api/status`, { signal: ctl.signal });
    return await r.json();
  } finally { clearTimeout(t); }
}

export async function nodeGet(ip, path, timeout = 8000) {
  const ctl = new AbortController();
  const t = setTimeout(() => ctl.abort(), timeout);
  try {
    const r = await fetch(`http://${ip}${path}`, { signal: ctl.signal });
    return await r.json();
  } finally { clearTimeout(t); }
}

export const imageUrl = (ip, name) => `http://${ip}/api/image?name=${name}`;
export const liveUrl  = (ip)       => `http://${ip}/api/live?t=${Date.now()}`;
