import { NavLink } from 'react-router-dom'

const NAV_ITEMS = [
  { to: '/projekte',   label: 'Projekte' },
  { to: '/rollen',     label: 'Rollen'   },
  { to: '/historisch', label: 'Import'   },
]

export default function NavBar() {
  return (
    <header className="px-6 py-4 flex items-center justify-between bg-white border-b border-slate-200 sticky top-0 z-10">
      <NavLink to="/" className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
          <span className="text-white font-bold text-sm">IQ</span>
        </div>
        <span className="font-bold text-primary text-lg tracking-tight">EstimateIQ</span>
      </NavLink>

      <nav className="flex items-center gap-1">
        {NAV_ITEMS.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `text-sm px-3 py-2 rounded-lg font-medium transition-colors ${
                isActive ? 'bg-primary text-white' : 'text-slate-600 hover:bg-slate-100'
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </header>
  )
}
