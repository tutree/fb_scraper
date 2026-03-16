import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [token, setToken] = useState(localStorage.getItem('token'));
  const [role, setRole] = useState(localStorage.getItem('role') || 'user');

  useEffect(() => {
    if (token) {
      localStorage.setItem('token', token);
    } else {
      localStorage.removeItem('token');
      localStorage.removeItem('role');
      setRole('user');
    }
  }, [token]);

  useEffect(() => {
    if (role) localStorage.setItem('role', role);
  }, [role]);

  const login = (newToken, userRole) => {
    setToken(newToken);
    setRole(userRole || 'user');
  };

  const logout = () => {
    setToken(null);
  };

  const value = {
    token,
    role,
    login,
    logout,
    isAuthenticated: !!token,
    isAdmin: role === 'admin',
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
