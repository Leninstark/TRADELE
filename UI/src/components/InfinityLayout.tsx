import { NavLink, Outlet, useLocation } from 'react-router-dom'

export default function InfinityLayout() {
  const location = useLocation()
  const jarvisActive = location.pathname.startsWith('/infinity/jarvis')

  return (
    <div className="inf-page">
      <div className="inf-subnav-wrap">
        <nav className="inf-subnav" aria-label="Infinity agents">
          <NavLink
            to="/infinity/jarvis/test"
            className={() => `inf-subnav-link${jarvisActive ? ' active' : ''}`}
          >
            JARVIS
          </NavLink>
          <NavLink
            to="/infinity/friday"
            className={({ isActive }) => `inf-subnav-link${isActive ? ' active' : ''}`}
          >
            FRIDAY
          </NavLink>
        </nav>
      </div>
      <Outlet />
    </div>
  )
}
