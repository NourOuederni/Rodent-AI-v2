import React, { useState } from 'react';
import { View, Text, TextInput, TouchableOpacity, FlatList, Alert, StyleSheet, RefreshControl } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { C } from '../theme/theme';
import { st } from '../theme/styles';
import { Chip } from '../components/ui';

export default function AlertsScreen({ alerts, onCheck, onCheckAll, onOpenImages, me, refreshing, onRefresh }) {
  const [q, setQ] = useState('');
  const [filter, setFilter] = useState('all');

  const uncheckedCount = alerts.filter(a => a.status === 'unchecked').length;

  const filtered = alerts.filter(a => {
    if (filter === 'unchecked' && a.status !== 'unchecked') return false;
    if (filter === 'checked' && a.status !== 'checked') return false;
    const hay = `${a.nodeName} ${a.nodeId} #${a.nodeAlertId}`.toLowerCase();
    return hay.includes(q.toLowerCase().trim());
  });

  const confirmAll = () => {
    Alert.alert('Mark all as checked',
      `This marks ${uncheckedCount} alert${uncheckedCount > 1 ? 's' : ''} as checked for everyone.`,
      [{ text: 'Cancel', style: 'cancel' },
       { text: 'Mark all', onPress: onCheckAll }]);
  };

  return (
    <View style={{ flex: 1 }}>
      <View style={st.headerBlobSmall}>
        <Text style={st.screenTitle}>Alerts</Text>
        <TextInput style={st.searchOnNavy} value={q} onChangeText={setQ}
          placeholder="Search by node or alert ID…" placeholderTextColor={C.mutedOnNavy} />
        <View style={{ flexDirection: 'row', marginTop: 10, gap: 8 }}>
          <Chip label="All" active={filter === 'all'} onPress={() => setFilter('all')} />
          <Chip label="Unchecked" danger active={filter === 'unchecked'} onPress={() => setFilter('unchecked')} />
          <Chip label="Checked" active={filter === 'checked'} onPress={() => setFilter('checked')} />
        </View>

        {uncheckedCount > 0 && (
          <TouchableOpacity style={ls.markAll} onPress={confirmAll}>
            <Ionicons name="checkmark-done" size={17} color={C.navyDeep} />
            <Text style={ls.markAllText}>Mark all as checked ({uncheckedCount})</Text>
          </TouchableOpacity>
        )}
      </View>

      <FlatList
        data={filtered}
        keyExtractor={a => a.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={C.cheese} />}
        contentContainerStyle={{ paddingBottom: 24, paddingTop: 6 }}
        initialNumToRender={8}
        windowSize={7}
        removeClippedSubviews
        ListEmptyComponent={<Text style={st.emptyOnNavy}>No alerts here.</Text>}
        renderItem={({ item }) => (
          <View style={st.whiteCard}>
            <View style={ls.headRow}>
              <View style={ls.headLeft}>
                <Text style={ls.alertId} numberOfLines={1}>Alert #{item.nodeAlertId}</Text>
                <Text style={st.cardSub} numberOfLines={1}>{item.nodeName}</Text>
              </View>
              <View style={[st.statusPill, ls.pill,
                            item.status === 'checked' ? st.pillOk : st.pillBad]}>
                <Text style={[st.statusPillText,
                              { color: item.status === 'checked' ? C.green : C.red }]}
                      numberOfLines={1}>
                  {item.status === 'checked' ? '✓ checked' : 'unchecked'}
                </Text>
              </View>
            </View>

            <Text style={[st.cardSub, { marginTop: 8 }]}>
              {item.time} · peak {item.peak} · {item.rats} rat{item.rats > 1 ? 's' : ''}
            </Text>

            {item.imagesDeleted ? (
              <View style={ls.deletedNote}>
                <Ionicons name="trash-outline" size={15} color={C.textMuted} />
                <Text style={ls.deletedText}>Images deleted from the node</Text>
              </View>
            ) : (
              <View style={ls.actions}>
                <TouchableOpacity style={[st.btnCheck, ls.actionBtn]}
                  onPress={() => onOpenImages(item)}>
                  <Ionicons name="images-outline" size={15} color={C.cheese} />
                  <Text style={[st.btnCheckText, { marginLeft: 6 }]}>View images</Text>
                </TouchableOpacity>

                {item.status === 'unchecked' && (
                  <TouchableOpacity style={[st.btnCheck, ls.actionBtn]}
                    onPress={() => onCheck(item.id)}>
                    <Ionicons name="checkmark-circle-outline" size={15} color={C.cheese} />
                    <Text style={[st.btnCheckText, { marginLeft: 6 }]}>Mark checked</Text>
                  </TouchableOpacity>
                )}
              </View>
            )}

            {item.imagesDeleted && item.status === 'unchecked' && (
              <TouchableOpacity style={st.btnCheck} onPress={() => onCheck(item.id)}>
                <Text style={st.btnCheckText}>Mark checked</Text>
              </TouchableOpacity>
            )}
          </View>
        )}
      />
    </View>
  );
}

const ls = StyleSheet.create({
  headRow: { flexDirection: 'row', alignItems: 'flex-start' },
  headLeft: { flex: 1, paddingRight: 10, minWidth: 0 },
  alertId: { color: C.textStrong, fontSize: 17, fontWeight: '800' },
  pill: { flexShrink: 0, maxWidth: 120 },
  actions: { flexDirection: 'row', gap: 8, marginTop: 4 },
  actionBtn: {
    flex: 1, flexDirection: 'row', justifyContent: 'center',
    alignItems: 'center', paddingHorizontal: 8,
  },
  markAll: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    backgroundColor: C.cheese, borderRadius: 999,
    paddingVertical: 10, marginTop: 12, gap: 8,
  },
  markAllText: { color: C.navyDeep, fontWeight: '800', fontSize: 13 },
  deletedNote: {
    flexDirection: 'row', alignItems: 'center', gap: 7, marginTop: 10,
    paddingVertical: 8, paddingHorizontal: 12,
    backgroundColor: 'rgba(42,49,88,0.07)', borderRadius: 999, alignSelf: 'flex-start',
  },
  deletedText: { color: C.textMuted, fontSize: 12, fontWeight: '700' },
});
