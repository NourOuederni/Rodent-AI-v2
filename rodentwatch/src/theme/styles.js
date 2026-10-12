// src/theme/styles.js — shared StyleSheet on semantic tokens.
import { StyleSheet } from 'react-native';
import { C, R } from './theme';

export const st = StyleSheet.create({
  canvas: { flex: 1, backgroundColor: C.navy, paddingTop: 44 },
  center: { alignItems: 'center', justifyContent: 'center' },

  /* decorative corner blob — rendered on every screen from App.js */
  cornerBlob: {
    position: 'absolute',
    bottom: -60, right: -70,       // lower — hugs the corner, tab bar overlaps it
    width: 220, height: 220, borderRadius: 110,
    backgroundColor: C.sand, opacity: 0.14,   // warm sand, matches the cards
  },

  /* login */
  loginBlobTop: {
    position: 'absolute', top: -80, right: -60, width: 240, height: 240,
    backgroundColor: C.sand, borderRadius: 120, opacity: 0.14,
  },
  loginLogo: { width: 110, height: 110, borderRadius: 55, marginBottom: 10 },
  loginTitle: { color: C.white, fontSize: 30, fontWeight: '800' },
  loginSub: { color: C.mutedOnNavy, marginBottom: 22 },
  loginCard: {
    backgroundColor: C.surface, borderRadius: R.blob, padding: 22, width: '100%',
    borderBottomLeftRadius: 60,
  },
  cstLogo: { width: 54, height: 54, marginTop: 26, opacity: 0.9, resizeMode: 'contain' },

  /* header blobs */
  headerBlob: {
    backgroundColor: C.navyDeep, marginHorizontal: 10, borderRadius: R.blob,
    borderBottomRightRadius: 70, padding: 18, marginBottom: 14,
  },
  headerBlobSmall: {
    backgroundColor: C.navyDeep, marginHorizontal: 10, borderRadius: R.blob,
    borderBottomLeftRadius: 60, padding: 18, marginBottom: 8,
  },
  screenTitle: { color: C.white, fontSize: 24, fontWeight: '800' },
  avatar: { width: 52, height: 52, borderRadius: 26, backgroundColor: C.surface },
  hello: { color: C.white, fontSize: 20, fontWeight: '800' },
  linkState: { color: C.mutedOnNavy, fontSize: 12, marginLeft: 6 },

  statRow: { flexDirection: 'row', gap: 10, marginTop: 16 },
  statCard: {
    flex: 1, backgroundColor: C.cheese, borderRadius: R.card, padding: 14,
    borderBottomRightRadius: 34,
  },
  statNum: { color: C.navyDeep, fontSize: 26, fontWeight: '800' },
  statLabel: { color: C.cheeseDark, fontSize: 12, marginTop: 2 },

  /* cards */
  sectionTitle: {
    color: C.mutedOnNavy, fontSize: 12, textTransform: 'uppercase',
    letterSpacing: 1.2, marginHorizontal: 20, marginTop: 14, marginBottom: 8,
  },
  whiteCard: {   // name kept so no screen needs edits; the color is now semantic
    backgroundColor: C.surface, borderRadius: R.card, padding: 14,
    marginHorizontal: 12, marginBottom: 10, borderBottomLeftRadius: 30,
  },
  cardTitle: { color: C.textStrong, fontSize: 15, fontWeight: '700' },
  cardSub: { color: C.textMuted, fontSize: 12, marginTop: 4 },

  statusPill: { borderRadius: R.pill, paddingHorizontal: 10, paddingVertical: 3 },
  pillOk: { backgroundColor: C.tintGreen },
  pillBad: { backgroundColor: C.tintRed },
  statusPillText: { fontSize: 11, fontWeight: '700' },

  actionCard: {
    flex: 1, backgroundColor: C.surface, borderRadius: R.card, padding: 12,
    alignItems: 'center', borderTopRightRadius: 30,
  },
  actionEmoji: { fontSize: 22 },
  actionText: { color: C.textStrong, fontSize: 12, fontWeight: '700', marginTop: 6 },

  /* inputs & buttons */
  inputLabel: { color: C.textMuted, fontSize: 12, marginBottom: 6 },
  input: {
    backgroundColor: C.surfaceInput, borderRadius: 14, color: C.textStrong,
    paddingHorizontal: 14, paddingVertical: 11, fontSize: 15,
  },
  btnPrimary: {
    backgroundColor: C.cheese, borderRadius: R.pill, paddingVertical: 13,
    alignItems: 'center', marginTop: 16,
  },
  btnPrimaryText: { color: C.navyDeep, fontWeight: '800', fontSize: 15 },
  btnCheck: {
    backgroundColor: C.navyDeep, borderRadius: R.pill, paddingVertical: 10,
    alignItems: 'center', marginTop: 12,
  },
  btnCheckText: { color: C.cheese, fontWeight: '700', fontSize: 13 },
  btnDanger: {
    backgroundColor: C.tintRed, borderRadius: R.pill, paddingVertical: 12,
    alignItems: 'center', marginHorizontal: 12, marginTop: 18,
  },
  btnDangerText: { color: C.red, fontWeight: '800' },
  errText: { color: C.red, fontSize: 12, marginTop: 8 },
  hintOnWhite: { color: C.textMuted, fontSize: 11, marginTop: 12, textAlign: 'center' },

  /* chips / search */
  chip: {
    borderRadius: R.pill, borderWidth: 1.5, borderColor: C.mutedOnNavy,
    paddingHorizontal: 14, paddingVertical: 6,
  },
  chipText: { color: C.mutedOnNavy, fontSize: 12, fontWeight: '700' },
  searchOnNavy: {
    backgroundColor: 'rgba(255,255,255,0.08)', borderRadius: R.pill,
    color: C.white, paddingHorizontal: 16, paddingVertical: 9, marginTop: 12, fontSize: 14,
  },

  dot: { width: 10, height: 10, borderRadius: 5 },
  kvRow: {
    flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 6,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.divider,
  },
  kvKey: { color: C.textMuted, fontSize: 13 },
  kvVal: { color: C.textStrong, fontSize: 13, fontWeight: '600', maxWidth: '60%' },

  alertCountPill: {
    backgroundColor: C.red, borderRadius: R.pill, minWidth: 26,
    paddingHorizontal: 7, paddingVertical: 2, alignItems: 'center',
  },
  alertCountText: { color: C.white, fontWeight: '800', fontSize: 12 },

  emptyOnNavy: { color: C.mutedOnNavy, textAlign: 'center', marginTop: 20, paddingHorizontal: 30, lineHeight: 19 },
  emptyTitle: { color: C.white, fontSize: 18, fontWeight: '800', marginTop: 8 },
  footNote: { color: C.mutedOnNavy, fontSize: 11, textAlign: 'center', marginBottom: 8 },

  /* gallery */
  thumbWrap: { flex: 1, margin: 6 },
  thumb: { width: '100%', aspectRatio: 4 / 3, borderRadius: 16, backgroundColor: C.navyDeep },
  thumbLabel: { color: C.mutedOnNavy, fontSize: 11, marginTop: 4 },
  viewerBg: { flex: 1, backgroundColor: 'rgba(10,12,26,0.97)', alignItems: 'center', justifyContent: 'center' },
  viewerImg: { width: '94%', height: '70%' },

  /* modal sheet */
  modalBg: { flex: 1, backgroundColor: 'rgba(10,12,26,0.6)', justifyContent: 'flex-end' },
  modalSheet: {
    backgroundColor: C.surface, borderTopLeftRadius: R.blob, borderTopRightRadius: R.blob,
    padding: 22, paddingBottom: 34,
  },
  sheetHandle: {
    width: 44, height: 5, borderRadius: 3, backgroundColor: C.divider,
    alignSelf: 'center', marginBottom: 14,
  },

  /* banner + admin msg */
  banner: {
    backgroundColor: C.red, marginHorizontal: 12, marginBottom: 8,
    borderRadius: 16, padding: 12,
  },
  bannerText: { color: C.white, fontWeight: '800' },
  notice: {
    flexDirection: 'row', alignItems: 'center',
    backgroundColor: C.cheese, marginHorizontal: 12, marginBottom: 8,
    borderRadius: 16, padding: 12,
  },
  noticeText: { color: C.navyDeep, fontWeight: '700', fontSize: 13, flex: 1 },
  adminMsg: {
    color: C.navyDeep, backgroundColor: C.cheese, marginHorizontal: 12,
    borderRadius: 12, padding: 10, fontSize: 12, fontWeight: '700', marginBottom: 6,
  },
});
