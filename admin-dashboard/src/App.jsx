import { useState, useEffect } from 'react'
import axios from 'axios'

const API_BASE = '/api/v1'

function App() {
  const [results, setResults] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filters, setFilters] = useState({
    userType: '',
    status: '',
    keyword: ''
  })

  useEffect(() => {
    fetchData()
  }, [filters])

  const fetchData = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      if (filters.userType) params.append('user_type', filters.userType)
      if (filters.status) params.append('status', filters.status)
      if (filters.keyword) params.append('keyword', filters.keyword)

      const [resultsRes, statsRes] = await Promise.all([
        axios.get(`${API_BASE}/results?${params}`),
        axios.get(`${API_BASE}/dashboard/stats`)
      ])

      setResults(resultsRes.data.items)
      setStats(statsRes.data)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const updateStatus = async (id, newStatus) => {
    try {
      await axios.patch(`${API_BASE}/results/${id}`, { status: newStatus })
      fetchData()
    } catch (err) {
      alert('Failed to update status: ' + err.message)
    }
  }

  if (loading && !stats) return <div className="loading">Loading...</div>
  if (error) return <div className="error">Error: {error}</div>

  return (
    <div className="container">
      <div className="header">
        <h1>Facebook Scraper Dashboard</h1>
        <p>Manage and analyze scraped leads</p>
      </div>

      {stats && (
        <div className="stats-grid">
          <div className="stat-card">
            <h3>Total Leads</h3>
            <div className="value">{stats.total}</div>
          </div>
          <div className="stat-card">
            <h3>Customers</h3>
            <div className="value">{stats.customers}</div>
          </div>
          <div className="stat-card">
            <h3>Tutors</h3>
            <div className="value">{stats.tutors}</div>
          </div>
          <div className="stat-card">
            <h3>Pending</h3>
            <div className="value">{stats.pending}</div>
          </div>
          <div className="stat-card">
            <h3>Contacted</h3>
            <div className="value">{stats.contacted}</div>
          </div>
        </div>
      )}

      <div className="filters">
        <select 
          value={filters.userType} 
          onChange={(e) => setFilters({...filters, userType: e.target.value})}
        >
          <option value="">All Types</option>
          <option value="customer">Customers</option>
          <option value="tutor">Tutors</option>
          <option value="unknown">Unknown</option>
        </select>

        <select 
          value={filters.status} 
          onChange={(e) => setFilters({...filters, status: e.target.value})}
        >
          <option value="">All Status</option>
          <option value="pending">Pending</option>
          <option value="contacted">Contacted</option>
          <option value="not_interested">Not Interested</option>
          <option value="invalid">Invalid</option>
        </select>

        <input 
          type="text"
          placeholder="Search keyword..."
          value={filters.keyword}
          onChange={(e) => setFilters({...filters, keyword: e.target.value})}
        />
      </div>

      <div className="table-container">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Type</th>
              <th>Confidence</th>
              <th>Location</th>
              <th>Keyword</th>
              <th>Status</th>
              <th>Post Content</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {results.map((result) => (
              <tr key={result.id}>
                <td>
                  <a href={result.profile_url} target="_blank" rel="noopener noreferrer">
                    {result.name}
                  </a>
                </td>
                <td>
                  <span className={`badge badge-${result.user_type || 'unknown'}`}>
                    {result.user_type || 'unknown'}
                  </span>
                </td>
                <td>
                  <span className="confidence">
                    {result.confidence_score ? `${(result.confidence_score * 100).toFixed(0)}%` : '-'}
                  </span>
                </td>
                <td>{result.location || '-'}</td>
                <td>{result.search_keyword}</td>
                <td>
                  <select 
                    value={result.status}
                    onChange={(e) => updateStatus(result.id, e.target.value)}
                    className={`badge badge-${result.status}`}
                  >
                    <option value="pending">Pending</option>
                    <option value="contacted">Contacted</option>
                    <option value="not_interested">Not Interested</option>
                    <option value="invalid">Invalid</option>
                  </select>
                </td>
                <td style={{maxWidth: '300px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap'}}>
                  {result.post_content?.substring(0, 100)}...
                </td>
                <td>
                  <a href={result.post_url} target="_blank" rel="noopener noreferrer">
                    View Post
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default App
