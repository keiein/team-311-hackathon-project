import { Navigate, Route, Routes } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import MapPage from './pages/Map'
import Requests from './pages/Requests'
import Dispatch from './pages/Dispatch'
import Crews from './pages/Crews'
import Phone from './pages/Phone'
import { SimulationProvider } from './simulation/SimulationContext'

function AppLayout() {
  return (
    <SimulationProvider>
      <div className="flex h-full w-full bg-white">
        <Sidebar />
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <Routes>
            <Route path="/" element={<Navigate to="/map" replace />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/dashboard" element={<Navigate to="/map" replace />} />
            <Route path="/requests" element={<Requests />} />
            <Route path="/dispatch" element={<Dispatch />} />
            <Route path="/crews" element={<Crews />} />
          </Routes>
        </main>
      </div>
    </SimulationProvider>
  )
}

function App() {
  return (
    <Routes>
      {/* The resident's phone is its own full-screen page, without the ops sidebar */}
      <Route path="/phone" element={<Phone />} />
      <Route path="*" element={<AppLayout />} />
    </Routes>
  )
}

export default App
