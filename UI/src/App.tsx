import { BrowserRouter, Navigate, Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAuth from './components/RequireAuth'
import RequireMyTrade from './components/RequireMyTrade'
import RequireInfinity from './components/RequireInfinity'
import MyTradeShell from './pages/MyTradeShell'
import InfinityShell from './pages/InfinityShell'
import Explore from './pages/Explore'
import Watchlist from './pages/Watchlist'
import TradingStylePage from './pages/TradingStylePage'
import Swing from './pages/Swing'
import Fno from './pages/Fno'
import MarketNews from './pages/MarketNews'
import NewsBrief from './pages/NewsBrief'
import Login from './pages/Login'
import Admin from './pages/Admin'
import { canAccessMyTrade, getAuthUser, homePathForUser } from './auth'
import './App.css'

function HomeRedirect() {
  return <Navigate to={homePathForUser(getAuthUser()?.username)} replace />
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route element={<RequireAuth />}>
          <Route element={<Layout />}>
            <Route path="/" element={<HomeRedirect />} />
            <Route element={<RequireMyTrade />}>
              <Route path="/mytrade/*" element={<MyTradeShell />} />
            </Route>
            <Route element={<RequireInfinity />}>
              <Route path="/infinity/*" element={<InfinityShell />} />
            </Route>
            <Route path="/deep-agent" element={<Explore />} />
            <Route path="/explore" element={<Navigate to="/deep-agent" replace />} />
            <Route path="/mytrade/research" element={<Navigate to="/deep-agent" replace />} />
            <Route path="/watchlist" element={<Watchlist />} />
            <Route path="/intraday" element={<TradingStylePage style="intraday" />} />
            <Route path="/swing" element={<Swing />} />
            <Route path="/fno" element={<Fno />} />
            <Route path="/positional" element={<Navigate to="/fno" replace />} />
            <Route path="/investment" element={<Navigate to="/fno" replace />} />
            <Route path="/investments" element={<Navigate to="/fno" replace />} />
            <Route path="/market-news" element={<MarketNews />} />
            <Route path="/news-brief" element={<NewsBrief />} />
            <Route path="/admin" element={<Admin />} />
            <Route path="/scanners" element={<Navigate to="/swing" replace />} />
            <Route path="/momentum" element={<Navigate to="/swing" replace />} />
            <Route path="/alerts" element={<Navigate to="/intraday" replace />} />
          </Route>
        </Route>

        <Route
          path="*"
          element={
            <Navigate
              to={canAccessMyTrade(getAuthUser()?.username) ? '/mytrade' : '/swing'}
              replace
            />
          }
        />
      </Routes>
    </BrowserRouter>
  )
}
