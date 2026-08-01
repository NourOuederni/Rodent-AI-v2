import React, { useState } from 'react';
import { View, Text, TouchableOpacity, Image, ScrollView, RefreshControl, Modal, ActivityIndicator, StyleSheet } from 'react-native';
import { Image as CachedImage } from 'expo-image';
import { Ionicons } from '@expo/vector-icons';
import { C } from '../theme/theme';
import { st } from '../theme/styles';
import { Dot, SectionTitle } from '../components/ui';

export default function HomeScreen({ me, unchecked, nodes, alerts, session, goTab, openNode, onDisconnect, refreshing, onRefresh, nodeApi }) {
  const [testOpen, setTestOpen] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [testErr, setTestErr] = useState('');

  const runTest = async () => {
    setTestOpen(true); setTestBusy(true); setTestResult(null); setTestErr('');
    try {
      const r = await nodeApi('/api/test', 30000);
      if (r?.ok) setTestResult({ ...r, ts: Date.now() });
      else setTestErr('The node did not return a result.');
    } catch (e) {
      setTestErr('Test failed — check the connection to the node.');
    }
    setTestBusy(false);
  };

  const online = nodes.filter(n => n.online).length;
  const recent = alerts.slice(0, 3);

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 20 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.cheese} />}>
      <View style={st.headerBlob}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Image source={require('../../assets/logo.png')} style={st.avatar} />
          <View style={{ marginLeft: 12, flex: 1 }}>
            <Text style={st.hello}>Hello, {me.username}</Text>
            <View style={{ flexDirection: 'row', alignItems: 'center', marginTop: 3 }}>
              <Dot ok={!!session} />
              <Text style={st.linkState}>
                {session ? `Connected to ${session.status?.device}` : 'Not connected to a node'}
              </Text>
            </View>
            {session && (
              <TouchableOpacity onPress={onDisconnect}
                style={{ marginTop: 8, alignSelf: 'flex-start', borderWidth: 1.5,
                         borderColor: C.red, borderRadius: 999,
                         paddingHorizontal: 12, paddingVertical: 5 }}>
                <Text style={{ color: C.red, fontWeight: '800', fontSize: 12 }}>Disconnect</Text>
              </TouchableOpacity>
            )}
          </View>
        </View>

        <View style={st.statRow}>
          <TouchableOpacity style={[st.statCard, unchecked > 0 && { backgroundColor: C.red }]}
            onPress={() => goTab('alerts')}>
            <Text style={[st.statNum, unchecked > 0 && { color: C.white }]}>{unchecked}</Text>
            <Text style={[st.statLabel, unchecked > 0 && { color: '#FBD9D5' }]}>unchecked alerts</Text>
          </TouchableOpacity>
          <TouchableOpacity style={st.statCard} onPress={() => goTab('fleet')}>
            <Text style={st.statNum}>{online}/{nodes.length}</Text>
            <Text style={st.statLabel}>nodes online</Text>
          </TouchableOpacity>
        </View>
      </View>

      <SectionTitle>Recent alerts</SectionTitle>
      {recent.map(a => (
        <TouchableOpacity key={a.id} style={st.whiteCard} onPress={() => goTab('alerts')}>
          <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
            <Text style={st.cardTitle}>{a.nodeName}</Text>
            <View style={[st.statusPill, a.status === 'checked' ? st.pillOk : st.pillBad]}>
              <Text style={[st.statusPillText, { color: a.status === 'checked' ? C.green : C.red }]}>
                {a.status === 'checked' ? `✓ ${a.checkedBy}` : 'unchecked'}
              </Text>
            </View>
          </View>
          <Text style={st.cardSub}>{a.time} · peak {a.peak} · {a.rats} rat{a.rats > 1 ? 's' : ''}</Text>
        </TouchableOpacity>
      ))}

      <SectionTitle>Quick actions</SectionTitle>
      <View style={{ flexDirection: 'row', paddingHorizontal: 16, gap: 10 }}>
        <TouchableOpacity style={st.actionCard} onPress={() => goTab('fleet')}>
          <Ionicons name="radio-outline" size={24} color={C.ink} />
          <Text style={st.actionText}>Find a node</Text>
        </TouchableOpacity>
        <TouchableOpacity style={st.actionCard}
          onPress={() => openNode(nodes.find(n => n.self) || nodes[0])}>
          <Ionicons name="link-outline" size={24} color={C.ink} />
          <Text style={st.actionText}>Connect</Text>
        </TouchableOpacity>
        <TouchableOpacity style={st.actionCard} onPress={() => goTab('gallery')}>
          <Ionicons name="images-outline" size={24} color={C.ink} />
          <Text style={st.actionText}>Gallery</Text>
        </TouchableOpacity>
        {me.role === 'admin' && session && (
          <TouchableOpacity style={[st.actionCard, hs.testCard]} onPress={runTest}>
            <Ionicons name="flask-outline" size={24} color={C.navyDeep} />
            <Text style={[st.actionText, { color: C.navyDeep }]}>Test shot</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* ── Test shot result modal (admin) ── */}
      <Modal visible={testOpen} transparent animationType="fade"
        onRequestClose={() => setTestOpen(false)}>
        <TouchableOpacity style={hs.testBg} activeOpacity={1} onPress={() => !testBusy && setTestOpen(false)}>
          <TouchableOpacity activeOpacity={1} onPress={() => {}} style={hs.testSheet}>
            <Text style={hs.testTitle}>Test shot</Text>

            {testBusy && (
              <View style={{ alignItems: 'center', paddingVertical: 30 }}>
                <ActivityIndicator color={C.cheese} size="large" />
                <Text style={[st.cardSub, { marginTop: 12 }]}>Capturing and running inference…</Text>
              </View>
            )}

            {testErr ? <Text style={st.errText}>{testErr}</Text> : null}

            {testResult && (
              <>
                <CachedImage
                  source={{ uri: `http://${session?.ip}/api/testimg?t=${testResult.ts}` }}
                  style={hs.testImg} contentFit="cover" cachePolicy="none" />
                <View style={[hs.verdict,
                  { backgroundColor: testResult.detected ? 'rgba(200,54,43,0.15)' : 'rgba(62,155,110,0.15)' }]}>
                  <Ionicons
                    name={testResult.detected ? 'alert-circle' : 'checkmark-circle'}
                    size={20} color={testResult.detected ? C.red : C.green} />
                  <Text style={[hs.verdictText, { color: testResult.detected ? C.red : C.green }]}>
                    {testResult.detected
                      ? `RAT DETECTED · ${testResult.blobs} blob${testResult.blobs > 1 ? 's' : ''}`
                      : 'No rat detected'}
                  </Text>
                </View>
                <Text style={[st.cardSub, { marginTop: 10, textAlign: 'center' }]}>
                  peak {testResult.peak} · threshold {testResult.threshold} · {testResult.infer_ms} ms
                </Text>
                <TouchableOpacity style={[st.btnCheck, { marginTop: 14 }]} onPress={runTest}>
                  <Text style={st.btnCheckText}>Run again</Text>
                </TouchableOpacity>
              </>
            )}
          </TouchableOpacity>
        </TouchableOpacity>
      </Modal>
    </ScrollView>
  );
}


const hs = StyleSheet.create({
  testCard: { backgroundColor: C.cheese, borderTopRightRadius: 30 },
  testBg: {
    flex: 1, backgroundColor: 'rgba(10,12,26,0.75)',
    alignItems: 'center', justifyContent: 'center', padding: 20,
  },
  testSheet: {
    backgroundColor: C.surface, borderRadius: 26, padding: 18, width: '100%',
  },
  testTitle: { color: C.textStrong, fontSize: 18, fontWeight: '800', marginBottom: 12 },
  testImg: { width: '100%', aspectRatio: 4 / 3, borderRadius: 14, backgroundColor: C.navyDeep },
  verdict: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 8, borderRadius: 999, paddingVertical: 10, marginTop: 12,
  },
  verdictText: { fontWeight: '800', fontSize: 14 },
});
