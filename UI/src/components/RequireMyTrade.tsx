import { Navigate, Outlet } from 'react-router-dom'
import { canAccessMyTrade, getAuthUser, homePathForUser } from '../auth'

/** Blocks MyTrade routes for anyone except the primary admin (leninstark). */
export default function RequireMyTrade() {
  const user = getAuthUser()
  if (!canAccessMyTrade(user?.username)) {
    return <Navigate to={homePathForUser(user?.username)} replace />
  }
  return <Outlet />
}
