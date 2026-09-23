import { NavLink, Outlet } from 'react-router-dom'

type Props = {
  onRefresh: () => Promise<void>
  refreshing: boolean
}

export default function MyTradeLayout({ onRefresh, refreshing }: Props) {
  return (
    <div className="mt-page">
      <div className="mt-subnav-wrap">
        <nav className="mt-subnav" aria-label="My Trade">
          <NavLink
            to="/mytrade/dashboard"
            end
            className={({ isActive }) => `mt-subnav-link${isActive ? ' active' : ''}`}
          >
            Dashboard
          </NavLink>
          <NavLink
            to="/mytrade/calendar"
            className={({ isActive }) => `mt-subnav-link${isActive ? ' active' : ''}`}
          >
            P&amp;L Calendar
          </NavLink>
          <NavLink
            to="/mytrade/journal"
            className={({ isActive }) => `mt-subnav-link${isActive ? ' active' : ''}`}
          >
            Journal
          </NavLink>
          <button
            type="button"
            className="mt-refresh-btn"
            title="Sync Groww data"
            aria-label="Refresh Groww data"
            disabled={refreshing}
            onClick={() => void onRefresh()}
          >
            <svg
              className={`mt-refresh-icon${refreshing ? ' spinning' : ''}`}
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              aria-hidden
            >
              <path
                d="M21 12a9 9 0 1 1-2.64-6.36"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
              <path d="M21 3v6h-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </nav>
      </div>
      <Outlet />
    </div>
  )
}
