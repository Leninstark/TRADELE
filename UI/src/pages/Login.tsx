import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { getAuthUser, homePathForUser, isAuthenticated, login } from '../auth'

export default function Login() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')

  if (isAuthenticated()) {
    return <Navigate to={homePathForUser(getAuthUser()?.username)} replace />
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    setError('')
    if (!username.trim() || !password.trim()) {
      setError('Enter username and password')
      return
    }
    try {
      const user = login(username, password)
      navigate(homePathForUser(user.username), { replace: true })
    } catch {
      setError('Invalid username or password')
    }
  }

  return (
    <div className="login-page">
      <form className="login-bar" onSubmit={handleSubmit}>
        <input
          type="text"
          autoComplete="username"
          placeholder="Username"
          aria-label="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
        <input
          type="password"
          autoComplete="current-password"
          placeholder="Password"
          aria-label="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit" className="login-icon-btn" aria-label="Sign in" title="Sign in">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M10 17l5-5-5-5"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            <path
              d="M15 12H3"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
            />
            <path
              d="M21 3v18"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
            />
          </svg>
        </button>
        {error && <p className="login-error">{error}</p>}
      </form>
    </div>
  )
}
