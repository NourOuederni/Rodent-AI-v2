import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, Image, ActivityIndicator, StatusBar } from 'react-native';
import { C } from '../theme/theme';
import { st } from '../theme/styles';

export default function LoginScreen({ onLogin }) {
  const [u, setU] = useState(''); const [p, setP] = useState('');
  const [err, setErr] = useState(''); const [busy, setBusy] = useState(false);

  return (
    <View style={st.canvas}>
      <StatusBar barStyle="light-content" />
      <View style={st.loginBlobTop} />
      <View style={[st.center, { flex: 1, padding: 24 }]}>
        <Image source={require('../../assets/logo.png')} style={st.loginLogo} />
        <Text style={st.loginTitle}>RodentWatch</Text>
        <Text style={st.loginSub}>Field detection network</Text>

        <View style={st.loginCard}>
          <Text style={st.inputLabel}>Username</Text>
          <TextInput style={st.input} value={u} onChangeText={setU}
            autoCapitalize="none" placeholder="admin" placeholderTextColor={C.mutedOnWhite} />
          <Text style={[st.inputLabel, { marginTop: 14 }]}>Password</Text>
          <TextInput style={st.input} value={p} onChangeText={setP}
            secureTextEntry placeholder="••••••••" placeholderTextColor={C.mutedOnWhite} />
          {err ? <Text style={st.errText}>{err}</Text> : null}
          <TouchableOpacity style={st.btnPrimary} disabled={busy}
            onPress={async () => {
              setBusy(true); setErr('');
              const ok = await onLogin(u.trim(), p);
              if (!ok) setErr('Wrong username or password');
              setBusy(false);
            }}>
            {busy ? <ActivityIndicator color={C.navyDeep} />
                  : <Text style={st.btnPrimaryText}>Sign in</Text>}
          </TouchableOpacity>
          <Text style={st.hintOnWhite}>Demo: admin / admin123 · user / user123</Text>
        </View>

        <Image source={require('../../assets/cst.png')} style={st.cstLogo} />
      </View>
    </View>
  );
}
