import { useCallback, useState } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import MyTradeLayout from '../components/MyTradeLayout'
import { fetchMyTradeStatus, refreshGrowwToken, refreshMyTrade } from '../api/client'
import { getAuthUser } from '../auth'
import MyTradeDashboard from './MyTradeDashboard'
import PLCalendar from './PLCalendar'
import Journal from './Journal'

export default function MyTradeShell() {
  const user = getAuthUser()
  const username = user?.username || 'leninstark'
  const [refreshing, setRefreshing] = useState(false)
  const [refreshError, setRefreshError] = useState('')
  const [refreshNote, setRefreshNote] = useState('')
  const [refreshTick, setRefreshTick] = useState(0)

  const handleRefresh = useCallback(async () => {
    setRefreshing(true)
    setRefreshError('')
    setRefreshNote('')
    try {
      let status = await fetchMyTradeStatus(username)
      if (!status.groww_connected) {
        // Use GROWW_API_KEY / GROWW_API_SECRET from .env (or saved creds) automatically
        try {
          await refreshGrowwToken(username)
          status = await fetchMyTradeStatus(username)
        } catch (e: unknown) {
          const detail =
            typeof e === 'object' && e && 'response' in e
              ? String(
                  (e as { response?: { data?: { detail?: string } } }).response?.data?.detail || '',
                )
              : ''
          setRefreshError(
            detail ||
              'Could not connect Groww. Set GROWW_API_KEY + GROWW_API_SECRET in .env, restart backend, then retry.',
          )
          return
        }
        if (!status.groww_connected) {
          setRefreshError('Connect Groww first using the Connect button in the header.')
          return
        }
        setRefreshNote('Groww connected via API key/secret. Syncing…')
      }
      const result = await refreshMyTrade(username)
      if (result.note) setRefreshNote(result.note)
      setRefreshTick((t) => t + 1)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Sync failed'
      setRefreshError(typeof e === 'object' && e && 'response' in e
        ? String((e as { response?: { data?: { detail?: string } } }).response?.data?.detail || msg)
        : msg)
    } finally {
      setRefreshing(false)
    }
  }, [username])

  return (
    <Routes>
      <Route element={<MyTradeLayout onRefresh={handleRefresh} refreshing={refreshing} />}>
        <Route index element={<Navigate to="dashboard" replace />} />
        <Route
          path="dashboard"
          element={
            <MyTradeDashboard
              refreshTick={refreshTick}
              refreshError={refreshError}
              refreshNote={refreshNote}
              refreshing={refreshing}
            />
          }
        />
        <Route
          path="calendar"
          element={
            <PLCalendar
              refreshTick={refreshTick}
              refreshError={refreshError}
              refreshNote={refreshNote}
            />
          }
        />
        <Route
          path="journal"
          element={
            <Journal
              refreshTick={refreshTick}
              refreshError={refreshError}
              refreshNote={refreshNote}
            />
          }
        />
      </Route>
    </Routes>
  )
}
