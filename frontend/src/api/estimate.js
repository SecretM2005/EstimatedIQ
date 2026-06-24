import axios from 'axios'

function buildBody(beschreibung, region, verfuegbare_teamgroesse, projekt_groesse) {
  const body = { beschreibung, region, projekt_groesse: projekt_groesse ?? 'mittel' }
  if (verfuegbare_teamgroesse != null && Number(verfuegbare_teamgroesse) >= 1) {
    body.verfuegbare_teamgroesse = Number(verfuegbare_teamgroesse)
  }
  return body
}

function handleError(err) {
  if (!err.response) {
    throw new Error('Backend nicht erreichbar – stelle sicher, dass der Server auf localhost:8000 läuft.')
  }
  const detail = err.response.data?.detail ?? err.response.statusText
  throw new Error(`API-Fehler (${err.response.status}): ${detail}`)
}

export async function getEstimate(beschreibung, region, verfuegbare_teamgroesse = null, projekt_groesse = 'mittel') {
  try {
    const response = await axios.post('/api/estimate', buildBody(beschreibung, region, verfuegbare_teamgroesse, projekt_groesse), { timeout: 30_000 })
    return response.data
  } catch (err) {
    handleError(err)
  }
}

export async function getSensitivity(beschreibung, region, verfuegbare_teamgroesse = null, projekt_groesse = 'mittel') {
  try {
    const response = await axios.post('/api/estimate/sensitivity', buildBody(beschreibung, region, verfuegbare_teamgroesse, projekt_groesse), { timeout: 45_000 })
    return response.data
  } catch (err) {
    handleError(err)
  }
}
