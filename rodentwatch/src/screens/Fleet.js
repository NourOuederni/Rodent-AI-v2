import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, FlatList, RefreshControl } from 'react-native';
import { C } from '../theme/theme';
import { st } from '../theme/styles';
import { Dot } from '../components/ui';

export default function FleetScreen({ nodes, openNode, session, refreshing, onRefresh }) {
  const [q, setQ] = useState('');
  const filtered = nodes.filter(n =>
    (n.name + n.location + n.id).toLowerCase().includes(q.toLowerCase()));

  return (
    <View style={{ flex: 1 }}>
      <View style={st.headerBlobSmall}>
        <Text style={st.screenTitle}>Fleet</Text>
        <TextInput style={st.searchOnNavy} value={q} onChangeText={setQ}
          placeholder="Search nodes…" placeholderTextColor={C.mutedOnNavy} />
      </View>
      <FlatList
        data={filtered} keyExtractor={n => n.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.cheese} />}
        contentContainerStyle={{ paddingBottom: 20, paddingTop: 6 }}
        ListEmptyComponent={<Text style={st.emptyOnNavy}>No nodes match.</Text>}
        renderItem={({ item }) => (
          <TouchableOpacity style={st.whiteCard} onPress={() => openNode(item)}>
            <View style={{ flexDirection: 'row', alignItems: 'center' }}>
              <Dot ok={item.online} />
              <Text style={[st.cardTitle, { marginLeft: 8, flex: 1 }]}>
                {item.name}{item.self ? '  ·  yours' : ''}
              </Text>
              {item.alerts > 0 && (
                <View style={st.alertCountPill}>
                  <Text style={st.alertCountText}>{item.alerts}</Text>
                </View>
              )}
            </View>
            <Text style={st.cardSub}>{item.location} · last seen {item.lastSeen}</Text>
          </TouchableOpacity>
        )}
      />
      <Text style={st.footNote}>
        Map view unlocks when an admin uploads a site map.
      </Text>
    </View>
  );
}
