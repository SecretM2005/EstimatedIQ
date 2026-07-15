/**
 * Rollen: Datentabellen-Rendering.
 * Sichert das zentrale UI-Muster ab (Daten aus der API → Tabelle) inkl.
 * Leer-Zustand. Bricht das Rendering, ist die Kernansicht unbrauchbar.
 */
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'

// API-Modul mocken – die Seite lädt Rollen in useEffect.
const getRollen = vi.fn()
vi.mock('../api/angebot', () => ({
  getRollen: () => getRollen(),
  createRolle: vi.fn(),
  updateRolle: vi.fn(),
  deleteRolle: vi.fn(),
}))

import Rollen from './Rollen'

describe('Rollen', () => {
  it('rendert die geladenen Rollen mit Stundensatz', async () => {
    getRollen.mockResolvedValue([
      { id: 1, name: 'Senior Developer', stundensatz_eur: 120 },
      { id: 2, name: 'Projektleiter', stundensatz_eur: 130 },
    ])

    render(<Rollen />)

    expect(await screen.findByText('Senior Developer')).toBeInTheDocument()
    expect(screen.getByText('Projektleiter')).toBeInTheDocument()
    // Betrag wird als EUR formatiert dargestellt
    expect(screen.getAllByText(/120/).length).toBeGreaterThan(0)
  })

  it('zeigt einen Leer-Zustand, wenn keine Rollen existieren', async () => {
    getRollen.mockResolvedValue([])

    render(<Rollen />)

    expect(await screen.findByText('Noch keine Rollen')).toBeInTheDocument()
  })
})
