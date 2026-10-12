// src/screens/Admin.js — wired to the real backend.
import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, ScrollView } from 'react-native';
import { C } from '../theme/theme';
import { st } from '../theme/styles';
import { SectionTitle } from '../components/ui';
import { DB } from '../store/db';

export default function AdminScreen({ nodes, refresh, goBack }) {
  const [newUser, setNewUser] = useState('');
  const [newPass, setNewPass] = useState('');
  const [nodeName, setNodeName] = useState('');
  const [nodeLoc, setNodeLoc] = useState('');
  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  const addUser = async () => {
    if (!newUser.trim() || !newPass) { setMsg('Username and password required'); return; }
    setBusy(true);
    const err = await DB.addUser(newUser.trim(), newPass);
    setMsg(err ? `Error: ${err}` : `User "${newUser.trim()}" created`);
    if (!err) { setNewUser(''); setNewPass(''); }
    setBusy(false);
  };

  const addNode = async () => {
    if (!nodeName.trim()) { setMsg('Node name required'); return; }
    setBusy(true);
    const err = await DB.registerNode(nodeName.trim(), nodeLoc.trim());
    setMsg(err ? `Error: ${err}` : 'Node registered — fetch its API key from the dashboard');
    if (!err) { setNodeName(''); setNodeLoc(''); await refresh(); }
    setBusy(false);
  };

  const deleteNode = async (id) => {
    setBusy(true);
    const err = await DB.deleteNode(id);
    setMsg(err ? `Error: ${err}` : `${id} deleted`);
    await refresh();
    setBusy(false);
  };

  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 24 }}>
      <View style={st.headerBlobSmall}>
        <TouchableOpacity onPress={goBack}><Text style={{ color: C.cheese }}>← Back</Text></TouchableOpacity>
        <Text style={[st.screenTitle, { marginTop: 6 }]}>Admin panel</Text>
      </View>

      {msg ? <Text style={st.adminMsg}>{msg}</Text> : null}

      <SectionTitle>Add user</SectionTitle>
      <View style={st.whiteCard}>
        <TextInput style={st.input} value={newUser} onChangeText={setNewUser}
          placeholder="username" autoCapitalize="none" placeholderTextColor={C.mutedOnWhite} />
        <TextInput style={[st.input, { marginTop: 10 }]} value={newPass} onChangeText={setNewPass}
          placeholder="password" secureTextEntry placeholderTextColor={C.mutedOnWhite} />
        <TouchableOpacity style={st.btnCheck} onPress={addUser} disabled={busy}>
          <Text style={st.btnCheckText}>{busy ? '…' : 'Create user'}</Text>
        </TouchableOpacity>
      </View>

      <SectionTitle>Register node</SectionTitle>
      <View style={st.whiteCard}>
        <TextInput style={st.input} value={nodeName} onChangeText={setNodeName}
          placeholder="Node name" placeholderTextColor={C.mutedOnWhite} />
        <TextInput style={[st.input, { marginTop: 10 }]} value={nodeLoc} onChangeText={setNodeLoc}
          placeholder="Location label" placeholderTextColor={C.mutedOnWhite} />
        <TouchableOpacity style={st.btnCheck} onPress={addNode} disabled={busy}>
          <Text style={st.btnCheckText}>{busy ? '…' : 'Register'}</Text>
        </TouchableOpacity>
      </View>

      <SectionTitle>Nodes</SectionTitle>
      {nodes.map(n => (
        <View key={n.id} style={[st.whiteCard, { flexDirection: 'row', alignItems: 'center' }]}>
          <View style={{ flex: 1 }}>
            <Text style={st.cardTitle}>{n.name}</Text>
            <Text style={st.cardSub}>{n.id} · {n.location} · AP {n.apSsid || '—'}</Text>
          </View>
          <TouchableOpacity onPress={() => deleteNode(n.id)} disabled={busy}>
            <Text style={{ color: C.red, fontWeight: '700' }}>Delete</Text>
          </TouchableOpacity>
        </View>
      ))}

      <SectionTitle>Maps</SectionTitle>
      <View style={st.whiteCard}>
        <Text style={st.cardSub}>
          Map upload (Supabase Storage) is the next admin feature to wire in.
        </Text>
      </View>
    </ScrollView>
  );
}
