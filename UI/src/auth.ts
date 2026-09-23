const AUTH_KEY = 'tradele_auth'
const USERS_KEY = 'tradele_users'

export const DEFAULT_USERNAME = 'leninstark'
export const DEFAULT_PASSWORD = 'Iamstark@123'

export type UserRole = 'admin' | 'trader' | 'viewer'

export interface PlatformUser {
  username: string
  password: string
  role: UserRole
  name: string
  createdAt: string
}

export interface AuthUser {
  username: string
  name: string
  role: UserRole
}

function seedUsers(): PlatformUser[] {
  return [
    {
      username: DEFAULT_USERNAME,
      password: DEFAULT_PASSWORD,
      role: 'admin',
      name: 'Leninstark',
      createdAt: new Date().toISOString(),
    },
  ]
}

export function listUsers(): PlatformUser[] {
  try {
    const raw = localStorage.getItem(USERS_KEY)
    if (!raw) {
      const seeded = seedUsers()
      localStorage.setItem(USERS_KEY, JSON.stringify(seeded))
      return seeded
    }
    const users = JSON.parse(raw) as PlatformUser[]
    if (!Array.isArray(users) || users.length === 0) {
      const seeded = seedUsers()
      localStorage.setItem(USERS_KEY, JSON.stringify(seeded))
      return seeded
    }
    return users
  } catch {
    const seeded = seedUsers()
    localStorage.setItem(USERS_KEY, JSON.stringify(seeded))
    return seeded
  }
}

function saveUsers(users: PlatformUser[]) {
  localStorage.setItem(USERS_KEY, JSON.stringify(users))
}

export function addUser(input: {
  username: string
  password: string
  role?: UserRole
}): PlatformUser {
  const username = input.username.trim().toLowerCase()
  const password = input.password
  if (!username || username.length < 3) {
    throw new Error('Username must be at least 3 characters')
  }
  if (!password || password.length < 6) {
    throw new Error('Password must be at least 6 characters')
  }
  const users = listUsers()
  if (users.some((u) => u.username.toLowerCase() === username)) {
    throw new Error('Username already exists')
  }
  const user: PlatformUser = {
    username,
    password,
    role: input.role || 'trader',
    name: username.charAt(0).toUpperCase() + username.slice(1),
    createdAt: new Date().toISOString(),
  }
  saveUsers([...users, user])
  return user
}

export function removeUser(username: string): void {
  if (username.toLowerCase() === DEFAULT_USERNAME) {
    throw new Error('Cannot remove the primary admin account')
  }
  const users = listUsers().filter((u) => u.username.toLowerCase() !== username.toLowerCase())
  saveUsers(users)
}

export function getAuthUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(AUTH_KEY)
    if (!raw) return null
    const data = JSON.parse(raw) as AuthUser & { email?: string }
    if (!data.username && data.email) {
      return {
        username: data.email,
        name: data.name || data.email,
        role: 'trader',
      }
    }
    if (!data.username) return null
    return {
      username: data.username,
      name: data.name || data.username,
      role: data.role || 'admin',
    }
  } catch {
    return null
  }
}

export function isAuthenticated(): boolean {
  return getAuthUser() != null
}

export function login(username: string, password: string): AuthUser {
  const user = username.trim().toLowerCase()
  const users = listUsers()
  const match = users.find((u) => u.username.toLowerCase() === user && u.password === password)
  if (!match) {
    throw new Error('Invalid username or password')
  }
  const authUser: AuthUser = {
    username: match.username,
    name: match.name,
    role: match.role,
  }
  localStorage.setItem(AUTH_KEY, JSON.stringify(authUser))
  return authUser
}

export function logout(): void {
  localStorage.removeItem(AUTH_KEY)
}

/** MyTrade (personal P&L) is restricted to the primary admin account only. */
export function canAccessMyTrade(username?: string | null): boolean {
  const u = (username ?? getAuthUser()?.username ?? '').trim().toLowerCase()
  return u === DEFAULT_USERNAME.toLowerCase()
}

/** INFINITY (JARVIS / FRIDAY) is restricted to the primary admin account only. */
export function canAccessInfinity(username?: string | null): boolean {
  return canAccessMyTrade(username)
}

/** Default landing path after login / home. */
export function homePathForUser(username?: string | null): string {
  return canAccessMyTrade(username) ? '/mytrade' : '/swing'
}
