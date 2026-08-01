// App.js — root, wired to the REAL backend (Supabase via src/store/db.js).
// Changes vs the mock version:
//   - login/logout/session restore go through Supabase auth
//   - fleet + alerts load from Postgres; alerts update in REALTIME
//   - "mark checked" tries the backend first; if offline (e.g. on a node's
//     AP), it applies locally and queues for sync — the designed behavior
//   - connecting to a node logs a session row (when internet available)

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { View, Text, TouchableOpacity, ActivityIndicator, Vibration, StatusBar } from 'react-native';

import { C } from './src/theme/theme';
import { st } from './src/theme/styles';
import { DB } from './src/store/db';
import { nodeStatus, nodeGet } from './src/api/nodeApi';

import LoginScreen from './src/screens/Login';
import HomeScreen from './src/screens/Home';
import FleetScreen from './src/screens/Fleet';
import NodeProfileModal from './src/screens/NodeProfile';
import AlertsScreen from './src/screens/Alerts';
import GalleryScreen from './src/screens/Gallery';
import ProfileScreen from './src/screens/Profile';
import AdminScreen from './src/screens/Admin';

export default function App() {
  const [ready, setReady] = useState(false);
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState('home');
  const [openNode, setOpenNode] = useState(null);
  const [session, setSession] = useState(null);

  const [nodes, setNodes] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [queue, setQueue] = useState([]);
  const [banner, setBanner] = useState(null);
  const lastCount = useRef(null);

  const refresh = useCallback(async () => {
    const [n, a, q] = await Promise.all([DB.listNodes(), DB.listAlerts(), DB.getQueue()]);
    setNodes(n); setAlerts(a); setQueue(q);
  }, []);

  useEffect(() => {
    (async () => {
      const profile = await DB.restoreSession();
      if (profile) { setMe(profile); await refresh(); }
      setReady(true);
    })();
  }, [refresh]);

  // Realtime: alert changes from ANY source (node, gateway, other users).
  useEffect(() => {
    if (!me) return;
    const unsub = DB.subscribeAlerts(async (payload) => {
      if (payload.eventType === 'INSERT') {
        Vibration.vibrate([0, 400, 200, 400]);
        setBanner('New rat alert!');
        setTimeout(() => setBanner(null), 8000);
      }
      await refresh();
    });
    return unsub;
  }, [me, refresh]);

  const nodeApi = useCallback(
    (path, timeout) => nodeGet(session?.ip, path, timeout),
    [session]);

  // Poll the connected node too (its local counter, for on-site detections).
  useEffect(() => {
    if (!session) return;
    const id = setInterval(async () => {
      try {
        const s = await nodeStatus(session.ip);
        setSession(prev => prev ? { ...prev, status: s } : prev);
        if (lastCount.current !== null && s.alert_counter > lastCount.current) {
          Vibration.vibrate([0, 400, 200, 400]);
          setBanner(`New detection on ${s.device}`);
          setTimeout(() => setBanner(null), 8000);
        }
        lastCount.current = s.alert_counter;
      } catch (e) {}
    }, 10000);
    return () => clearInterval(id);
  }, [session]);

  const login = async (username, password) => {
    const profile = await DB.login(username, password);
    if (!profile) return false;
    setMe(profile);
    await refresh();
    return true;
  };

  const logout = async () => {
    await DB.logout();
    setMe(null); setSession(null); setTab('home');
  };

  // Online-first, queue-fallback — the designed offline behavior.
  const checkAlert = async (alertId) => {
    setAlerts(prev => prev.map(a => a.id === alertId
      ? { ...a, status: 'checked', checkedBy: me.username } : a));
    const err = await DB.checkAlert(alertId, me.id);
    if (err) {
      const q = await DB.enqueueCheck(alertId, me.id);
      setQueue(q);
    }
  };

  const flushQueue = async () => {
    const remaining = await DB.flushQueue();
    setQueue(remaining);
    await refresh();
  };

  const connectTo = async (ip) => {
    try {
      const s = await nodeStatus(ip);
      lastCount.current = s.alert_counter;
      setSession({ ip, status: s });
      DB.logSession(me.id, s.device).catch(() => {});   // best-effort
      return true;
    } catch (e) { return false; }
  };

  if (!ready) return (
    <View style={[st.canvas, st.center]}>
      <ActivityIndicator color={C.cheese} size="large" />
    </View>
  );

  if (!me) return <LoginScreen onLogin={login} />;

  const uncheckedCount = alerts.filter(a => a.status === 'unchecked').length;

  return (
    <View style={st.canvas}>
      <StatusBar barStyle="light-content" />

      {banner && (
        <TouchableOpacity style={st.banner} onPress={() => { setBanner(null); setTab('alerts'); }}>
          <Text style={st.bannerText}>🚨 {banner}</Text>
        </TouchableOpacity>
      )}

      <View style={{ flex: 1 }}>
        {tab === 'home' && (
          <HomeScreen me={me} unchecked={uncheckedCount} nodes={nodes} alerts={alerts}
            session={session} goTab={setTab} openNode={setOpenNode} />
        )}
        {tab === 'fleet' && (
          <FleetScreen nodes={nodes} openNode={setOpenNode} session={session} />
        )}
        {tab === 'alerts' && (
          <AlertsScreen alerts={alerts} onCheck={checkAlert} me={me} />
        )}
        {tab === 'gallery' && (
          <GalleryScreen session={session} nodeApi={nodeApi} goTab={setTab} />
        )}
        {tab === 'profile' && (
          <ProfileScreen me={me} queue={queue} onFlush={flushQueue}
            onLogout={logout} goAdmin={() => setTab('admin')} />
        )}
        {tab === 'admin' && me.role === 'admin' && (
          <AdminScreen nodes={nodes} refresh={refresh} goBack={() => setTab('profile')} />
        )}
      </View>

      {openNode && (
        <NodeProfileModal node={openNode} close={() => setOpenNode(null)}
          onConnect={async (ip) => {
            const ok = await connectTo(ip);
            if (ok) { setOpenNode(null); setTab('gallery'); }
            return ok;
          }} session={session} />
      )}

      <View style={st.tabbar}>
        {[
          ['home', 'Home'], ['fleet', 'Fleet'], ['alerts', 'Alerts'],
          ['gallery', 'Gallery'], ['profile', 'Profile'],
        ].map(([id, label]) => (
          <TouchableOpacity key={id} style={st.tabBtn} onPress={() => setTab(id)}>
            <View style={[st.tabPill, tab === id && { backgroundColor: C.cheese }]}>
              <Text style={[st.tabText, tab === id && { color: C.navyDeep, fontWeight: '700' }]}>
                {label}
              </Text>
              {id === 'alerts' && uncheckedCount > 0 && (
                <View style={st.tabBadge}><Text style={st.tabBadgeText}>{uncheckedCount}</Text></View>
              )}
            </View>
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}
