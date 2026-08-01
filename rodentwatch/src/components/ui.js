// src/components/ui.js — small shared UI pieces.
import React from 'react';
import { View, Text, TouchableOpacity } from 'react-native';
import { C } from '../theme/theme';
import { st } from '../theme/styles';

export const Chip = ({ label, active, onPress, danger }) => (
  <TouchableOpacity onPress={onPress} style={[
    st.chip,
    active && { backgroundColor: danger ? C.red : C.ink, borderColor: danger ? C.red : C.ink },
  ]}>
    <Text style={[st.chipText, active && { color: C.white }]}>{label}</Text>
  </TouchableOpacity>
);

export const Dot = ({ ok }) => (
  <View style={[st.dot, { backgroundColor: ok ? C.green : C.red }]} />
);

export const Row = ({ k, v, color }) => (
  <View style={st.kvRow}>
    <Text style={st.kvKey}>{k}</Text>
    <Text style={[st.kvVal, color && { color }]} numberOfLines={1}>{String(v)}</Text>
  </View>
);

export const SectionTitle = ({ children }) => (
  <Text style={st.sectionTitle}>{children}</Text>
);
