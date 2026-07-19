const AUTH_KEY = 'tradele_auth'

/** Hardcoded local credentials (replace with real auth later). */
export const DEFAULT_USERNAME = 'leninstark'
export const DEFAULT_PASSWORD = 'Iamstark@123'

export interface AuthUser {
  username: string
  name: string
}

export function getAuthUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(AUTH_KEY)
    if (!raw) return null
    const data = JSON.parse(raw) as AuthUser & { email?: string }
    // Migrate older sessions that stored email
    if (!data.username && data.email) {
      return { username: data.email, name: data.name || data.email }
    }
    return data.username ? data : null
  } catch {
    return null
  }
}

export function isAuthenticated(): boolean {
  return getAuthUser() != null
}

export function login(username: string, password: string): AuthUser {
  const user = username.trim()
  if (user !== DEFAULT_USERNAME || password !== DEFAULT_PASSWORD) {
    throw new Error('Invalid username or password')
  }
  const authUser: AuthUser = {
    username: user,
    name: user.charAt(0).toUpperCase() + user.slice(1),
  }
  localStorage.setItem(AUTH_KEY, JSON.stringify(authUser))
  return authUser
}

export function logout(): void {
  localStorage.removeItem(AUTH_KEY)
}
