// src/components/TabBar.js — taller bar, icon+label tabs, circular active
// bubble with a spring animation (no extra libraries; Ionicons ships with Expo).
//
// CUSTOM ICONS LATER: to use your own PNGs instead of Ionicons, replace the
// <Ionicons .../> line inside TabItem with:
//   <Image source={ICONS[id]} style={{ width: 24, height: 24, tintColor: color }} />
// and define ICONS = { home: require('../../assets/icons/home.png'), ... }

import React, { useEffect, useRef } from 'react';
import { View, Text, TouchableOpacity, Animated, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { C } from '../theme/theme';

const TABS = [
  { id: 'home',    label: 'Home',    icon: 'home-outline',          iconActive: 'home' },
  { id: 'fleet',   label: 'Fleet',   icon: 'radio-outline',         iconActive: 'radio' },
  { id: 'alerts',  label: 'Alerts',  icon: 'notifications-outline', iconActive: 'notifications' },
  { id: 'gallery', label: 'Gallery', icon: 'images-outline',        iconActive: 'images' },
  { id: 'profile', label: 'Profile', icon: 'person-outline',        iconActive: 'person' },
];

function TabItem({ tab, focused, onPress, badge }) {
  const anim = useRef(new Animated.Value(focused ? 1 : 0)).current;

  useEffect(() => {
    Animated.spring(anim, {
      toValue: focused ? 1 : 0,
      useNativeDriver: true,
      friction: 6,
      tension: 80,
    }).start();
  }, [focused]);

  const bubbleScale = anim.interpolate({ inputRange: [0, 1], outputRange: [0.3, 1] });
  const lift        = anim.interpolate({ inputRange: [0, 1], outputRange: [0, -6] });

  return (
    <TouchableOpacity style={s.item} onPress={onPress} activeOpacity={0.8}>
      <Animated.View style={{ transform: [{ translateY: lift }], alignItems: 'center' }}>
        <View style={s.iconSlot}>
          {/* circular cheese bubble springs in behind the icon */}
          <Animated.View style={[s.bubble, { opacity: anim, transform: [{ scale: bubbleScale }] }]} />
          <Ionicons
            name={focused ? tab.iconActive : tab.icon}
            size={24}
            color={focused ? C.navyDeep : C.mutedOnNavy}
          />
          {badge > 0 && (
            <View style={s.badge}><Text style={s.badgeText}>{badge}</Text></View>
          )}
        </View>
        <Text style={[s.label, focused && s.labelActive]}>{tab.label}</Text>
      </Animated.View>
    </TouchableOpacity>
  );
}

export default function TabBar({ tab, setTab, alertBadge }) {
  return (
    <View style={s.bar}>
      {TABS.map(t => (
        <TabItem
          key={t.id}
          tab={t}
          focused={tab === t.id}
          onPress={() => setTab(t.id)}
          badge={t.id === 'alerts' ? alertBadge : 0}
        />
      ))}
    </View>
  );
}

const s = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    backgroundColor: C.navyDeep,
    paddingTop: 14,
    paddingBottom: 30,        // taller bar
    paddingHorizontal: 8,
    borderTopLeftRadius: 32,  // curvier shell
    borderTopRightRadius: 32,
  },
  item: { flex: 1, alignItems: 'center' },
  iconSlot: {
    width: 52, height: 52,    // room for the circular bubble
    alignItems: 'center', justifyContent: 'center',
  },
  bubble: {
    position: 'absolute',
    width: 52, height: 52,
    borderRadius: 26,         // perfect circle — no rectangle anywhere
    backgroundColor: C.cheese,
  },
  label: { color: C.mutedOnNavy, fontSize: 11, marginTop: 3 },
  labelActive: { color: C.cheese, fontWeight: '800' },
  badge: {
    position: 'absolute', top: 2, right: 2,
    backgroundColor: C.red, borderRadius: 999,
    minWidth: 17, height: 17, paddingHorizontal: 4,
    alignItems: 'center', justifyContent: 'center',
    borderWidth: 2, borderColor: C.navyDeep,
  },
  badgeText: { color: C.white, fontSize: 9, fontWeight: '800' },
});
