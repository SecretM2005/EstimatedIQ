import axios from 'axios'
import { supabase } from '../lib/supabase'

const api = axios.create({
  baseURL: (import.meta.env.VITE_API_URL || '') + '/api/v2',
  timeout: 60000,
})

// Supabase-Access-Token an jeden Request hängen (getSession liest aus dem
// lokalen Cache und refresht bei Bedarf automatisch).
api.interceptors.request.use(async (config) => {
  if (supabase) {
    const { data } = await supabase.auth.getSession()
    const token = data.session?.access_token
    if (token) config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Rollen
export const getRollen        = ()         => api.get('/rollen').then(r => r.data)
export const createRolle      = (body)     => api.post('/rollen', body).then(r => r.data)
export const updateRolle      = (id, body) => api.put(`/rollen/${id}`, body).then(r => r.data)
export const deleteRolle      = (id)       => api.delete(`/rollen/${id}`)

// Benutzer / Konto
export const getMe            = ()             => api.get('/me').then(r => r.data)
export const getUsers         = ()             => api.get('/users').then(r => r.data)
export const createUser       = (body)         => api.post('/users', body).then(r => r.data)
export const updateUserRole   = (id, rolle)    => api.patch(`/users/${id}`, { rolle }).then(r => r.data)
export const deleteUser       = (id)           => api.delete(`/users/${id}`)

// Projekte
export const getProjekte      = (nurMeine)  => api.get('/projekte', { params: nurMeine ? { nur_meine: true } : undefined }).then(r => r.data)
export const createProjekt    = (body)     => api.post('/projekte', body).then(r => r.data)
export const getProjekt       = (id)       => api.get(`/projekte/${id}`).then(r => r.data)
export const updateProjekt    = (id, body) => api.patch(`/projekte/${id}`, body).then(r => r.data)
export const deleteProjekt    = (id)       => api.delete(`/projekte/${id}`)

// Positionen
export const getPositionen    = (pId)      => api.get(`/projekte/${pId}/positionen`).then(r => r.data)
export const createPosition   = (pId, b)   => api.post(`/projekte/${pId}/positionen`, b).then(r => r.data)
export const updateIstStunden = (id, ist)  => api.patch(`/positionen/${id}/ist-stunden`, { ist_stunden: ist }).then(r => r.data)
export const deletePosition   = (id)       => api.delete(`/positionen/${id}`)

// Ähnlichkeitssuche
export const sucheAehnliche   = (body)     => api.post('/positionen/suche', body).then(r => r.data)

// Import
export const importierePositionen = (file) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/import/positionen', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  }).then(r => r.data)
}

// Referenzprojekte
export const sucheReferenzprojekte = (body)            => api.post('/referenzprojekte/suche', body).then(r => r.data)
export const vorlagUebernehmen     = (pId, referenzId) => api.post(`/projekte/${pId}/positionen/aus-referenz/${referenzId}`).then(r => r.data)

// Status & Dashboard
export const updateProjektStatus = (id, body) => api.patch(`/projekte/${id}/status`, body).then(r => r.data)
export const getDashboardStats   = ()          => api.get('/dashboard/stats').then(r => r.data)

// Angebote (PDF)
export const createAngebot    = (pId, b)   => api.post(`/projekte/${pId}/angebote`, b).then(r => r.data)
// Lädt das PDF über axios (Bearer-Token via Interceptor) und öffnet es im neuen Tab
export const openAngebotPdf = async (id) => {
  const res = await api.get(`/angebote/${id}/pdf`, { responseType: 'blob', timeout: 120000 })
  const url = URL.createObjectURL(new Blob([res.data], { type: 'application/pdf' }))
  window.open(url, '_blank')
  setTimeout(() => URL.revokeObjectURL(url), 60000)
}
