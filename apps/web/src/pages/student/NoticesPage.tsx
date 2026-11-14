import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, errorMessage } from '../../api/client'
import type { NoticeDetail, StudentNoticeFeed, StudentNoticeItem } from '../../api/types'

const PAGE_SIZE = 20

function formatMonth(value: string): string {
  const [year, month] = value.split('-').map(Number)
  return new Intl.DateTimeFormat('en-IN', { month: 'long', year: 'numeric' }).format(
    new Date(year, month - 1, 1),
  )
}

function formatPublishedDate(notice: StudentNoticeItem): string {
  if (!notice.published_on) return 'Date unavailable'
  return new Intl.DateTimeFormat('en-IN', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(new Date(`${notice.published_on}T00:00:00`))
}

export default function NoticesPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const month = searchParams.get('month') ?? ''
  const query = searchParams.get('q') ?? ''
  const parsedPage = Number(searchParams.get('page') ?? '1')
  const page = Number.isFinite(parsedPage) && parsedPage > 0 ? parsedPage : 1
  const [searchInput, setSearchInput] = useState(query)
  const [feed, setFeed] = useState<StudentNoticeFeed | null>(null)
  const [selected, setSelected] = useState<NoticeDetail | null>(null)
  const [detailLoadingId, setDetailLoadingId] = useState<number | null>(null)
  const [detailError, setDetailError] = useState('')
  const [detailErrorId, setDetailErrorId] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    setError('')
    api
      .get<StudentNoticeFeed>('/notices/student/feed', {
        params: {
          ...(month ? { month } : {}),
          ...(query ? { q: query } : {}),
          page,
          page_size: PAGE_SIZE,
        },
      })
      .then((res) => setFeed(res.data))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [month, query, page])

  useEffect(() => setSearchInput(query), [query])

  useEffect(() => {
    if (feed && feed.page_count > 0 && page > feed.page_count) {
      const next = new URLSearchParams(searchParams)
      next.set('page', String(feed.page_count))
      setSearchParams(next, { replace: true })
    }
  }, [feed, page, searchParams, setSearchParams])

  const updateFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    setSearchParams(next)
    setSelected(null)
  }

  const applySearch = (event: FormEvent) => {
    event.preventDefault()
    updateFilter('q', searchInput.trim())
  }

  const clearFilters = () => {
    setSearchInput('')
    setSearchParams({})
    setSelected(null)
  }

  const openDetail = async (noticeId: number) => {
    setSelected(null)
    setDetailError('')
    setDetailErrorId(null)
    setDetailLoadingId(noticeId)
    try {
      const res = await api.get<NoticeDetail>(`/notices/${noticeId}`)
      setSelected(res.data)
    } catch (err) {
      setDetailError(errorMessage(err))
      setDetailErrorId(noticeId)
    } finally {
      setDetailLoadingId(null)
    }
  }

  const goToPage = (targetPage: number) => {
    const next = new URLSearchParams(searchParams)
    if (targetPage <= 1) next.delete('page')
    else next.set('page', String(targetPage))
    setSearchParams(next)
    setSelected(null)
  }

  const startIndex = feed && feed.total > 0 ? (page - 1) * PAGE_SIZE + 1 : 0
  const endIndex = feed ? Math.min(page * PAGE_SIZE, feed.total) : 0

  return (
    <div className="stack notice-feed-page">
      <section className="card notice-feed-header">
        <div>
          <p className="eyebrow">Your campus bulletin</p>
          <h1>{feed?.institution_name ? `Notices from ${feed.institution_name}` : 'My college notices'}</h1>
          <p className="muted">
            Official updates from your selected college, arranged by publication date.
          </p>
        </div>
        <Link className="button-link" to="/submit">Check a notice</Link>
      </section>

      {feed && (
        <section className="feed-stats" aria-label="Notice feed summary">
          <div className="feed-stat">
            <span>Official notices</span>
            <strong>{feed.total.toLocaleString()}</strong>
            <small>{month || query ? 'matching your filters' : 'in your college feed'}</small>
          </div>
          <div className="feed-stat">
            <span>Months available</span>
            <strong>{feed.months.length.toLocaleString()}</strong>
            <small>with a publication date</small>
          </div>
          <div className="feed-stat">
            <span>Date unavailable</span>
            <strong>{feed.undated_count.toLocaleString()}</strong>
            <small>kept separate from dated notices</small>
          </div>
        </section>
      )}

      <section className="card notice-browser">
        <div className="notice-browser-head">
          <div>
            <p className="eyebrow">The official record</p>
            <h2>Browse notices</h2>
          </div>
          <span className="notice-order-note">Newest publication dates first</span>
        </div>

        <div className="notice-filters">
          <form className="notice-search" onSubmit={applySearch} role="search">
            <label htmlFor="notice-search-input">Search notices</label>
            <div className="search-control">
              <input
                id="notice-search-input"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Title, issuer or notice text"
              />
              <button type="submit">Search</button>
            </div>
          </form>
          <label className="month-filter">
            Publication month
            <select value={month} onChange={(event) => updateFilter('month', event.target.value)}>
              <option value="">All months</option>
              {feed?.months.map((entry) => (
                <option key={entry.month} value={entry.month}>
                  {formatMonth(entry.month)} · {entry.count}
                </option>
              ))}
              {Boolean(feed?.undated_count) && (
                <option value="undated">Date unavailable · {feed?.undated_count}</option>
              )}
            </select>
          </label>
          {(month || query) && (
            <button type="button" className="btn-secondary clear-filter" onClick={clearFilters}>
              Clear filters
            </button>
          )}
        </div>

        {loading ? (
          <div className="notice-loading" role="status">Loading your college notices…</div>
        ) : error ? (
          <div className="feed-empty" role="alert">
            <strong>We couldn’t load the notice feed.</strong>
            <p>{error}</p>
            <button type="button" className="btn-secondary" onClick={() => setSearchParams(new URLSearchParams(searchParams))}>
              Try again
            </button>
          </div>
        ) : feed?.items.length ? (
          <>
            <div className="notice-list">
              {feed.items.map((notice) => (
                <article className="notice-item" key={notice.id}>
                  <div className={`notice-date-tile${notice.published_on ? '' : ' notice-date-undated'}`}>
                    {notice.published_on ? (
                      <>
                        <strong>
                          {new Intl.DateTimeFormat('en-IN', { day: '2-digit' }).format(
                            new Date(`${notice.published_on}T00:00:00`),
                          )}
                        </strong>
                        <span>
                          {new Intl.DateTimeFormat('en-IN', { month: 'short' }).format(
                            new Date(`${notice.published_on}T00:00:00`),
                          )}
                        </span>
                      </>
                    ) : (
                      <span>Undated</span>
                    )}
                  </div>
                  <div className="notice-item-content">
                    <div className="notice-item-meta">
                      <span>{notice.issuer || feed.institution_name}</span>
                      {notice.audience && <span>{notice.audience}</span>}
                      <span>{formatPublishedDate(notice)}</span>
                    </div>
                    <h3>{notice.title || 'Official institutional notice'}</h3>
                    {notice.preview && <p>{notice.preview}</p>}
                    <div className="notice-item-footer">
                      <span className="notice-source-label">Official source</span>
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={detailLoadingId !== null && detailLoadingId !== notice.id}
                        onClick={() => {
                          if (selected?.id === notice.id) setSelected(null)
                          else void openDetail(notice.id)
                        }}
                      >
                        {detailLoadingId === notice.id
                          ? 'Loading…'
                          : selected?.id === notice.id
                            ? 'Hide notice'
                            : 'View notice'}
                      </button>
                    </div>
                  </div>
                  {detailLoadingId === notice.id && (
                    <section className="card notice-detail-card" role="status" aria-live="polite">
                      Loading notice details…
                    </section>
                  )}
                  {detailErrorId === notice.id && detailError && (
                    <p className="error notice-detail-error" role="alert">{detailError}</p>
                  )}
                  {selected?.id === notice.id && (
                    <section className="card notice-detail-card" aria-label="Notice details">
                      <div className="notice-browser-head">
                        <div>
                          <p className="eyebrow">Official source detail</p>
                          <h2>{selected.title || `Notice #${selected.id}`}</h2>
                        </div>
                      </div>
                      <dl className="kv">
                        <dt>Issuer</dt><dd>{selected.issuer ?? '—'}</dd>
                        <dt>Notice date</dt><dd>{selected.notice_date ?? '—'}</dd>
                        <dt>Publication date</dt><dd>{selected.published_date ?? 'Not listed by the source'}</dd>
                        <dt>Deadline</dt><dd>{selected.deadline ?? '—'}</dd>
                        <dt>Audience</dt><dd>{selected.audience ?? '—'}</dd>
                        <dt>Action</dt><dd>{selected.action ?? '—'}</dd>
                        <dt>Source</dt>
                        <dd>
                          {selected.source_url ? (
                            <a href={selected.source_url} target="_blank" rel="noreferrer">Open official source</a>
                          ) : '—'}
                        </dd>
                        <dt>SHA-256</dt><dd className="mono">{selected.sha256 ?? '—'}</dd>
                      </dl>
                      {selected.redacted_text && <pre className="pre">{selected.redacted_text}</pre>}
                    </section>
                  )}
                </article>
              ))}
            </div>
            <div className="feed-pagination" aria-label="Notice feed pagination">
              <span>Showing {startIndex}–{endIndex} of {feed.total.toLocaleString()}</span>
              <div>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={page <= 1}
                  onClick={() => goToPage(page - 1)}
                >
                  Previous
                </button>
                <span>Page {page} of {feed.page_count}</span>
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={page >= feed.page_count}
                  onClick={() => goToPage(page + 1)}
                >
                  Next
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="feed-empty">
            <span className="empty-mark" aria-hidden="true">—</span>
            <strong>
              {query
                ? 'No notices match that search.'
                : month === 'undated'
                  ? 'No undated notices in this feed.'
                  : month
                    ? `No notices published in ${formatMonth(month)}.`
                    : 'No official notices are available for this college yet.'}
            </strong>
            <p>
              {query || month
                ? 'Try another month or clear your filters to see more notices.'
                : 'When new official notices are collected, they will appear here.'}
            </p>
            {(query || month) && (
              <button type="button" className="btn-secondary" onClick={clearFilters}>
                Show all notices
              </button>
            )}
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </section>

    </div>
  )
}
