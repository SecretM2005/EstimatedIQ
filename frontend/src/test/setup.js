// Globales Test-Setup für Vitest: erweitert expect um jest-dom-Matcher
// (z. B. toBeInTheDocument) und räumt nach jedem Test das DOM auf.
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})
