import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import App from './App.jsx'
import CommentsPage from './pages/CommentsPage.jsx'
import ScraperPage from './pages/ScraperPage.jsx'
import JobsPage from './pages/JobsPage.jsx'
import Login from './pages/Login.jsx'
import Settings from './pages/Settings.jsx'
import ProtectedRoute from './components/ProtectedRoute.jsx'
import { AuthProvider, useAuth } from './contexts/AuthContext.jsx'
import { Toaster } from 'sonner'
import './index.css'

function AdminRoute({ children }) {
  const { isAdmin } = useAuth()
  if (!isAdmin) return <Navigate to="/" replace />
  return children
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <Toaster richColors closeButton position="top-right" />
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<ProtectedRoute />}>
            <Route path="/" element={<App />} />
            <Route path="/comments" element={<CommentsPage />} />
            <Route path="/scraper" element={<AdminRoute><ScraperPage /></AdminRoute>} />
            <Route path="/jobs" element={<AdminRoute><JobsPage /></AdminRoute>} />
            <Route path="/settings" element={<Settings />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
