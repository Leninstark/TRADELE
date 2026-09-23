import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { NavLink, Outlet, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import {
  fetchGrowwLoginInfo,
  fetchGrowwStatus,
  fetchZerodhaLoginUrl,
  fetchZerodhaStatus,
  refreshGrowwToken,
  saveGrowwCredentials,
  saveGrowwToken,
  saveZerodhaToken,
  type GrowwStatus,
  type ZerodhaStatus,
} from '../api/client'
import {
  addUser,
  canAccessMyTrade,
  canAccessInfinity,
  getAuthUser,
  homePathForUser,
  listUsers,
  logout,
  removeUser,
  type PlatformUser,
  type UserRole,
} from '../auth'

const tradeAssistItems = [
  { to: '/intraday', label: 'Equity Intraday' },
  { to: '/swing', label: 'Equity Swing' },
  { to: '/fno', label: 'F&O' },
]

type Broker = 'pick' | 'zerodha' | 'groww'

export default function Layout() {
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const user = getAuthUser()
  const username = user?.username || 'leninstark'
  const displayName = user?.name || username
  const role = user?.role || 'admin'
  const initial = displayName.charAt(0).toUpperCase()
  const showMyTrade = canAccessMyTrade(username)
  const showInfinity = canAccessInfinity(username)
  const homePath = homePathForUser(username)

  const [zerodha, setZerodha] = useState<ZerodhaStatus | null>(null)
  const [groww, setGroww] = useState<GrowwStatus | null>(null)
  const [checking, setChecking] = useState(true)
  const [connectOpen, setConnectOpen] = useState(false)
  const [connectStep, setConnectStep] = useState<Broker>('pick')
  const [tokenInput, setTokenInput] = useState('')
  const [growwApiKey, setGrowwApiKey] = useState('')
  const [growwApiSecret, setGrowwApiSecret] = useState('')
  const [growwKeysUrl, setGrowwKeysUrl] = useState('https://groww.in/trade-api')
  const [saving, setSaving] = useState(false)
  const [modalError, setModalError] = useState('')

  const [assistOpen, setAssistOpen] = useState(false)
  const [profileOpen, setProfileOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)

  const [users, setUsers] = useState<PlatformUser[]>([])
  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState<UserRole>('trader')
  const [settingsError, setSettingsError] = useState('')
  const [settingsOk, setSettingsOk] = useState('')

  const assistRef = useRef<HTMLDivElement>(null)
  const profileRef = useRef<HTMLDivElement>(null)

  const refreshStatus = useCallback(async () => {
    setChecking(true)
    try {
      const [zStatus, gStatus] = await Promise.all([
        fetchZerodhaStatus(username).catch(() => ({
          connected: false,
          status: 'not_connected' as const,
          message: 'Not connected',
          expires_at: null,
          username,
        })),
        fetchGrowwStatus(username).catch(() => ({
          connected: false,
          status: 'not_connected',
          message: 'Not connected',
          expires_at: null,
          username,
        })),
      ])
      setZerodha(zStatus)
      setGroww(gStatus)
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
    if (searchParams.get('groww') === 'connected') {
      refreshStatus()
      searchParams.delete('groww')
      setSearchParams(searchParams, { replace: true })
    }
  }, [searchParams, setSearchParams, refreshStatus])

  useEffect(() => {
    const onDocClick = (e: MouseEvent) => {
      const target = e.target as Node
      if (assistRef.current && !assistRef.current.contains(target)) setAssistOpen(false)
      if (profileRef.current && !profileRef.current.contains(target)) setProfileOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [])

  useEffect(() => {
    setAssistOpen(false)
    setProfileOpen(false)
  }, [location.pathname])

  const handleSignOut = () => {
    logout()
    navigate('/login', { replace: true })
  }

  const openConnectModal = () => {
    setModalError('')
    setTokenInput('')
    setGrowwApiKey('')
    setGrowwApiSecret('')
    setConnectStep('pick')
    setConnectOpen(true)
  }

  const selectZerodha = async () => {
    setConnectStep('zerodha')
    setModalError('')
    setTokenInput('')
    try {
      const url = await fetchZerodhaLoginUrl()
      window.open(url, '_blank', 'noopener,noreferrer')
    } catch {
      setModalError('Could not open Zerodha login. Paste access token below if you have one.')
    }
  }

  const selectGroww = async () => {
    setConnectStep('groww')
    setModalError('')
    setTokenInput('')
    try {
      const info = await fetchGrowwLoginInfo()
      setGrowwKeysUrl(info.keys_page_url)
      window.open(info.keys_page_url, '_blank', 'noopener,noreferrer')
    } catch {
      setModalError('Open Groww Trading APIs in your browser and generate an Access Token.')
    }
  }

  const handleSaveZerodhaToken = async () => {
    setModalError('')
    if (!tokenInput.trim()) {
      setModalError('Paste your Zerodha access token')
      return
    }
    setSaving(true)
    try {
      const status = await saveZerodhaToken(username, tokenInput.trim())
      setZerodha(status)
      setConnectOpen(false)
      setConnectStep('pick')
      setTokenInput('')
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setModalError(err.response?.data?.detail || err.message || 'Invalid token')
    } finally {
      setSaving(false)
    }
  }

  const handleSaveGrowwToken = async () => {
    setModalError('')
    const token = tokenInput.trim()
    const hasCreds = growwApiKey.trim() && growwApiSecret.trim()
    const envCreds = Boolean(groww?.api_key_set && groww?.api_secret_set)

    // Key + secret (form or .env) → exchange for today's access token
    if (!token && (hasCreds || envCreds)) {
      await handleGrowwRefresh()
      return
    }

    if (!token) {
      setModalError(
        'Paste today\'s Groww access token, or set GROWW_API_KEY + GROWW_API_SECRET in .env and click Refresh token.',
      )
      return
    }
    setSaving(true)
    try {
      const status = await saveGrowwToken(username, token)
      setGroww(status)
      if (hasCreds) {
        await saveGrowwCredentials(username, growwApiKey.trim(), growwApiSecret.trim())
      }
      setConnectOpen(false)
      setConnectStep('pick')
      setTokenInput('')
      setGrowwApiKey('')
      setGrowwApiSecret('')
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setModalError(err.response?.data?.detail || err.message || 'Invalid token')
    } finally {
      setSaving(false)
    }
  }

  const handleGrowwRefresh = async () => {
    setModalError('')
    const hasCreds = growwApiKey.trim() && growwApiSecret.trim()
    const envCreds = Boolean(groww?.api_key_set && groww?.api_secret_set)
    if (!hasCreds && !envCreds) {
      setModalError(
        'Add GROWW_API_KEY and GROWW_API_SECRET to .env (restart backend), or paste them below.',
      )
      return
    }
    setSaving(true)
    try {
      if (hasCreds) {
        await saveGrowwCredentials(username, growwApiKey.trim(), growwApiSecret.trim())
      }
      const status = await refreshGrowwToken(username)
      setGroww(status)
      setConnectOpen(false)
      setConnectStep('pick')
      setTokenInput('')
    } catch (e) {
      const err = e as { response?: { data?: { detail?: string } }; message?: string }
      setModalError(err.response?.data?.detail || err.message || 'Refresh failed')
    } finally {
      setSaving(false)
    }
  }

  const openSettings = () => {
    setSettingsError('')
    setSettingsOk('')
    setNewUsername('')
    setNewPassword('')
    setNewRole('trader')
    setUsers(listUsers())
    setSettingsOpen(true)
    setProfileOpen(false)
  }

  const handleAddUser = (e: FormEvent) => {
    e.preventDefault()
    setSettingsError('')
    setSettingsOk('')
    try {
      addUser({ username: newUsername, password: newPassword, role: newRole })
      setUsers(listUsers())
      setNewUsername('')
      setNewPassword('')
      setNewRole('trader')
      setSettingsOk(`User “${newUsername.trim().toLowerCase()}” added successfully`)
    } catch (err) {
      setSettingsError((err as Error).message)
    }
  }

  const handleRemoveUser = (uname: string) => {
    setSettingsError('')
    setSettingsOk('')
    try {
      removeUser(uname)
      setUsers(listUsers())
      setSettingsOk(`Removed “${uname}”`)
    } catch (err) {
      setSettingsError((err as Error).message)
    }
  }

  const zerodhaConnected = zerodha?.connected === true
  const growwConnected = groww?.connected === true
  const connected = zerodhaConnected || growwConnected
  const connectionTitle = checking
    ? 'Checking broker connections…'
    : [
        zerodhaConnected ? 'Zerodha connected' : 'Zerodha offline',
        growwConnected ? 'Groww connected' : 'Groww offline',
      ].join(' · ')
  const assistActive = tradeAssistItems.some((item) => location.pathname.startsWith(item.to))

  return (
    <div className="app-shell">
      <header className="gw-header">
        <div className="gw-header-inner">
          <NavLink to={homePath} className="gw-logo" aria-label="TRADELE home">
            <img src="/favicon.png" alt="" className="gw-logo-img" width={34} height={34} />
            <span className="gw-logo-text">TRADELE</span>
          </NavLink>

          <nav className="gw-nav" aria-label="Primary">
            {showMyTrade && (
              <NavLink
                to="/mytrade"
                className={() =>
                  `gw-nav-link${location.pathname.startsWith('/mytrade') ? ' active' : ''}`
                }
              >
                MYTRADE
              </NavLink>
            )}
            {showInfinity && (
              <NavLink
                to="/infinity/jarvis/test"
                className={() =>
                  `gw-nav-link${location.pathname.startsWith('/infinity') ? ' active' : ''}`
                }
              >
                INFINITY
              </NavLink>
            )}
            <NavLink
              to="/watchlist"
              className={({ isActive }) => `gw-nav-link${isActive ? ' active' : ''}`}
            >
              WATCHLIST
            </NavLink>
            <NavLink
              to="/deep-agent"
              className={() =>
                `gw-nav-link${location.pathname.startsWith('/deep-agent') ? ' active' : ''}`
              }
            >
              DEEP AGENT
            </NavLink>

            <div className="gw-nav-dropdown" ref={assistRef}>
              <button
                type="button"
                className={`gw-nav-link gw-nav-trigger${assistActive || assistOpen ? ' active' : ''}`}
                aria-expanded={assistOpen}
                aria-haspopup="true"
                onClick={() => {
                  setAssistOpen((v) => !v)
                  setProfileOpen(false)
                }}
              >
                TRADE ASSIST
                <svg className="gw-chevron" width="12" height="12" viewBox="0 0 12 12" aria-hidden>
                  <path d="M2.5 4.5L6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </button>
              {assistOpen && (
                <div className="gw-dropdown-menu" role="menu">
                  {tradeAssistItems.map((item) => (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      role="menuitem"
                      className={({ isActive }) => `gw-dropdown-item${isActive ? ' active' : ''}`}
                      onClick={() => setAssistOpen(false)}
                    >
                      {item.label}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>

            <NavLink
              to="/market-news"
              className={({ isActive }) => `gw-nav-link${isActive ? ' active' : ''}`}
            >
              MARKET NEWS
            </NavLink>
            <NavLink
              to="/news-brief"
              className={({ isActive }) => `gw-nav-link${isActive ? ' active' : ''}`}
            >
              NEWS BRIEF
            </NavLink>
          </nav>

          <div className="gw-search">
            <span className="gw-search-icon" aria-hidden>
              ⌕
            </span>
            <input type="search" placeholder="Search stocks" aria-label="Search stocks" />
          </div>

          <div className="gw-header-actions">
            <div
              className={`gw-kite-status icon-only${connected ? ' is-connected' : ' is-offline'}`}
              title={connectionTitle}
              aria-label={connected ? 'Broker connected' : 'Broker not connected'}
            >
              <span className={`gw-kite-dot${connected ? ' blink' : ''}${checking ? ' checking' : ''}`} />
            </div>

            <button type="button" className="gw-connect-btn" onClick={openConnectModal}>
              Connect
            </button>

            <div className="gw-profile" ref={profileRef}>
              <button
                type="button"
                className="gw-avatar"
                aria-expanded={profileOpen}
                aria-haspopup="true"
                aria-label="Account menu"
                onClick={() => {
                  setProfileOpen((v) => !v)
                  setAssistOpen(false)
                }}
              >
                {initial}
              </button>
              {profileOpen && (
                <div className="gw-dropdown-menu gw-profile-menu" role="menu">
                  <div className="gw-profile-head">
                    <span className="gw-avatar sm">{initial}</span>
                    <div>
                      <strong>{displayName}</strong>
                      <span>@{username}</span>
                    </div>
                  </div>
                  {showMyTrade ? (
                    <button
                      type="button"
                      className="gw-dropdown-item"
                      role="menuitem"
                      onClick={() => {
                        setProfileOpen(false)
                        navigate('/mytrade')
                      }}
                    >
                      My Trade
                    </button>
                  ) : null}
                  <div className="gw-dropdown-item gw-dropdown-static" role="menuitem">
                    <span>Role</span>
                    <em className="gw-role-pill">{role}</em>
                  </div>
                  <button
                    type="button"
                    className="gw-dropdown-item"
                    role="menuitem"
                    onClick={openSettings}
                  >
                    Settings
                  </button>
                  <div className="gw-dropdown-divider" />
                  <button
                    type="button"
                    className="gw-dropdown-item danger"
                    role="menuitem"
                    onClick={handleSignOut}
                  >
                    Sign out
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="main-content">
        <Outlet />
      </main>

      {connectOpen && (
        <div className="gw-modal-backdrop" onClick={() => setConnectOpen(false)} role="presentation">
          <div
            className="gw-modal gw-modal-lg connect-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-labelledby="connect-title"
          >
            {connectStep === 'pick' && (
              <>
                <h2 id="connect-title">Connect Broker</h2>
                <p className="gw-modal-hint">
                  Choose your broker. Tokens reset daily at <strong>6 AM IST</strong>.
                </p>
                <div className="broker-picker">
                  <button type="button" className="broker-card zerodha" onClick={selectZerodha}>
                    <span className="broker-card-logo">Z</span>
                    <strong>Zerodha</strong>
                    <span>Kite Connect · login &amp; paste token</span>
                    {zerodhaConnected && <em className="broker-connected-tag">Connected</em>}
                  </button>
                  <button type="button" className="broker-card groww" onClick={selectGroww}>
                    <span className="broker-card-logo">G</span>
                    <strong>Groww</strong>
                    <span>Trading API · paste token or refresh</span>
                    {growwConnected && <em className="broker-connected-tag">Connected</em>}
                  </button>
                </div>
                {modalError && <p className="login-error">{modalError}</p>}
                <div className="gw-modal-actions">
                  <button type="button" className="btn secondary" onClick={() => setConnectOpen(false)}>
                    Cancel
                  </button>
                </div>
              </>
            )}

            {connectStep === 'zerodha' && (
              <>
                <button type="button" className="connect-back" onClick={() => setConnectStep('pick')}>
                  ← Back
                </button>
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
                    placeholder="Paste Zerodha access_token here"
                    rows={3}
                  />
                </label>
                {modalError && <p className="login-error">{modalError}</p>}
                <div className="gw-modal-actions">
                  <button type="button" className="btn secondary" onClick={() => setConnectStep('pick')}>
                    Back
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
                    onClick={handleSaveZerodhaToken}
                    disabled={saving}
                  >
                    {saving ? 'Saving…' : 'Save token'}
                  </button>
                </div>
              </>
            )}

            {connectStep === 'groww' && (
              <>
                <button type="button" className="connect-back" onClick={() => setConnectStep('pick')}>
                  ← Back
                </button>
                <h2 id="connect-title">Connect Groww</h2>
                <p className="gw-modal-hint">
                  {groww?.api_key_set && groww?.api_secret_set ? (
                    <>
                      API key + secret are loaded from <strong>.env</strong>. Click{' '}
                      <strong>Refresh token</strong> to connect (no paste needed). Tokens reset daily at 6
                      AM IST.
                    </>
                  ) : (
                    <>
                      Paste Groww <strong>API key</strong> + <strong>API secret</strong> below (or set{' '}
                      <code>GROWW_API_KEY</code> / <code>GROWW_API_SECRET</code> in <code>.env</code>) and
                      click <strong>Refresh token</strong>. Resets daily at 6 AM IST.
                    </>
                  )}
                </p>
                <label className="gw-modal-label">
                  Access token <span className="gw-optional">(optional)</span>
                  <textarea
                    value={tokenInput}
                    onChange={(e) => setTokenInput(e.target.value)}
                    placeholder="Only if you copied today's Access Token from Groww dashboard"
                    rows={3}
                  />
                </label>
                <p className="gw-modal-hint groww-refresh-hint">
                  {groww?.api_key_set && groww?.api_secret_set
                    ? 'Optional override — leave blank to use .env credentials:'
                    : 'From Groww API key dashboard — key + secret:'}
                </p>
                <div className="groww-creds-row">
                  <label className="gw-modal-label">
                    API key
                    <input
                      value={growwApiKey}
                      onChange={(e) => setGrowwApiKey(e.target.value)}
                      placeholder="Groww API key"
                      autoComplete="off"
                    />
                  </label>
                  <label className="gw-modal-label">
                    API secret
                    <input
                      type="password"
                      value={growwApiSecret}
                      onChange={(e) => setGrowwApiSecret(e.target.value)}
                      placeholder="Groww API secret"
                      autoComplete="off"
                    />
                  </label>
                </div>
                {modalError && <p className="login-error">{modalError}</p>}
                <div className="gw-modal-actions">
                  <button type="button" className="btn secondary" onClick={() => setConnectStep('pick')}>
                    Back
                  </button>
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={() => window.open(growwKeysUrl, '_blank', 'noopener,noreferrer')}
                  >
                    Open Groww API
                  </button>
                  <button
                    type="button"
                    className="btn secondary"
                    onClick={handleGrowwRefresh}
                    disabled={saving}
                  >
                    Refresh token
                  </button>
                  <button
                    type="button"
                    className="btn primary"
                    onClick={handleSaveGrowwToken}
                    disabled={saving}
                  >
                    {saving ? 'Saving…' : 'Save token'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {settingsOpen && (
        <div className="gw-modal-backdrop" onClick={() => setSettingsOpen(false)} role="presentation">
          <div
            className="gw-modal gw-modal-xl"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-labelledby="settings-title"
          >
            <div className="gw-modal-title-row">
              <div>
                <h2 id="settings-title">User Management</h2>
                <p className="gw-modal-hint" style={{ marginBottom: 0 }}>
                  Add platform users with username and password. They can sign in and use TRADELE.
                </p>
              </div>
              <button
                type="button"
                className="gw-icon-btn"
                aria-label="Close"
                onClick={() => setSettingsOpen(false)}
              >
                ✕
              </button>
            </div>

            <form className="gw-user-form" onSubmit={handleAddUser}>
              <label className="gw-modal-label">
                Username
                <input
                  value={newUsername}
                  onChange={(e) => setNewUsername(e.target.value)}
                  placeholder="e.g. trader01"
                  autoComplete="off"
                />
              </label>
              <label className="gw-modal-label">
                Password
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Min 6 characters"
                  autoComplete="new-password"
                />
              </label>
              <label className="gw-modal-label">
                Role
                <select value={newRole} onChange={(e) => setNewRole(e.target.value as UserRole)}>
                  <option value="trader">Trader</option>
                  <option value="viewer">Viewer</option>
                  <option value="admin">Admin</option>
                </select>
              </label>
              <div className="gw-user-form-actions">
                <button type="submit" className="btn primary">
                  Add user
                </button>
              </div>
            </form>

            {settingsError && <p className="admin-banner err">{settingsError}</p>}
            {settingsOk && <p className="admin-banner ok">{settingsOk}</p>}

            <div className="gw-user-table-wrap">
              <table className="gw-user-table">
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Role</th>
                    <th>Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr key={u.username}>
                      <td>
                        <strong>{u.username}</strong>
                      </td>
                      <td>
                        <em className="gw-role-pill">{u.role}</em>
                      </td>
                      <td>{new Date(u.createdAt).toLocaleDateString()}</td>
                      <td>
                        <button
                          type="button"
                          className="btn danger small"
                          disabled={u.username.toLowerCase() === 'leninstark'}
                          onClick={() => handleRemoveUser(u.username)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
