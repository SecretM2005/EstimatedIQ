import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

/**
 * Sends a project description to the EstimateIQ backend and returns
 * cost, duration, risk, and confidence estimates.
 *
 * @param {string} beschreibung  Project description text
 * @param {string} region        ISO 3166-2 region code (e.g. "DE-BY")
 * @returns {Promise<EstimateResult>}
 */
export async function getEstimate(beschreibung, region) {
  try {
    const response = await axios.post(
      `${API_BASE}/api/estimate`,
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
