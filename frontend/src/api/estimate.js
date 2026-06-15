import axios from 'axios'

export async function getEstimate(beschreibung, region) {
  try {
    const response = await axios.post(
      '/api/estimate',
      { beschreibung, region },
      { timeout: 30_000 }
    )
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
