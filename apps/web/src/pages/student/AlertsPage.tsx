import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Clock3, FileText } from 'lucide-react'
import { api, errorMessage } from '../../api/client'
import type { NoticeSummary } from '../../api/types'

export default function AlertsPage() {
  const [notices, setNotices] = useState<NoticeSummary[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    api.get<NoticeSummary[]>('/notices', { params: { kind: 'official' }, signal: controller.signal })
      .then(({ data }) => setNotices(data.slice(0, 10)))
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [])

  return (
    <div className="stack">
      <header className="page-heading">
        <div><span className="page-kicker"><Clock3 size={17} aria-hidden="true" /> Official sources</span>
          <h1>Recent updates</h1><p className="muted">The latest official notices added to the catalogue.</p></div>
        <Link to="/notices" className="button btn-secondary">All official notices <ArrowRight size={17} aria-hidden="true" /></Link>
      </header>
      <section className="card" aria-label="Recently indexed notices">
        {loading ? <p className="muted" role="status">Loading updates…</p> : error ? <p className="error" role="alert">{error}</p> :
          notices.length === 0 ? <p className="muted">No official notices are available yet.</p> : (
            <ul className="notice-list">{notices.map((notice) => (
              <li key={notice.id}>
                <Link className="notice-row" to={'/notices?notice=' + notice.id}>
                  <span className="section-icon"><FileText size={20} aria-hidden="true" /></span>
                  <span className="notice-row-title"><strong>{notice.title || notice.issuer || 'Official notice'}</strong>
                    <small>{[notice.issuer, notice.published_date || notice.notice_date].filter(Boolean).join(' · ')}</small></span>
                  <ArrowRight size={18} aria-hidden="true" />
                </Link>
              </li>
            ))}</ul>
          )}
      </section>
    </div>
  )
}
