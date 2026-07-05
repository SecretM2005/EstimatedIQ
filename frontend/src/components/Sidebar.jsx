import { NavLink } from 'react-router-dom'

const Logo = () => (
  <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
    <path d="M5 4v16" stroke="#eef2ff" strokeWidth="2.4" strokeLinecap="round"/>
    <path d="M5 12l9-8M5 12l9 8" stroke="#6366f1" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
)

function NavItem({ to, icon, label, badge, end }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex items-center gap-2.5 h-10 px-3 rounded-lg text-[13.5px] font-medium transition-colors duration-100 ${
          isActive
            ? 'bg-indigo-50 text-accent border border-indigo-100 font-semibold'
            : 'text-slate-500 hover:bg-slate-100 border border-transparent'
        }`
      }
    >
      {icon}
      <span className="flex-1">{label}</span>
      {badge != null && (
        <span className="text-[11px] font-semibold text-slate-400 bg-slate-100 rounded-md px-1.5 py-0.5 tabular-nums">
          {badge}
        </span>
      )}
    </NavLink>
  )
}

export default function Sidebar() {
  return (
    <aside className="w-[250px] flex-none bg-white border-r border-slate-200 flex flex-col h-full overflow-hidden">
      {/* Logo */}
      <div className="px-[18px] py-4 flex items-center gap-2.5">
        <div className="w-[30px] h-[30px] rounded-lg bg-slate-900 flex items-center justify-center flex-none">
          <Logo />
        </div>
        <span className="text-[15px] font-bold tracking-tight text-slate-900">EstimateIQ</span>
        <span className="ml-auto text-[10px] font-semibold tracking-widest text-slate-400 border border-slate-200 rounded px-1.5 py-0.5">v1</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-3 pb-4 flex flex-col gap-0.5">
        <div className="text-[10px] font-bold tracking-[0.06em] uppercase text-slate-400 px-3 pt-3 pb-1.5">
          Übersicht
        </div>

        <NavItem
          to="/"
          end
          label="Dashboard"
          icon={
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="flex-none">
              <rect x="3" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.9"/>
              <rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.9"/>
              <rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.9"/>
              <rect x="14" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.9"/>
            </svg>
          }
        />

        <div className="text-[10px] font-bold tracking-[0.06em] uppercase text-slate-400 px-3 pt-4 pb-1.5">
          Arbeitsbereich
        </div>

        <NavItem
          to="/angebote"
          label="Angebote"
          icon={
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="flex-none">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6z" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/>
              <path d="M14 2v6h6M9 13h6M9 17h4" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round"/>
            </svg>
          }
        />

        <NavItem
          to="/projekte"
          label="Projekte"
          icon={
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="flex-none">
              <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" stroke="currentColor" strokeWidth="1.9" strokeLinejoin="round"/>
            </svg>
          }
        />

        <NavItem
          to="/rollen"
          label="Rollen & Stundensätze"
          icon={
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="flex-none">
              <rect x="4" y="4" width="16" height="16" rx="2" stroke="currentColor" strokeWidth="1.9"/>
              <path d="M4 9h16M9 9v11" stroke="currentColor" strokeWidth="1.9"/>
            </svg>
          }
        />

        <div className="text-[10px] font-bold tracking-[0.06em] uppercase text-slate-400 px-3 pt-4 pb-1.5">
          Import
        </div>

        <NavItem
          to="/historisch"
          label="Daten importieren"
          icon={
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" className="flex-none">
              <path d="M12 3v12m0 0 4-4m-4 4-4-4M5 21h14" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          }
        />
      </nav>

      {/* User */}
      <div className="border-t border-slate-200 p-3">
        <div className="flex items-center gap-2.5 px-2 py-1.5 rounded-lg">
          <span className="w-8 h-8 rounded-full bg-slate-200 text-slate-600 text-[11px] font-bold flex items-center justify-center flex-none select-none">
            EI
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-[12.5px] font-semibold text-slate-900 truncate">EstimateIQ</span>
            <span className="block text-[11px] text-slate-400">Kalkulations-Tool</span>
          </span>
        </div>
      </div>
    </aside>
  )
}
