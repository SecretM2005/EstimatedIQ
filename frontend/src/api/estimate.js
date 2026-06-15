import axios from 'axios'

export async function getEstimate(beschreibung, region, verfuegbare_teamgroesse = null, projekt_groesse = 'mittel') {
  const body = { beschreibung, region, projekt_groesse }
  if (verfuegbare_teamgroesse != null && Number(verfuegbare_teamgroesse) >= 1) {
    body.verfuegbare_teamgroesse = Number(verfuegbare_teamgroesse)
  }
  try {
    const response = await axios.post('/api/estimate', body, { timeout: 30_000 })
    return response.data
  } catch (err) {
    if (!err.response) {
      throw new Error(
        'Backend nicht erreichbar – stelle sicher, dass der Server auf localhost:8000 läuft.'
      )
    }
    const detail = err.response.data?.detail ?? err.response.statusText
    throw new Error(`API-Fehler (${err.response.status}): ${detail}`)
  }
}
