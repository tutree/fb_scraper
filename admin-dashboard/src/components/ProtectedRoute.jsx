import { Navigate, Outlet } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { Link } from 'react-router-dom';

export default function ProtectedRoute() {
  const { isAuthenticated, isAdmin, role, logout } = useAuth();
  
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200">
        <div className="mx-auto max-w-[1400px] px-4 py-4 flex items-center justify-between">
          <div className="flex items-center gap-6">
            <h1 className="text-xl font-bold text-slate-900">FB Scraper</h1>
            <nav className="hidden md:flex gap-4">
              <Link to="/" className="text-sm font-medium text-slate-700 hover:text-slate-900">Leads</Link>
              <Link to="/comments" className="text-sm font-medium text-slate-700 hover:text-slate-900">Comments</Link>
              {isAdmin && <Link to="/scraper" className="text-sm font-medium text-slate-700 hover:text-slate-900">Scraper</Link>}
              {isAdmin && <Link to="/jobs" className="text-sm font-medium text-slate-700 hover:text-slate-900">Jobs</Link>}
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${isAdmin ? 'bg-amber-100 text-amber-800' : 'bg-slate-100 text-slate-600'}`}>{role}</span>
            <Link to="/settings" className="text-sm font-medium text-slate-600 hover:text-slate-900">Settings</Link>
            <button 
              onClick={logout}
              className="text-sm font-medium text-rose-600 hover:text-rose-700"
            >
              Logout
            </button>
          </div>
        </div>
      </header>
      <main className="p-4 md:p-6">
        <Outlet />
      </main>
    </div>
  );
}
