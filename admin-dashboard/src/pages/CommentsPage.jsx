import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import axios from 'axios'
import './CommentsPage.css'

const API_BASE = '/api/v1'

export default function CommentsPage() {
  const [comments, setComments] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [perPage, setPerPage] = useState(20)
  const [userTypeFilter, setUserTypeFilter] = useState('')

  useEffect(() => {
    fetchComments()
  }, [page, perPage, userTypeFilter])

  const fetchComments = async () => {
    setLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.append('skip', (page - 1) * perPage)
      params.append('limit', perPage)
      if (userTypeFilter) params.append('user_type', userTypeFilter)
      const res = await axios.get(`${API_BASE}/comments?${params}`)
      setComments(Array.isArray(res.data?.items) ? res.data.items : [])
      setTotal(res.data?.total ?? 0)
    } catch (err) {
      setError(err.response?.data?.detail ?? err.message ?? 'Failed to load comments')
      setComments([])
    } finally {
      setLoading(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / perPage))

  return (
    <div className="comments-page">
      <header className="comments-header">
        <h1>Comments</h1>
        <p>All scraped comments with scores and analysis</p>
        <nav className="comments-nav">
          <Link to="/" className="nav-link">Back to Leads</Link>
        </nav>
      </header>

      <div className="comments-filters">
        <label>
          User type:
          <select value={userTypeFilter} onChange={(e) => { setUserTypeFilter(e.target.value); setPage(1) }}>
            <option value="">All</option>
            <option value="customer">Customer</option>
            <option value="tutor">Tutor</option>
            <option value="unknown">Unknown</option>
          </select>
        </label>
        <label>
          Per page:
          <select value={perPage} onChange={(e) => { setPerPage(Number(e.target.value)); setPage(1) }}>
            <option value={10}>10</option>
            <option value={20}>20</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </label>
      </div>

      {error && <p className="comments-page-error">{error}</p>}
      {loading && <p className="comments-loading">Loading...</p>}

      {!loading && !error && (
        <div className="comments-table-wrap">
          <table className="comments-table">
            <thead>
              <tr>
                <th>Author</th>
                <th>Comment</th>
                <th>Type</th>
                <th>Score</th>
                <th>Analysis</th>
                <th>Time</th>
              </tr>
            </thead>
            <tbody>
              {comments.length === 0 ? (
                <tr><td colSpan={6} className="no-data">No comments found.</td></tr>
              ) : (
                comments.map((c) => (
                  <tr key={c.id}>
                    <td>
                      {c.author_profile_url ? (
                        <a href={c.author_profile_url} target="_blank" rel="noopener noreferrer">{c.author_name || '-'}</a>
                      ) : (
                        (c.author_name || '-')
                      )}
                    </td>
                    <td className="comment-text">{c.comment_text || '-'}</td>
                    <td>
                      <span className={'badge badge-' + (c.user_type || 'unknown')}>{c.user_type || '-'}</span>
                    </td>
                    <td>
                      {c.confidence_score != null ? (c.confidence_score * 100).toFixed(0) + '%' : '-'}
                    </td>
                    <td className="analysis-cell">{c.analysis_message || '-'}</td>
                    <td>{c.comment_timestamp || (c.scraped_at ? new Date(c.scraped_at).toLocaleDateString() : '-')}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      {!loading && total > 0 && (
        <div className="comments-pagination">
          <button onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>Previous</button>
          <span>Page {page} of {totalPages} ({total} total)</span>
          <button onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>Next</button>
        </div>
      )}
    </div>
  )
}
