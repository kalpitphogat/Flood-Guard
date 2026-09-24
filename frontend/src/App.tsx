import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import Home from './pages/Home'
import Simulation from './pages/Simulation'
import RealtimeMonitoring from './pages/RealtimeMonitoring'
import About from './pages/About'
import ShareRedirect from './pages/ShareRedirect'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/simulation" element={<Simulation />} />
        <Route path="/monitoring" element={<RealtimeMonitoring />} />
        <Route path="/about" element={<About />} />
        <Route path="/s/:code" element={<ShareRedirect />} />
      </Routes>
    </Layout>
  )
}
