import { useState, useEffect } from 'react'
import axios from 'axios'
import './App.css'

const API_BASE = '/api/v1'

function App() {
  const [results, setResults] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedResult, setSelectedResult] = useState(null)
  const [showDetailDialog, setShowDetailDialog] = useState(false)
  const [filters, setFilters] = useState({
    userType: '',
    status: '',
    keyword: ''
  })
  const [currentPage, setCurrentPage] = useState(1)
  const [itemsPerPage, setItemsPerPage] = useState(20)
  const [totalItems, setTotalItems] = useState(0)

  useEffect(() => {
    fetchData()
  }, [filters, currentPage, itemsPerPage])

  const fetchData = async () => {
    try {
      setLoading(true)
      const params = new URLSearchParams()
      if (filters.userType) params.append('user_type', filters.userType)
      if (filters.status) params.append('status', filters.status)
      if (filters.keyword) params.append('keyword', filters.keyword)
      params.append('skip', (currentPage - 1) * itemsPerPage)
      params.append('limit', itemsPerPage)

      const [resultsRes, statsRes] = await Promise.all([
        axios.get(`${API_BASE}/results/?${params}`),
        axios.get(`${API_BASE}/dashboard/stats`)
      ])

      setResults(resultsRes.data.items)
      setTotalItems(resultsRes.data.total)
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

  const openDetailDialog = (result) => {
    setSelectedResult(result)
    setShowDetailDialog(true)
  }

  const closeDetailDialog = () => {
    setShowDetailDialog(false)
    setSelectedResult(null)
  }

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text)
    alert('Copied to clipboard!')
  }

  const totalPages = Math.ceil(totalItems / itemsPerPage)

  const goToPage = (page) => {
    if (page >= 1 && page <= totalPages) {
      setCurrentPage(page)
    }
  }

  const handleItemsPerPageChange = (newItemsPerPage) => {
    setItemsPerPage(newItemsPerPage)
    setCurrentPage(1) // Reset to first page when changing items per page
  }

  const getPageNumbers = () => {
    const pages = []
    const maxPagesToShow = 5
    
    if (totalPages <= maxPagesToShow) {
      for (let i = 1; i <= totalPages; i++) {
        pages.push(i)
      }
    } else {
      if (currentPage <= 3) {
        for (let i = 1; i <= 4; i++) pages.push(i)
        pages.push('...')
        pages.push(totalPages)
      } else if (currentPage >= totalPages - 2) {
        pages.push(1)
        pages.push('...')
        for (let i = totalPages - 3; i <= totalPages; i++) pages.push(i)
      } else {
        pages.push(1)
        pages.push('...')
        for (let i = currentPage - 1; i <= currentPage + 1; i++) pages.push(i)
        pages.push('...')
        pages.push(totalPages)
      }
    }
    
    return pages
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
            <h3>Not Analyzed</h3>
            <div className="value">{stats.not_analyzed || 0}</div>
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
          onChange={(e) => {
            setFilters({...filters, userType: e.target.value})
            setCurrentPage(1)
          }}
        >
          <option value="">All Types</option>
          <option value="customer">Customers</option>
          <option value="tutor">Tutors</option>
          <option value="unknown">Unknown</option>
        </select>

        <select 
          value={filters.status} 
          onChange={(e) => {
            setFilters({...filters, status: e.target.value})
            setCurrentPage(1)
          }}
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
          onChange={(e) => {
            setFilters({...filters, keyword: e.target.value})
            setCurrentPage(1)
          }}
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
              <tr 
                key={result.id}
                onClick={() => openDetailDialog(result)}
                style={{cursor: 'pointer'}}
                className="table-row-hover"
              >
                <td>
                  <a 
                    href={result.profile_url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    onClick={(e) => e.stopPropagation()}
                  >
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
                <td>{result.location || 'N/A'}</td>
                <td>{result.search_keyword}</td>
                <td onClick={(e) => e.stopPropagation()}>
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
                  {result.post_content?.substring(0, 100) || 'N/A'}...
                </td>
                <td onClick={(e) => e.stopPropagation()}>
                  {result.post_url ? (
                    <a 
                      href={result.post_url} 
                      target="_blank" 
                      rel="noopener noreferrer"
                      className="btn-link"
                    >
                      View Post
                    </a>
                  ) : (
                    <span style={{color: '#999'}}>No URL</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination Controls */}
      <div className="pagination-container">
        <div className="pagination-info">
          Showing {results.length > 0 ? (currentPage - 1) * itemsPerPage + 1 : 0} to {Math.min(currentPage * itemsPerPage, totalItems)} of {totalItems} results
        </div>
        
        <div className="pagination-controls">
          <button 
            className="pagination-btn" 
            onClick={() => goToPage(1)}
            disabled={currentPage === 1}
          >
            ««
          </button>
          <button 
            className="pagination-btn" 
            onClick={() => goToPage(currentPage - 1)}
            disabled={currentPage === 1}
          >
            ‹
          </button>
          
          {getPageNumbers().map((page, index) => (
            page === '...' ? (
              <span key={`ellipsis-${index}`} className="pagination-ellipsis">...</span>
            ) : (
              <button
                key={page}
                className={`pagination-btn ${currentPage === page ? 'active' : ''}`}
                onClick={() => goToPage(page)}
              >
                {page}
              </button>
            )
          ))}
          
          <button 
            className="pagination-btn" 
            onClick={() => goToPage(currentPage + 1)}
            disabled={currentPage === totalPages}
          >
            ›
          </button>
          <button 
            className="pagination-btn" 
            onClick={() => goToPage(totalPages)}
            disabled={currentPage === totalPages}
          >
            »»
          </button>
        </div>

        <div className="items-per-page">
          <label>Items per page:</label>
          <select 
            value={itemsPerPage} 
            onChange={(e) => handleItemsPerPageChange(Number(e.target.value))}
          >
            <option value={10}>10</option>
            <option value={20}>20</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </div>
      </div>

      {/* Detail Dialog */}
      {showDetailDialog && selectedResult && (
        <div className="dialog-overlay" onClick={closeDetailDialog}>
          <div className="dialog-content" onClick={(e) => e.stopPropagation()}>
            <div className="dialog-header">
              <h2>Lead Details</h2>
              <button className="close-btn" onClick={closeDetailDialog}>×</button>
            </div>
            
            <div className="dialog-body">
              <div className="detail-section">
                <h3>Basic Information</h3>
                <div className="detail-grid">
                  <div className="detail-item">
                    <label>Name:</label>
                    <span>{selectedResult.name || 'N/A'}</span>
                  </div>
                  <div className="detail-item">
                    <label>User Type:</label>
                    <span className={`badge badge-${selectedResult.user_type || 'unknown'}`}>
                      {selectedResult.user_type || 'N/A'}
                    </span>
                  </div>
                  <div className="detail-item">
                    <label>Confidence Score:</label>
                    <span>
                      {selectedResult.confidence_score 
                        ? `${(selectedResult.confidence_score * 100).toFixed(1)}%` 
                        : 'N/A'}
                    </span>
                  </div>
                  <div className="detail-item">
                    <label>Location:</label>
                    <span>{selectedResult.location || 'N/A'}</span>
                  </div>
                  <div className="detail-item">
                    <label>Status:</label>
                    <span className={`badge badge-${selectedResult.status}`}>
                      {selectedResult.status}
                    </span>
                  </div>
                  <div className="detail-item">
                    <label>Search Keyword:</label>
                    <span>{selectedResult.search_keyword || 'N/A'}</span>
                  </div>
                  <div className="detail-item">
                    <label>Source:</label>
                    <span>{selectedResult.source || 'N/A'}</span>
                  </div>
                  <div className="detail-item">
                    <label>Scraped At:</label>
                    <span>{new Date(selectedResult.scraped_at).toLocaleString()}</span>
                  </div>
                  {selectedResult.analyzed_at && (
                    <div className="detail-item">
                      <label>Analyzed At:</label>
                      <span>{new Date(selectedResult.analyzed_at).toLocaleString()}</span>
                    </div>
                  )}
                </div>
              </div>

              <div className="detail-section">
                <h3>Links</h3>
                <div className="detail-grid">
                  <div className="detail-item full-width">
                    <label>Profile URL:</label>
                    <div className="link-actions">
                      {selectedResult.profile_url ? (
                        <>
                          <a href={selectedResult.profile_url} target="_blank" rel="noopener noreferrer">
                            {selectedResult.profile_url}
                          </a>
                          <button 
                            className="btn-copy" 
                            onClick={() => copyToClipboard(selectedResult.profile_url)}
                          >
                            Copy
                          </button>
                        </>
                      ) : (
                        <span>N/A</span>
                      )}
                    </div>
                  </div>
                  <div className="detail-item full-width">
                    <label>Post URL:</label>
                    <div className="link-actions">
                      {selectedResult.post_url ? (
                        <>
                          <a href={selectedResult.post_url} target="_blank" rel="noopener noreferrer">
                            {selectedResult.post_url}
                          </a>
                          <button 
                            className="btn-copy" 
                            onClick={() => copyToClipboard(selectedResult.post_url)}
                          >
                            Copy
                          </button>
                        </>
                      ) : (
                        <span>N/A</span>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              <div className="detail-section">
                <h3>Post Content</h3>
                <div className="post-content-box">
                  {selectedResult.post_content || 'N/A'}
                </div>
              </div>

              {selectedResult.gemini_analysis && (
                <div className="detail-section">
                  <h3>AI Analysis</h3>
                  <pre className="analysis-box">
                    {JSON.stringify(selectedResult.gemini_analysis, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            <div className="dialog-footer">
              <button className="btn-secondary" onClick={closeDetailDialog}>Close</button>
              <button 
                className="btn-primary" 
                onClick={() => {
                  updateStatus(selectedResult.id, 'contacted')
                  closeDetailDialog()
                }}
              >
                Mark as Contacted
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
