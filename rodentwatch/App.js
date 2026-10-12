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

import { Ionicons } from '@expo/vector-icons';
import TabBar from './src/components/TabBar';
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
  const [refreshing, setRefreshing] = useState(false);
  const [notice, setNotice] = useState(null);      // neutral info toast

  // Gallery state lives HERE so leaving the tab doesn't throw the list away
  const [galleryImages, setGalleryImages] = useState([]);
  const [galleryLoaded, setGalleryLoaded] = useState(false);
  const [galleryFilter, setGalleryFilter] = useState(null);
  const lastCount = useRef(null);
  const failCount = useRef(0);

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

  // Poll the connected node: live status, loss detection, auto-refresh on new detections.
  useEffect(() => {
    if (!session) return;
    failCount.current = 0;
    const id = setInterval(async () => {
      try {
        const s = await nodeStatus(session.ip);
        failCount.current = 0;
        setSession(prev => prev ? { ...prev, status: s } : prev);
        if (lastCount.current !== null && s.alert_counter > lastCount.current) {
          Vibration.vibrate([0, 400, 200, 400]);
          setBanner(`New detection on ${s.device}`);
          setTimeout(() => setBanner(null), 8000);
          // new images just landed on the SD -> refresh the gallery list now
          try {
            const list = (await nodeGet(session.ip, '/api/images'))
              .sort((a, b) => b.name.localeCompare(a.name, undefined, { numeric: true }));
            setGalleryImages(list); setGalleryLoaded(true);
          } catch (e) {}
          // the node also POSTed to the cloud -> pull the new alert (give it a moment)
          setTimeout(() => refresh(), 4000);
        }
        lastCount.current = s.alert_counter;
      } catch (e) {
        failCount.current += 1;
        if (failCount.current >= 2) {          // two misses = link is gone
          const name = session.status?.device || 'the node';
          setSession(null);
          setGalleryImages([]); setGalleryLoaded(false); setGalleryFilter(null);
          Vibration.vibrate(300);
          setNotice(`Disconnected from ${name} — connection lost.`);
          setTimeout(() => setNotice(null), 6000);
        }
      }
    }, 10000);
    return () => clearInterval(id);
  }, [session, refresh]);

  // Fallback sync: realtime can miss events on flaky links — refresh periodically.
  useEffect(() => {
    if (!me) return;
    const id = setInterval(() => { refresh(); }, 30000);
    return () => clearInterval(id);
  }, [me, refresh]);

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
      setGalleryImages([]); setGalleryLoaded(false); setGalleryFilter(null);
      DB.logSession(me.id, s.device).catch(() => {});   // best-effort
      return true;
    } catch (e) { return false; }
  };

  const checkAllAlerts = async () => {
    setAlerts(prev => prev.map(a => a.status === 'unchecked'
      ? { ...a, status: 'checked', checkedBy: me.username } : a));
    const err = await DB.checkAllAlerts(me.id);
    if (err) setNotice('Could not sync all checks — they will retry when online.');
    await refresh();
  };

  // Delete images from the node's SD, then auto-check the affected alerts.
  const deleteImages = async (names) => {
    if (!session || !names.length) return false;
    try {
      // chunk so the ESP32's query string never gets too long
      for (let i = 0; i < names.length; i += 15) {
        const chunk = names.slice(i, i + 15);
        const r = await nodeApi('/api/delete?names=' + chunk.join(','), 15000);
        if (!r?.ok) return false;
      }
    } catch (e) { return false; }

    // drop them from the gallery list immediately
    setGalleryImages(prev => prev.filter(i => !names.includes(i.name)));

    // R16_0.jpg -> alert 16
    const alertNums = [...new Set(
      names.map(n => parseInt(n.match(/^R(\d+)_/)?.[1], 10)).filter(Number.isFinite))];
    const nodeId = session.status?.device;
    if (nodeId && alertNums.length) {
      const err = await DB.markImagesDeleted(nodeId, alertNums, me.id);
      if (!err) {
        setAlerts(prev => prev.map(a =>
          (a.nodeId === nodeId && alertNums.includes(a.nodeAlertId))
            ? { ...a, status: 'checked', checkedBy: me.username, imagesDeleted: true }
            : a));
      }
    }
    setNotice(`Deleted ${names.length} image${names.length > 1 ? 's' : ''} from the node.`);
    setTimeout(() => setNotice(null), 4000);
    await refresh();
    return true;
  };

  const pullRefresh = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
  };

  const disconnectNode = () => {
    const name = session?.status?.device || 'the node';
    setSession(null);
    setGalleryImages([]); setGalleryLoaded(false); setGalleryFilter(null);
    setNotice(`Disconnected from ${name}.`);
    setTimeout(() => setNotice(null), 4000);
  };

  // Alert -> its images on the node (same id as the R<id>_*.jpg files)
  const openAlertImages = (alert) => {
    if (!session) {
      setNotice("You're not connected to a node. Connect to " +
                (alert.nodeName || alert.nodeId) + " to view its images.");
      setTimeout(() => setNotice(null), 5000);
      return;
    }
    if (session.status?.device && alert.nodeId &&
        session.status.device !== alert.nodeId) {
      setNotice(`Connected to ${session.status.device}, but this alert is from ${alert.nodeName}.`);
      setTimeout(() => setNotice(null), 5000);
      return;
    }
    setGalleryFilter(`R${alert.nodeAlertId}_`);
    setTab('gallery');
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
      <View pointerEvents="none" style={st.cornerBlob} />

      {banner && (
        <TouchableOpacity style={[st.banner, { flexDirection: 'row', alignItems: 'center' }]}
          onPress={() => { setBanner(null); setTab('alerts'); }}>
          <Ionicons name="warning" size={18} color={C.white} style={{ marginRight: 8 }} />
          <Text style={st.bannerText}>{banner}</Text>
        </TouchableOpacity>
      )}

      {notice && (
        <TouchableOpacity style={st.notice} onPress={() => setNotice(null)}>
          <Ionicons name="information-circle" size={18} color={C.navyDeep} style={{ marginRight: 8 }} />
          <Text style={st.noticeText}>{notice}</Text>
        </TouchableOpacity>
      )}

      <View style={{ flex: 1 }}>
        {tab === 'home' && (
          <HomeScreen me={me} unchecked={uncheckedCount} nodes={nodes} alerts={alerts}
            session={session} goTab={setTab} openNode={setOpenNode}
            onDisconnect={disconnectNode} nodeApi={nodeApi}
            refreshing={refreshing} onRefresh={pullRefresh} />
        )}
        {tab === 'fleet' && (
          <FleetScreen nodes={nodes} openNode={setOpenNode} session={session}
            refreshing={refreshing} onRefresh={pullRefresh} />
        )}
        {tab === 'alerts' && (
          <AlertsScreen alerts={alerts} onCheck={checkAlert} onCheckAll={checkAllAlerts}
            onOpenImages={openAlertImages} me={me}
            refreshing={refreshing} onRefresh={pullRefresh} />
        )}
        {tab === 'gallery' && (
          <GalleryScreen session={session} nodeApi={nodeApi} goTab={setTab}
            images={galleryImages} setImages={setGalleryImages}
            loaded={galleryLoaded} setLoaded={setGalleryLoaded}
            filter={galleryFilter} clearFilter={() => setGalleryFilter(null)}
            onDelete={deleteImages} />
        )}
        {tab === 'profile' && (
          <ProfileScreen me={me} queue={queue} onFlush={flushQueue}
            onLogout={logout} goAdmin={() => setTab('admin')}
            refreshing={refreshing} onRefresh={pullRefresh} />
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

      <TabBar tab={tab} setTab={setTab} alertBadge={uncheckedCount} />
    </View>
  );
}
