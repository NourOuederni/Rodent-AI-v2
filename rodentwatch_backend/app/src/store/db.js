// src/store/db.js — REAL backend calls (replaces the AsyncStorage mock).
// The sync queue stays device-local by design (offline-first).

import AsyncStorage from '@react-native-async-storage/async-storage';
import { supabase } from '../api/supabase';

const EMAIL = (username) => `${username.toLowerCase().trim()}@rodentwatch.app`;

function timeAgo(iso) {
  if (!iso) return 'never';
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)} min`;
  if (s < 86400) return `${Math.floor(s / 3600)} h`;
  return `${Math.floor(s / 86400)} d`;
}

export const DB = {
  /* ── auth ── */
  async login(username, password) {
    const { data, error } = await supabase.auth.signInWithPassword({
      email: EMAIL(username), password,
    });
    if (error || !data.user) return null;
    const { data: profile } = await supabase
      .from('profiles').select('id, username, role').eq('id', data.user.id).single();
    return profile;   // { id, username, role }
  },

  async restoreSession() {
    const { data } = await supabase.auth.getUser();
    if (!data.user) return null;
    const { data: profile } = await supabase
      .from('profiles').select('id, username, role').eq('id', data.user.id).single();
    return profile;
  },

  async logout() { await supabase.auth.signOut(); },

  /* ── fleet ── */
  async listNodes() {
    const { data, error } = await supabase
      .from('nodes')
      .select('id, name, location_label, ap_ssid, last_seen, firmware_version, model_version, alerts(count)')
      .order('id');
    if (error) return [];
    return data.map(n => ({
      id: n.id,
      name: n.name,
      location: n.location_label || '—',
      apSsid: n.ap_ssid,
      lastSeen: timeAgo(n.last_seen),
      online: n.last_seen && (Date.now() - new Date(n.last_seen).getTime()) < 15 * 60 * 1000,
      alerts: n.alerts?.[0]?.count ?? 0,
      fw: n.firmware_version || '—',
      model: n.model_version || '—',
    }));
  },

  async registerNode(name, location) {
    const id = 'node-' + String(Date.now()).slice(-6);
    const { error } = await supabase.from('nodes').insert({
      id, name, location_label: location,
      ap_ssid: `RodentNode-${id.slice(-2)}`,
    });
    return error ? error.message : null;
  },

  async deleteNode(id) {
    const { error } = await supabase.from('nodes').delete().eq('id', id);
    return error ? error.message : null;
  },

  /* ── alerts ── */
  async listAlerts() {
    const { data, error } = await supabase
      .from('alerts')
      .select('id, node_id, node_alert_id, raised_at, peak_score, rat_count, status, nodes(name), profiles:checked_by(username)')
      .order('raised_at', { ascending: false })
      .limit(200);
    if (error) return [];
    return data.map(a => ({
      id: a.id,
      shortId: `${a.node_id}#${a.node_alert_id}`,
      nodeId: a.node_id,
      nodeName: a.nodes?.name ?? a.node_id,
      time: new Date(a.raised_at).toLocaleString(),
      peak: a.peak_score,
      rats: a.rat_count,
      status: a.status,
      checkedBy: a.profiles?.username ?? null,
    }));
  },

  async checkAlert(alertId, userId) {
    const { error } = await supabase.from('alerts').update({
      status: 'checked', checked_by: userId, checked_at: new Date().toISOString(),
    }).eq('id', alertId);
    return error ? error.message : null;
  },

  // Live updates: any alert insert/update anywhere → callback fires.
  subscribeAlerts(onChange) {
    const ch = supabase.channel('alerts-live')
      .on('postgres_changes', { event: '*', schema: 'public', table: 'alerts' }, onChange)
      .subscribe();
    return () => supabase.removeChannel(ch);
  },

  /* ── admin: users ── */
  async addUser(username, password, role = 'user') {
    const { data: { session } } = await supabase.auth.getSession();
    const { data, error } = await supabase.functions.invoke('create-user', {
      body: { username, password, role },
      headers: { Authorization: `Bearer ${session?.access_token}` },
    });
    if (error) return typeof error === 'string' ? error : (error.message || 'failed');
    return null;
  },

  /* ── sessions log ── */
  async logSession(userId, nodeId) {
    await supabase.from('sessions').insert({ user_id: userId, node_id: nodeId });
  },

  /* ── offline sync queue (device-local, by design) ── */
  async getQueue()  { return JSON.parse(await AsyncStorage.getItem('db_queue')) || []; },
  async setQueue(q) { await AsyncStorage.setItem('db_queue', JSON.stringify(q)); },

  async enqueueCheck(alertId, userId) {
    const q = await this.getQueue();
    q.push({ type: 'check', alertId, userId, at: Date.now() });
    await this.setQueue(q);
    return q;
  },

  // Try to push every queued action; keep the ones that still fail.
  async flushQueue() {
    const q = await this.getQueue();
    const remaining = [];
    for (const item of q) {
      if (item.type === 'check') {
        const err = await this.checkAlert(item.alertId, item.userId);
        if (err) remaining.push(item);
      }
    }
    await this.setQueue(remaining);
    return remaining;
  },
};
