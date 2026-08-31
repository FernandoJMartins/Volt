import { StrictMode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'

import './styles.css'
import { api } from './api/client'
import Layout from './components/Layout'
import { Loading } from './components/ui'
import Accounts from './pages/Accounts'
import Analytics from './pages/Analytics'
import Compose from './pages/Compose'
import Dashboard from './pages/Dashboard'
import Inbox from './pages/Inbox'
import Login from './pages/Login'
import Monitoring from './pages/Monitoring'
import MyTexts from './pages/MyTexts'
import Queue from './pages/Queue'
import Settings from './pages/Settings'

function Protected({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<'loading' | 'in' | 'out'>('loading')

  useEffect(() => {
    api
      .me()
      .then(() => setState('in'))
      .catch(() => setState('out'))
  }, [])

  if (state === 'loading') return <Loading />
  if (state === 'out') return <Navigate to="/login" replace />
  return <>{children}</>
}

function App() {
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', localStorage.getItem('theme') ?? 'dark')
  }, [])

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <Protected>
              <Layout />
            </Protected>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/texts" element={<MyTexts />} />
          <Route path="/monitoring" element={<Monitoring />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/compose" element={<Compose />} />
          <Route path="/compose/:postId" element={<Compose />} />
          <Route path="/queue" element={<Queue />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/accounts" element={<Accounts />} />
          <Route path="/settings" element={<Settings />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
