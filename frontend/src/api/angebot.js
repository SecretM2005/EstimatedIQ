import axios from 'axios'

const api = axios.create({ baseURL: '/api/v2', timeout: 60000 })

// Rollen
export const getRollen        = ()         => api.get('/rollen').then(r => r.data)
export const createRolle      = (body)     => api.post('/rollen', body).then(r => r.data)
export const updateRolle      = (id, body) => api.put(`/rollen/${id}`, body).then(r => r.data)
export const deleteRolle      = (id)       => api.delete(`/rollen/${id}`)

// Projekte
export const getProjekte      = ()         => api.get('/projekte').then(r => r.data)
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

// Angebote
export const createAngebot    = (pId, b)   => api.post(`/projekte/${pId}/angebote`, b).then(r => r.data)
export const getPdfUrl        = (id)       => `/api/v2/angebote/${id}/pdf`
