import { createClient } from '@supabase/supabase-js'

const url     = import.meta.env.VITE_SUPABASE_URL
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY

// Ohne Konfiguration (lokale Entwicklung) läuft die App ohne Login –
// das Backend muss dann mit AUTH_DISABLED=true laufen.
export const supabase = url && anonKey ? createClient(url, anonKey) : null
