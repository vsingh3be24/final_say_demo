import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowRight, ArrowUpRight, ChevronLeft, ChevronRight, FileSearch, FileText, Landmark, Search, X } from 'lucide-react'
import { api, errorMessage } from '../../api/client'
import type { InstitutionOut, NoticeDetail, NoticeSummary } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'

const PAGE_SIZE = 8

export default function NoticesPage() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const institutionId = searchParams.get('institution_id') ?? ''
  const noticeId = searchParams.get('notice') ?? ''
  const detailHeading = useRef<HTMLHeadingElement>(null)
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(1)
  const [notices, setNotices] = useState<NoticeSummary[]>([])
  const [sources, setSources] = useState<InstitutionOut[]>([])
  const [selected, setSelected] = useState<NoticeDetail | null>(null)
  const [error, setError] = useState('')
  const [detailError, setDetailError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const controller = new AbortController()
    api.get<InstitutionOut[]>('/ingest/sources', { signal: controller.signal })
      .then(({ data }) => setSources(data))
      .catch(() => {})
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    setError('')
    setLoading(true)
    setPage(1)
    api.get<NoticeSummary[]>('/notices', {
      params: { kind: 'official', institution_id: institutionId || undefined },
      signal: controller.signal,
    })
      .then(({ data }) => setNotices(data))
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [institutionId])

  useEffect(() => {
    setSelected(null)
    setDetailError('')
    if (!noticeId) return
    const controller = new AbortController()
    api.get<NoticeDetail>('/notices/' + noticeId, { signal: controller.signal })
      .then(({ data }) => {
        if (data.kind !== 'official') setDetailError('Choose an official notice from the catalogue.')
        else setSelected(data)
      })
      .catch((err) => {
        if (!controller.signal.aborted) setDetailError(errorMessage(err))
      })
    return () => controller.abort()
  }, [noticeId])

  useEffect(() => {
    if (selected) detailHeading.current?.focus()
  }, [selected])

  function setInstitution(value: string) {
    setSearchParams(value ? { institution_id: value } : {})
  }

  function openNotice(value: string) {
    const params = new URLSearchParams(searchParams)
    if (value) params.set('notice', value)
    else params.delete('notice')
    setSearchParams(params)
  }

  const search = query.trim().toLowerCase()
  const matches = notices.filter((notice) => (
    [notice.title, notice.issuer, notice.audience].some((value) => value?.toLowerCase().includes(search)) || !search
  ))
  const pages = Math.max(1, Math.ceil(matches.length / PAGE_SIZE))
  const visible = matches.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
  const sourceUrl = selected?.source_url
  const canCompare = user?.role === 'student' && selected?.redacted_text && selected.is_current &&
    sources.some((source) => source.id === selected.institution_id && source.active && source.current_notice_count > 0)

  return (
    <div className="stack">
      <header className="page-heading">
        <div>
          <span className="page-kicker"><Landmark size={17} aria-hidden="true" /> Source catalogue</span>
          <h1>Official notices</h1>
          <p className="muted">Find a circular or see the notice as it appeared at its source.</p>
        </div>
      </header>
      <div className={noticeId ? 'catalogue catalogue-open' : 'catalogue'}>
        <section className="card catalogue-list" aria-label="Find official notices">
          <div className="catalogue-filters">
            <label>
              Search notices
              <span className="search-control"><Search size={18} aria-hidden="true" /><input type="search" value={query}
                placeholder="Search by title, issuer or audience" onChange={(event) => { setQuery(event.target.value); setPage(1) }} /></span>
            </label>
            <label>
              Institution
              <select value={institutionId} onChange={(event) => setInstitution(event.target.value)}>
                <option value="">All institutions</option>
                {institutionId && !sources.some((source) => String(source.id) === institutionId) && <option value={institutionId}>Selected institution</option>}
                {sources.map(({ id, name }) => <option value={id} key={id}>{name}</option>)}
              </select>
            </label>
          </div>

          {loading ? <p className="muted" role="status">Loading notices…</p> : error ? <p className="error" role="alert">{error}</p> : (
            <>
              <p className="catalogue-count muted" role="status">{matches.length} {matches.length === 1 ? 'notice' : 'notices'}</p>
              {visible.length ? (
                <ul className="notice-list">
                  {visible.map((notice) => (
                    <li key={notice.id}>
                      <button className="notice-row" type="button" aria-pressed={noticeId === String(notice.id)} onClick={() => openNotice(String(notice.id))}>
                        <span className="section-icon"><FileText size={20} aria-hidden="true" /></span>
                        <span className="notice-row-title"><strong>{notice.title || notice.issuer || 'Official notice'}</strong>
                          <small>{[notice.issuer, notice.published_date || notice.notice_date].filter(Boolean).join(' · ') || 'Publication date unavailable'}</small></span>
                        <ArrowRight size={18} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
              ) : <div className="empty-state"><FileSearch size={24} aria-hidden="true" /><p>{search ? 'No notices match your search.' : 'No official notices are available here yet.'}</p></div>}
              {pages > 1 && <div className="pagination" aria-label="Notice pages">
                <button type="button" className="icon-button btn-secondary" disabled={page === 1} aria-label="Previous page" onClick={() => setPage(page - 1)}><ChevronLeft size={18} aria-hidden="true" /></button>
                <span>Page {page} of {pages}</span>
                <button type="button" className="icon-button btn-secondary" disabled={page >= pages} aria-label="Next page" onClick={() => setPage(page + 1)}><ChevronRight size={18} aria-hidden="true" /></button>
              </div>}
            </>
          )}
        </section>

        {noticeId && <section className="card notice-detail" aria-label="Official notice details">
          <div className="detail-top">
            <span className="page-kicker"><FileText size={17} aria-hidden="true" /> Notice details</span>
            <button type="button" className="icon-button btn-secondary" onClick={() => openNotice('')} aria-label="Close notice"><X size={17} aria-hidden="true" /></button>
          </div>
          {detailError ? <p className="error" role="alert">{detailError}</p> : !selected ? <p className="muted" role="status">Loading notice…</p> : (
            <>
              <h2 tabIndex={-1} ref={detailHeading}>{selected.title || 'Official notice #' + selected.id}</h2>
              <dl className="kv">
                <dt>Issuer</dt><dd>{selected.issuer || '—'}</dd>
                <dt>Published</dt><dd>{selected.published_date || selected.notice_date || '—'}</dd>
                <dt>Deadline</dt><dd>{selected.deadline || '—'}</dd>
                <dt>Audience</dt><dd>{selected.audience || '—'}</dd>
                <dt>Action</dt><dd>{selected.action || '—'}</dd>
              </dl>
              <div className="row notice-detail-actions">
                {sourceUrl && /^https?:\/\//i.test(sourceUrl) && <a className="button" href={sourceUrl} target="_blank" rel="noreferrer">Open source <ArrowUpRight size={16} aria-hidden="true" /></a>}
                {canCompare && <Link to="/submit" state={{ text: selected.redacted_text, institutionId: selected.institution_id }} className="button btn-secondary">Use as sample <ArrowRight size={16} aria-hidden="true" /></Link>}
              </div>
              <details className="document-details">
                <summary>Notice text</summary>
                <pre className="pre">{selected.redacted_text || 'No readable notice text is available.'}</pre>
              </details>
              <details className="document-details">
                <summary>Record information</summary>
                <dl className="kv">
                  <dt>Version</dt><dd>{selected.version_no}{selected.is_current ? ' · Current' : ''}</dd>
                  <dt>Indexed</dt><dd>{selected.retrieved_at ? new Date(selected.retrieved_at).toLocaleString() : '—'}</dd>
                  <dt>SHA-256</dt><dd className="mono">{selected.sha256 || '—'}</dd>
                </dl>
              </details>
            </>
          )}
        </section>}
      </div>
    </div>
  )
}
