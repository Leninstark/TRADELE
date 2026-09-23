import { Navigate, Route, Routes } from 'react-router-dom'
import InfinityLayout from '../components/InfinityLayout'
import JarvisLayout from '../components/JarvisLayout'
import JarvisDesk from './JarvisDesk'
import FridayDesk from './FridayDesk'
import JarvisTestLab from './JarvisTestLab'

export default function InfinityShell() {
  return (
    <Routes>
      <Route element={<InfinityLayout />}>
        <Route index element={<Navigate to="jarvis/test" replace />} />
        <Route path="jarvis" element={<JarvisLayout />}>
          <Route index element={<Navigate to="test" replace />} />
          <Route path="test" element={<JarvisTestLab />} />
          <Route path="agent" element={<JarvisDesk />} />
        </Route>
        <Route path="friday" element={<FridayDesk />} />
        <Route path="test" element={<Navigate to="/infinity/jarvis/test" replace />} />
      </Route>
    </Routes>
  )
}
