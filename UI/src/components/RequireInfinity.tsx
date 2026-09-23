import { Navigate, Outlet } from 'react-router-dom'
import { canAccessInfinity, getAuthUser, homePathForUser } from '../auth'

/** Blocks INFINITY (JARVIS / FRIDAY) for anyone except leninstark. */
export default function RequireInfinity() {
  const user = getAuthUser()
  if (!canAccessInfinity(user?.username)) {
    return <Navigate to={homePathForUser(user?.username)} replace />
  }
  return <Outlet />
}
