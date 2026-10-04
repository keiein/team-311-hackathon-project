import { Navigate, Route, Routes } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Dashboard from './pages/Dashboard'
import Requests from './pages/Requests'
import Dispatch from './pages/Dispatch'
import Crews from './pages/Crews'
import Reports from './pages/Reports'

function App() {
  return (
    <div className="flex h-full w-full bg-white">
      <Sidebar />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Routes>
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/requests" element={<Requests />} />
          <Route path="/dispatch" element={<Dispatch />} />
          <Route path="/crews" element={<Crews />} />
          <Route path="/reports" element={<Reports />} />
        </Routes>
      </main>
    </div>
  )
}

export default App
