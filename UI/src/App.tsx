import { BrowserRouter, Navigate, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAuth from './components/RequireAuth'
import Explore from './pages/Explore'
import Watchlist from './pages/Watchlist'
import TradingStylePage from './pages/TradingStylePage'
import Swing from './pages/Swing'
import Investments from './pages/Investments'
import Login from './pages/Login'
import Admin from './pages/Admin'
import './App.css'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/explore" replace />} />
            <Route path="/explore" element={<Explore />} />
            <Route path="/watchlist" element={<Watchlist />} />
            <Route path="/intraday" element={<TradingStylePage style="intraday" />} />
            <Route path="/swing" element={<Swing />} />
            <Route path="/investment" element={<Investments />} />
            <Route path="/investments" element={<Navigate to="/investment" replace />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/positional" element={<Navigate to="/swing" replace />} />
            <Route path="/scanners" element={<Navigate to="/swing" replace />} />
            <Route path="/momentum" element={<Navigate to="/swing" replace />} />
            <Route path="/alerts" element={<Navigate to="/intraday" replace />} />
          </Route>
        </Route>

        <Route path="*" element={<Navigate to="/explore" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
