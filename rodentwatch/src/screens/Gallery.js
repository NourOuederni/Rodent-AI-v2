import React, { useState, useEffect, useCallback } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, FlatList, Modal,
  RefreshControl, ActivityIndicator, Alert, StyleSheet,
} from 'react-native';
import { Image } from 'expo-image';
import { Ionicons } from '@expo/vector-icons';
import { C } from '../theme/theme';
import { st } from '../theme/styles';

const CACHE = 'memory-disk';
const BLUR = 'L6C~2K00_3~q00%M-;RjIUt7t7Rj';

export default function GalleryScreen({
  session, nodeApi, goTab,
  images, setImages, loaded, setLoaded,
  filter, clearFilter,
  onDelete,                    // async (names[]) => true/false
}) {
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [viewer, setViewer] = useState(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState([]);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async (force = false) => {
    if (!session) return;
    if (loaded && !force) return;
    setBusy(true);
    try {
      const list = (await nodeApi('/api/images'))
        .sort((a, b) => b.name.localeCompare(a.name, undefined, { numeric: true }));
      setImages(list);
      setLoaded(true);
      list.slice(0, 8).forEach(i =>
        Image.prefetch(`http://${session.ip}/api/image?name=${i.name}`, CACHE));
    } catch (e) {}
    setBusy(false);
  }, [session, nodeApi, loaded, setImages, setLoaded]);

  useEffect(() => { load(); }, [load]);

  if (!session) return (
    <View style={[st.center, { flex: 1, padding: 30 }]}>
      <Ionicons name="cloud-offline-outline" size={46} color={C.mutedOnNavy} />
      <Text style={st.emptyTitle}>Not connected</Text>
      <Text style={st.emptyOnNavy}>
        The gallery lives on each node's SD card. Join a node's WiFi and connect to browse its images.
      </Text>
      <TouchableOpacity style={[st.btnPrimary, { marginTop: 18, minWidth: 180 }]}
        onPress={() => goTab('fleet')}>
        <Text style={st.btnPrimaryText}>Go to fleet</Text>
      </TouchableOpacity>
    </View>
  );

  const base = images.filter(i => !filter || i.name.startsWith(filter));
  const shown = base.filter(i => i.name.toLowerCase().includes(q.toLowerCase().trim()));

  const toggle = (name) => setSelected(prev =>
    prev.includes(name) ? prev.filter(n => n !== name) : [...prev, name]);

  const allShownSelected = shown.length > 0 && shown.every(i => selected.includes(i.name));
  const selectAll = () => setSelected(allShownSelected ? [] : shown.map(i => i.name));

  const exitSelect = () => { setSelectMode(false); setSelected([]); };

  const confirmDelete = () => {
    const n = selected.length;
    const alertIds = [...new Set(selected.map(f => f.match(/^R(\d+)_/)?.[1]).filter(Boolean))];
    Alert.alert(
      `Delete ${n} image${n > 1 ? 's' : ''}?`,
      `They will be permanently removed from the node's SD card.\n\n` +
      `Alert${alertIds.length > 1 ? 's' : ''} #${alertIds.join(', #')} will be marked as checked ` +
      `and flagged as having no images.`,
      [{ text: 'Cancel', style: 'cancel' },
       { text: 'Delete', style: 'destructive', onPress: doDelete }]);
  };

  const doDelete = async () => {
    setDeleting(true);
    const ok = await onDelete(selected);
    setDeleting(false);
    if (ok) exitSelect();
    else Alert.alert('Delete failed', 'The node did not confirm the deletion. Check the connection and try again.');
  };

  return (
    <View style={{ flex: 1 }}>
      <View style={st.headerBlobSmall}>
        <View style={{ flexDirection: 'row', alignItems: 'center' }}>
          <Text style={[st.screenTitle, { flex: 1 }]} numberOfLines={1}>
            {selectMode ? `${selected.length} selected` : `Gallery · ${session.status?.device}`}
          </Text>
          {images.length > 0 && (
            <TouchableOpacity onPress={() => selectMode ? exitSelect() : setSelectMode(true)}>
              <Text style={gs.headerAction}>{selectMode ? 'Cancel' : 'Select'}</Text>
            </TouchableOpacity>
          )}
        </View>

        {selectMode ? (
          <View style={gs.selectBar}>
            <TouchableOpacity style={gs.selectAllBtn} onPress={selectAll}>
              <Ionicons name={allShownSelected ? 'square-outline' : 'checkbox-outline'}
                size={16} color={C.white} />
              <Text style={gs.selectAllText}>
                {allShownSelected ? 'Deselect all' : `Select all (${shown.length})`}
              </Text>
            </TouchableOpacity>
            <TouchableOpacity
              style={[gs.deleteBtn, selected.length === 0 && { opacity: 0.4 }]}
              disabled={selected.length === 0 || deleting}
              onPress={confirmDelete}>
              {deleting ? <ActivityIndicator color={C.white} size="small" /> : (
                <>
                  <Ionicons name="trash" size={16} color={C.white} />
                  <Text style={gs.deleteText}>Delete ({selected.length})</Text>
                </>
              )}
            </TouchableOpacity>
          </View>
        ) : filter ? (
          <TouchableOpacity style={gs.filterChip} onPress={clearFilter}>
            <Text style={gs.filterText}>Showing alert #{filter.replace(/^R|_$/g, '')}</Text>
            <Ionicons name="close-circle" size={16} color={C.navyDeep} />
          </TouchableOpacity>
        ) : (
          <TextInput style={st.searchOnNavy} value={q} onChangeText={setQ}
            placeholder="Search by alert ID (e.g. R12)…" placeholderTextColor={C.mutedOnNavy} />
        )}
      </View>

      {busy && images.length === 0 && (
        <View style={{ paddingVertical: 20 }}>
          <ActivityIndicator color={C.cheese} />
          <Text style={[st.emptyOnNavy, { marginTop: 8 }]}>Loading images from the node…</Text>
        </View>
      )}

      <FlatList
        data={shown}
        keyExtractor={i => i.name}
        numColumns={2}
        contentContainerStyle={{ padding: 10, paddingBottom: 24 }}
        initialNumToRender={6}
        maxToRenderPerBatch={6}
        windowSize={5}
        removeClippedSubviews
        refreshControl={
          <RefreshControl refreshing={busy} onRefresh={() => load(true)} tintColor={C.cheese} />
        }
        ListEmptyComponent={!busy && (
          <Text style={st.emptyOnNavy}>
            {filter ? 'No images saved for this alert on the node.'
                    : 'No saved detections on this node.'}
          </Text>
        )}
        renderItem={({ item }) => {
          const isSel = selected.includes(item.name);
          return (
            <TouchableOpacity
              style={st.thumbWrap}
              onLongPress={() => { setSelectMode(true); toggle(item.name); }}
              onPress={() => selectMode ? toggle(item.name) : setViewer(item.name)}>
              <View>
                <Image
                  source={{ uri: `http://${session.ip}/api/image?name=${item.name}` }}
                  style={[st.thumb, isSel && gs.thumbSelected]}
                  cachePolicy={CACHE}
                  recyclingKey={item.name}
                  placeholder={BLUR}
                  transition={150}
                  contentFit="cover"
                />
                {selectMode && (
                  <View style={[gs.checkCircle, isSel && gs.checkCircleOn]}>
                    {isSel && <Ionicons name="checkmark" size={15} color={C.navyDeep} />}
                  </View>
                )}
              </View>
              <Text style={st.thumbLabel}>{item.name} · {(item.size / 1024).toFixed(0)} KB</Text>
            </TouchableOpacity>
          );
        }}
      />

      <Modal visible={!!viewer} transparent onRequestClose={() => setViewer(null)}>
        <TouchableOpacity style={st.viewerBg} activeOpacity={1} onPress={() => setViewer(null)}>
          {viewer && (
            <Image source={{ uri: `http://${session.ip}/api/image?name=${viewer}` }}
              style={st.viewerImg} cachePolicy={CACHE} contentFit="contain" />
          )}
          <Text style={{ color: C.mutedOnNavy, marginTop: 12 }}>{viewer} — tap to close</Text>
        </TouchableOpacity>
      </Modal>
    </View>
  );
}

const gs = StyleSheet.create({
  headerAction: { color: C.cheese, fontWeight: '800', fontSize: 14 },
  filterChip: {
    flexDirection: 'row', alignItems: 'center', alignSelf: 'flex-start',
    backgroundColor: C.cheese, borderRadius: 999,
    paddingHorizontal: 14, paddingVertical: 7, marginTop: 12, gap: 8,
  },
  filterText: { color: C.navyDeep, fontWeight: '800', fontSize: 13 },
  selectBar: { flexDirection: 'row', gap: 8, marginTop: 12 },
  selectAllBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 6, borderRadius: 999, paddingVertical: 9,
    borderWidth: 1.5, borderColor: C.mutedOnNavy,
  },
  selectAllText: { color: C.white, fontWeight: '700', fontSize: 12 },
  deleteBtn: {
    flex: 1, flexDirection: 'row', alignItems: 'center', justifyContent: 'center',
    gap: 6, borderRadius: 999, paddingVertical: 9, backgroundColor: C.red,
  },
  deleteText: { color: C.white, fontWeight: '800', fontSize: 12 },
  thumbSelected: { borderWidth: 3, borderColor: C.cheese },
  checkCircle: {
    position: 'absolute', top: 8, right: 8,
    width: 24, height: 24, borderRadius: 12,
    backgroundColor: 'rgba(0,0,0,0.45)', borderWidth: 2, borderColor: C.white,
    alignItems: 'center', justifyContent: 'center',
  },
  checkCircleOn: { backgroundColor: C.cheese, borderColor: C.cheese },
});
