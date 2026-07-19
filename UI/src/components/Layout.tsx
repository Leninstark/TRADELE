import { useCallback, useEffect, useState } from 'react'
import { NavLink, Outlet, useNavigate, useSearchParams } from 'react-router-dom'
import {
  fetchZerodhaLoginUrl,
  fetchZerodhaStatus,
  saveZerodhaToken,
  type ZerodhaStatus,
} from '../api/client'
import { getAuthUser, logout } from '../auth'

const primaryNav = [
  { to: '/explore', label: 'Explore' },
  { to: '/watchlist', label: 'Watchlist' },
  { to: '/intraday', label: 'Intraday' },
  { to: '/swing', label: 'Swing' },
  { to: '/investment', label: 'Investment' },
]

export default function Layout() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const user = getAuthUser()
  const username = user?.username || 'leninstark'
  const initial = (user?.name || username || 'U').charAt(0).toUpperCase()

  const [zerodha, setZerodha] = useState<ZerodhaStatus | null>(null)
  const [checking, setChecking] = useState(true)
  const [modalOpen, setModalOpen] = useState(false)
  const [tokenInput, setTokenInput] = useState('')
  const [saving, setSaving] = useState(false)
  const [modalError, setModalError] = useState('')

  const refreshStatus = useCallback(async () => {
    setChecking(true)
    try {
      const status = await fetchZerodhaStatus(username)
      setZerodha(status)
    } catch {
      setZerodha({
        connected: false,
        status: 'not_connected',
        message: 'Not connected',
        expires_at: null,
        username,
      })
    } finally {
      setChecking(false)
    }
  }, [username])

  useEffect(() => {
    refreshStatus()
  }, [refreshStatus])

  useEffect(() => {
    if (searchParams.get('zerodha') === 'connected') {
      refreshStatus()
      searchParams.delete('zerodha')
      setSearchParams(searchParams, { replace: true })
    }
  }, [searchParams, setSearchParams, refreshStatus])

  const handleSignOut = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const openConnectModal = async () => {
    setModalError('')
    setTokenInput('')
    setModalOpen(true)
    try {
      const url = await fetchZerodhaLoginUrl()
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch {
      setModalError('Could not open Zerodha login. Paste access token below if you have one.')
    }
  }

  const handleSaveToken = async () => {
    setModalError('')
    if (!tokenInput.trim()) {
      setModalError('Paste your access token')
      return
    }
    setSaving(true)
    try {
      const status = await saveZerodhaToken(username, tokenInput.trim())
      setZerodha(status)
      setModalOpen(false)
      setTokenInput('')
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setModalError(err.response?.data?.detail || err.message || 'Invalid token')
    } finally {
      setSaving(false)
    }
  }

  const connected = zerodha?.connected === true

  return (
    <div className="app-shell">
      <header className="gw-header">
        <div className="gw-header-inner">
          <NavLink to="/explore" className="gw-logo">
            <span className="gw-logo-mark">T</span>
            <span className="gw-logo-text">TRADELE</span>
          </NavLink>

          <nav className="gw-nav">
            {primaryNav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => `gw-nav-link${isActive ? ' active' : ''}`}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="gw-search">
            <span className="gw-search-icon">⌕</span>
            <input type="search" placeholder="Search stocks, strategies…" />
          </div>

          <div className="gw-header-actions">
            <div className={`gw-kite-status${connected ? ' is-connected' : ' is-offline'}`}>
              <span className={`gw-kite-dot${connected ? ' blink' : ''}`} />
              <span className="gw-kite-label">
                {checking ? 'Checking…' : connected ? 'Connected' : 'Not connected'}
              </span>
            </div>

            <button type="button" className="gw-connect-btn" onClick={openConnectModal}>
              Connect
            </button>

            <span className="gw-avatar" aria-hidden>
              {initial}
            </span>
            <button type="button" className="gw-signout" onClick={handleSignOut}>
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="main-content">
        <Outlet />
      </main>

      {modalOpen && (
        <div className="gw-modal-backdrop" onClick={() => setModalOpen(false)} role="presentation">
          <div
            className="gw-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-labelledby="connect-title"
          >
            <h2 id="connect-title">Connect Zerodha</h2>
            <p className="gw-modal-hint">
              Zerodha login opened in a new tab. After login, copy the <strong>access token</strong> and
              paste it below.
            </p>
            <label className="gw-modal-label">
              Access token
              <textarea
                value={tokenInput}
                onChange={(e) => setTokenInput(e.target.value)}
                placeholder="Paste access_token here"
                rows={3}
              />
            </label>
            {modalError && <p className="login-error">{modalError}</p>}
            <div className="gw-modal-actions">
              <button type="button" className="btn secondary" onClick={() => setModalOpen(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn secondary"
                onClick={async () => {
                  try {
                    const url = await fetchZerodhaLoginUrl()
                    window.open(url, '_blank', 'noopener,noreferrer')
                  } catch {
                    setModalError('Could not open Zerodha login')
                  }
                }}
              >
                Open Zerodha again
              </button>
              <button
                type="button"
                className="btn primary"
                onClick={handleSaveToken}
                disabled={saving}
              >
                {saving ? 'Saving…' : 'Save token'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
