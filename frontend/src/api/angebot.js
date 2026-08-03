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

// Konto
export const getMe            = ()             => api.get('/me').then(r => r.data)

// Team (Mitgliederverwaltung)
export const getTeam                 = ()               => api.get('/team').then(r => r.data)
export const createTeamMember        = (body)           => api.post('/team', body).then(r => r.data)
export const updateTeamMemberRolle   = (userId, teamrolleId) =>
  api.patch(`/team/${userId}`, { teamrolle_id: teamrolleId }).then(r => r.data)
export const removeTeamMember        = (userId)          => api.delete(`/team/${userId}`)

// Teamrollen (RBAC)
export const getTeamrollen    = ()         => api.get('/teamrollen').then(r => r.data)
export const createTeamrolle  = (body)     => api.post('/teamrollen', body).then(r => r.data)
export const updateTeamrolle  = (id, body) => api.patch(`/teamrollen/${id}`, body).then(r => r.data)
export const deleteTeamrolle  = (id)       => api.delete(`/teamrollen/${id}`)

// Permissions-Katalog
export const getPermissions   = ()         => api.get('/permissions').then(r => r.data)

// Audit-Log
export const getAuditLog      = (limit = 100) => api.get('/audit-log', { params: { limit } }).then(r => r.data)

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
