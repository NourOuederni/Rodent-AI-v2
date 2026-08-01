// src/api/supabase.js — the one place the app knows about Supabase.
// Fill in YOUR project's URL and anon key (Dashboard → Settings → API).

import 'react-native-url-polyfill/auto';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient } from '@supabase/supabase-js';

export const SUPABASE_URL = 'https://vkeeujkwjoiholgojrdw.supabase.co';
export const SUPABASE_ANON_KEY = 'sb_publishable_yWZ43Cp2WVqI__0v7BT77w_WVMhYX6l';

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    storage: AsyncStorage,
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: false,
  },
});
