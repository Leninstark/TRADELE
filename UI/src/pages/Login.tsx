import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { DEFAULT_PASSWORD, DEFAULT_USERNAME, isAuthenticated, login } from '../auth'

export default function Login() {
  const navigate = useNavigate()
  const [username, setUsername] = useState(DEFAULT_USERNAME)
  const [password, setPassword] = useState(DEFAULT_PASSWORD)
  const [error, setError] = useState('')

  if (isAuthenticated()) {
    return <Navigate to="/explore" replace />
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password.trim()) {
      setError('Enter username and password')
      return
    }
    try {
      login(username, password)
      navigate('/explore', { replace: true })
    } catch {
      setError('Invalid username or password')
    }
  }

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <span className="gw-logo-mark">T</span>
          <h1>TRADELE</h1>
          <p>Sign in to continue</p>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <label>
            Username
            <input
              type="text"
              autoComplete="username"
              placeholder="Username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </label>
          <label>
            Password
            <input
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          {error && <p className="login-error">{error}</p>}
          <button type="submit" className="btn primary login-submit">
            Sign in
          </button>
        </form>
      </div>
    </div>
  )
}
