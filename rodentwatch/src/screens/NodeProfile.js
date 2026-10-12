import React, { useState, useEffect } from 'react';
import { View, Text, TextInput, TouchableOpacity, Modal, ActivityIndicator } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { C } from '../theme/theme';
import { st } from '../theme/styles';
import { Dot, Row } from '../components/ui';

export default function NodeProfileModal({ node, close, onConnect, session }) {
  const [ip, setIp] = useState('192.168.4.1');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  useEffect(() => { AsyncStorage.getItem('last_ip').then(v => v && setIp(v)); }, []);

  return (
    <Modal visible transparent animationType="slide" onRequestClose={close}>
      <TouchableOpacity style={st.modalBg} activeOpacity={1} onPress={close}>
        <TouchableOpacity activeOpacity={1} onPress={() => {}} style={st.modalSheet}>
          <View style={st.sheetHandle} />
          <View style={{ flexDirection: 'row', alignItems: 'center', marginBottom: 10 }}>
            <Dot ok={node.online} />
            <Text style={[st.cardTitle, { fontSize: 20, marginLeft: 8 }]}>{node.name}</Text>
          </View>
          <Row k="Location" v={node.location} />
          <Row k="Last seen" v={node.lastSeen} />
          <Row k="Alerts total" v={node.alerts} color={node.alerts > 0 ? C.red : C.green} />
          <Row k="Firmware" v={node.fw} />
          <Row k="Model" v={node.model} />

          <Text style={[st.inputLabel, { marginTop: 16 }]}>
            Node IP (192.168.4.1 on its own AP)
          </Text>
          <TextInput style={st.input} value={ip} onChangeText={setIp}
            autoCapitalize="none" keyboardType="numbers-and-punctuation" />
          {err ? <Text style={st.errText}>{err}</Text> : null}

          <TouchableOpacity style={st.btnPrimary} disabled={busy}
            onPress={async () => {
              setBusy(true); setErr('');
              await AsyncStorage.setItem('last_ip', ip.trim());
              const ok = await onConnect(ip.trim());
              if (!ok) setErr('Unreachable. Join the node\'s WiFi first, then retry.');
              setBusy(false);
            }}>
            {busy ? <ActivityIndicator color={C.navyDeep} />
                  : <Text style={st.btnPrimaryText}>Connect to this node</Text>}
          </TouchableOpacity>

        </TouchableOpacity>
      </TouchableOpacity>
    </Modal>
  );
}
