/**
 * Login: Formular-Validierung und Fehleranzeige.
 * Wichtig, weil der Login die Eingangstür ist – eine falsche/fehlende
 * Fehlermeldung lässt Nutzer im Dunkeln stehen.
 */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Supabase-Client mocken – kein echter Netzwerkaufruf im Test.
const signInWithPassword = vi.fn()
vi.mock('../lib/supabase', () => ({
  supabase: { auth: { signInWithPassword: (...a) => signInWithPassword(...a) } },
}))

import Login from './Login'

describe('Login', () => {
  beforeEach(() => {
    signInWithPassword.mockReset()
  })

  it('zeigt bei falschen Zugangsdaten eine verständliche Fehlermeldung', async () => {
    signInWithPassword.mockResolvedValue({ error: { message: 'Invalid login credentials' } })

    render(<Login />)
    await userEvent.type(screen.getByPlaceholderText('name@firma.de'), 'demo@estimateiq.de')
    await userEvent.type(screen.getByPlaceholderText('••••••••'), 'falsch')
    await userEvent.click(screen.getByRole('button', { name: /anmelden/i }))

    expect(await screen.findByText('E-Mail oder Passwort ist falsch.')).toBeInTheDocument()
  })

  it('verlangt E-Mail und Passwort (Pflichtfelder)', () => {
    render(<Login />)
    expect(screen.getByPlaceholderText('name@firma.de')).toBeRequired()
    expect(screen.getByPlaceholderText('••••••••')).toBeRequired()
  })
})
