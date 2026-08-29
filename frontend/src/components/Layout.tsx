import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  IconCalendar,
  IconHome,
  IconPencil,
  IconProfile,
  IconSearch,
  IconSettings,
  IconSparkle,
} from './Icons'
import { api } from '../api/client'

const NAV = [
  { to: '/', label: 'Início', Icon: IconHome, end: true },
  { to: '/texts', label: 'Meus Textos', Icon: IconPencil },
  { to: '/inbox', label: 'Conteúdo', Icon: IconSparkle },
  { to: '/queue', label: 'Fila', Icon: IconCalendar },
  { to: '/accounts', label: 'Contas', Icon: IconProfile },
]

export default function Layout() {
  const navigate = useNavigate()

  async function logout() {
    await api.logout()
    navigate('/login')
  }

  return (
    <div className="shell">
      <nav className="sidebar">
        {NAV.map(({ to, label, Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
          >
            <Icon size={26} />
            <span className="nav-label">{label}</span>
          </NavLink>
        ))}
        <NavLink
          to="/monitoring"
          className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}
        >
          <IconSearch size={26} />
          <span className="nav-label">Monitorar</span>
        </NavLink>
        <NavLink to="/settings" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
          <IconSettings size={26} />
          <span className="nav-label">Config</span>
        </NavLink>
        <button
          className="nav-item"
          onClick={logout}
          style={{ background: 'none', border: 0, cursor: 'pointer', marginTop: 'auto' }}
        >
          <span className="nav-label small muted">Sair</span>
        </button>
      </nav>

      <main className="main">
        <Outlet />
      </main>

      <nav className="tabbar">
        {NAV.map(({ to, label, Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            aria-label={label}
            className={({ isActive }) => (isActive ? 'active' : '')}
          >
            <Icon size={26} />
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
