import React from 'react';
import { View, Text, TouchableOpacity, Image, ScrollView, RefreshControl } from 'react-native';
import { C } from '../theme/theme';
import { st } from '../theme/styles';
import { Row, SectionTitle } from '../components/ui';

export default function ProfileScreen({ me, queue, onFlush, onLogout, goAdmin, refreshing, onRefresh }) {
  return (
    <ScrollView contentContainerStyle={{ paddingBottom: 20 }}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.cheese} />}>
      <View style={st.headerBlob}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Image source={require('../../assets/logo.png')} style={st.avatar} />
          <View style={{ marginLeft: 12 }}>
            <Text style={st.hello}>{me.username}</Text>
            <Text style={st.linkState}>{me.role === 'admin' ? 'Administrator' : 'User'}</Text>
          </View>
        </View>
      </View>

      <SectionTitle>Sync</SectionTitle>
      <View style={st.whiteCard}>
        <Row k="Pending checks to sync" v={queue.length}
          color={queue.length > 0 ? C.cheeseDark : C.green} />
        {queue.length > 0 && (
          <TouchableOpacity style={st.btnCheck} onPress={onFlush}>
            <Text style={st.btnCheckText}>Sync now (needs internet)</Text>
          </TouchableOpacity>
        )}
      </View>

      {me.role === 'admin' && (
        <>
          <SectionTitle>Administration</SectionTitle>
          <TouchableOpacity style={st.whiteCard} onPress={goAdmin}>
            <Text style={st.cardTitle}>Open admin panel</Text>
            <Text style={st.cardSub}>Users, nodes, maps, SD management</Text>
          </TouchableOpacity>
        </>
      )}

      <TouchableOpacity style={[st.btnDanger]} onPress={onLogout}>
        <Text style={st.btnDangerText}>Sign out</Text>
      </TouchableOpacity>

      <Image source={require('../../assets/cst.png')} style={[st.cstLogo, { alignSelf: 'center' }]} />
    </ScrollView>
  );
}
