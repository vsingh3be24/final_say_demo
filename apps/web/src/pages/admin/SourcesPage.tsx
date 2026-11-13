import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, errorMessage } from '../../api/client'
import type { BenchmarkCandidateOut, FetchResponse, InstitutionOut, IssuerMembershipOut, ScrapeRunOut } from '../../api/types'

type ScrapeType = InstitutionOut['scrape_type']
const SCRAPERS: Array<{ value: ScrapeType; label: string }> = [
  { value: 'thapar_html', label: 'Thapar notice board (HTML/PDF)' },
  { value: 'nitj_api', label: 'NIT Jalandhar academic notices (JSON/PDF)' },
  { value: 'iitb_html', label: 'IIT Bombay academic notices (HTML/PDF)' },
  { value: 'vtu_examination', label: 'VTU examination notices (paginated HTML/PDF)' },
  { value: 'du_examination', label: 'University of Delhi examination notices (paginated HTML/PDF)' },
  { value: 'mumbai_circulars', label: 'University of Mumbai circulars (HTML/PDF)' },
]

// Admin source management is wired to institution CRUD and the real scraper.
export default function SourcesPage() {
  const [sources, setSources] = useState<InstitutionOut[]>([])
  const [runs, setRuns] = useState<ScrapeRunOut[]>([])
  const [issuerGrants, setIssuerGrants] = useState<IssuerMembershipOut[]>([])
  const [benchmarkCandidates, setBenchmarkCandidates] = useState<BenchmarkCandidateOut[]>([])
  const [issuerEmail, setIssuerEmail] = useState('')
  const [grantInstitutionId, setGrantInstitutionId] = useState('')
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [scrapeType, setScrapeType] = useState<ScrapeType>('vtu_examination')
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editUrl, setEditUrl] = useState('')
  const [editType, setEditType] = useState<ScrapeType>('vtu_examination')
  const [editEnabled, setEditEnabled] = useState(false)
  const [editActive, setEditActive] = useState(true)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [fetchResult, setFetchResult] = useState<FetchResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [sourcesRes, runsRes, grantsRes, benchmarkRes] = await Promise.all([
        api.get<InstitutionOut[]>('/ingest/sources'),
        api.get<ScrapeRunOut[]>('/ingest/runs'),
        api.get<IssuerMembershipOut[]>('/issuer-memberships'),
        api.get<BenchmarkCandidateOut[]>('/admin/benchmark/candidates'),
      ])
      setSources(sourcesRes.data)
      setRuns(runsRes.data)
      setIssuerGrants(grantsRes.data)
      setBenchmarkCandidates(benchmarkRes.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void load() }, [load])

  const addSource = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setError('')
    setMessage('')
    setBusy(true)
    try {
      await api.post('/ingest/sources', {
        name,
        slug,
        source_url: sourceUrl || null,
        scrape_type: scrapeType,
        scrape_enabled: true,
        active: true,
      })
      setName('')
      setSlug('')
      setSourceUrl('')
      setScrapeType('vtu_examination')
      setMessage('Institution source added.')
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const beginEdit = (source: InstitutionOut) => {
    setEditingId(source.id)
    setEditUrl(source.source_url ?? '')
    setEditType(source.scrape_type)
    setEditEnabled(source.scrape_enabled)
    setEditActive(source.active)
  }

  const saveSource = async (source: InstitutionOut) => {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      await api.put(`/ingest/sources/${source.id}`, {
        source_url: editUrl || null,
        scrape_type: editType,
        scrape_enabled: editEnabled,
        active: editActive,
      })
      setEditingId(null)
      setMessage(`Updated source ${source.slug}.`)
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const triggerFetch = async () => {
    setError('')
    setMessage('')
    setFetchResult(null)
    setBusy(true)
    try {
      const res = await api.post<FetchResponse>('/ingest/fetch')
      setFetchResult(res.data)
      setMessage(
        `Poll complete: ${res.data.created} new, ${res.data.modified} revised, ` +
        `${res.data.skipped} unchanged, ${res.data.errors} source errors.`,
      )
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const grantIssuer = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setError('')
    setMessage('')
    setBusy(true)
    try {
      await api.post('/issuer-memberships', {
        issuer_email: issuerEmail,
        institution_id: Number(grantInstitutionId),
      })
      setIssuerEmail('')
      setMessage('Issuer publishing grant added.')
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const revokeIssuer = async (grant: IssuerMembershipOut) => {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      await api.delete(`/issuer-memberships/${grant.user_id}/${grant.institution_id}`)
      setMessage(`Revoked ${grant.issuer_email} access to ${grant.institution_name}.`)
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const addBenchmarkCandidate = async (candidate: BenchmarkCandidateOut) => {
    setError('')
    setMessage('')
    setBusy(true)
    try {
      await api.post('/admin/benchmark/pairs', {
        submission_id: candidate.submission_id,
        official_id: candidate.official_id,
      })
      setMessage('Real comparison added to the blind reviewer benchmark.')
      await load()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Institution sources</h1>
        <p className="muted">
          Active, enabled sources poll on backend startup and at the configured
          interval. You can also poll now. Live adapters use HTTPS, allow-listed
          hosts, robots rules, bounded downloads, retries and per-host spacing.
        </p>
        <div className="row">
          <button onClick={triggerFetch} disabled={busy}>
            {busy ? 'Polling sources…' : 'Poll configured sources'}
          </button>
        </div>
        {message && <p className="banner banner-ok">{message}</p>}
        {error && <p className="error">{error}</p>}
        {fetchResult && (
          <ul>
            {fetchResult.institutions.map((item, index) => (
              <li key={`${String(item.slug)}-${index}`}>
                {String(item.name)}: {String(item.status)} · {String(item.found)} found ·{' '}
                {String(item.created)} new · {String(item.modified)} revised ·{' '}
                {String(item.skipped)} unchanged
                {item.error ? ` — ${String(item.error)}` : ''}
              </li>
            ))}
          </ul>
        )}
        {loading ? (
          <p className="muted">Loading…</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th><th>Slug</th><th>Listing URL</th><th>Scraper</th><th>Active</th><th>Polling</th><th>Backfill</th><th>Last successful poll</th><th>Latest poll result</th><th>Extraction</th><th>Notices</th><th />
              </tr>
            </thead>
            <tbody>
              {sources.map((source) => {
                const latestRun = runs.find((run) => run.institution_id === source.id)
                return (
                <tr key={source.id}>
                  <td>{source.name}</td>
                  <td>{source.slug}</td>
                  <td>{source.source_url ?? '—'}</td>
                  <td>{SCRAPERS.find((item) => item.value === source.scrape_type)?.label ?? source.scrape_type}</td>
                  <td>{source.active ? 'yes' : 'no'}</td>
                  <td>{source.scrape_enabled ? 'yes' : 'no'}</td>
                  <td>{source.backfill_complete ? 'complete' : 'in progress' + (source.backfill_cursor ? ' · ' + source.backfill_cursor : '')}</td>
                  <td>
                    {source.last_successful_fetch
                      ? `${new Date(source.last_successful_fetch).toLocaleString()} · ${source.last_successful_created} new, ${source.last_successful_modified} revised, ${source.last_successful_unchanged} unchanged`
                      : 'No successful poll yet'}
                  </td>
                  <td>
                    {latestRun ? (
                      <>
                        <div>{latestRun.status} · {latestRun.started_at ? new Date(latestRun.started_at).toLocaleString() : 'time unknown'}</div>
                        {latestRun.error && <div className="error" title={latestRun.error}>{latestRun.error.slice(0, 180)}</div>}
                      </>
                    ) : 'No recent poll in the latest 50 runs'}
                  </td>
                  <td>
                    {source.extracted_count}/{source.current_notice_count} extracted ·{' '}
                    {source.listing_only_count} listing-only · {source.unextractable_count} failed ·{' '}
                    {source.unknown_extraction_count} unknown
                  </td>
                  <td><Link to={`/notices?institution_id=${source.id}`}>Browse notices</Link></td>
                  <td><button type="button" onClick={() => beginEdit(source)}>Configure</button></td>
                </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {editingId != null && (
          <form className="stack-sm" onSubmit={(ev) => { ev.preventDefault(); const source = sources.find((item) => item.id === editingId); if (source) void saveSource(source) }}>
            <h2>Configure source #{editingId}</h2>
            <label>
              Scraper
              <select value={editType} onChange={(ev) => setEditType(ev.target.value as ScrapeType)}>
                {SCRAPERS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
            </label>
            <label>
              Public listing/feed URL
              <input value={editUrl} onChange={(ev) => setEditUrl(ev.target.value)} />
            </label>
            <label>
              <input type="checkbox" checked={editEnabled} onChange={(ev) => setEditEnabled(ev.target.checked)} /> Enable polling
            </label>
            <label>
              <input type="checkbox" checked={editActive} onChange={(ev) => setEditActive(ev.target.checked)} /> Active source
            </label>
            <div className="row">
              <button type="submit" disabled={busy}>Save configuration</button>
              <button type="button" onClick={() => setEditingId(null)} disabled={busy}>Cancel</button>
            </div>
          </form>
        )}
      </div>

      <div className="card">
        <h2>Blind reviewer benchmark</h2>
        <p className="muted">
          Curate persisted student submissions and their current notices from live sources. Seeded
          submissions and model labels are excluded; reviewers label each saved pair independently.
        </p>
        {benchmarkCandidates.length === 0 ? (
          <p className="muted">No uncurated real student comparisons are available yet.</p>
        ) : (
          <table>
            <thead><tr><th>Institution</th><th>Student submission</th><th>Current official notice</th><th>Notice date</th><th /></tr></thead>
            <tbody>{benchmarkCandidates.map((candidate) => (
              <tr key={`${candidate.submission_id}-${candidate.official_id}`}>
                <td>{candidate.institution_name}</td>
                <td>#{candidate.submission_id} · {candidate.submission_title || 'Untitled submission'}</td>
                <td>#{candidate.official_id} · {candidate.official_title || 'Untitled official notice'}</td>
                <td>{candidate.official_published_date || '—'}</td>
                <td><button type="button" disabled={busy} onClick={() => void addBenchmarkCandidate(candidate)}>Add blind pair</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Issuer publishing grants</h2>
        <p className="muted">Only an administrator can grant an existing issuer account access to an institution.</p>
        <form className="row" onSubmit={grantIssuer}>
          <label>Issuer email<input type="email" value={issuerEmail} onChange={(ev) => setIssuerEmail(ev.target.value)} required /></label>
          <label>Institution
            <select value={grantInstitutionId} onChange={(ev) => setGrantInstitutionId(ev.target.value)} required>
              <option value="">Select institution</option>
              {sources.filter((source) => source.active).map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}
            </select>
          </label>
          <button type="submit" disabled={busy || !grantInstitutionId}>Grant access</button>
        </form>
        {issuerGrants.length === 0 ? <p className="muted">No active issuer grants.</p> : (
          <table>
            <thead><tr><th>Issuer</th><th>Institution</th><th /></tr></thead>
            <tbody>{issuerGrants.filter((grant) => grant.active).map((grant) => (
              <tr key={`${grant.user_id}-${grant.institution_id}`}>
                <td>{grant.display_name ? `${grant.display_name} · ` : ''}{grant.issuer_email}</td>
                <td>{grant.institution_name}</td>
                <td><button type="button" disabled={busy} onClick={() => void revokeIssuer(grant)}>Revoke</button></td>
              </tr>
            ))}</tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Recent scrape runs</h2>
        {runs.length === 0 ? <p className="muted">No live source polls recorded yet.</p> : (
          <table>
            <thead><tr><th>Started</th><th>Institution</th><th>Status</th><th>Found</th><th>New</th><th>Revised</th><th>Unchanged</th><th>Error</th></tr></thead>
            <tbody>{runs.map((run) => {
              const source = sources.find((item) => item.id === run.institution_id)
              return <tr key={run.id}>
                <td>{run.started_at ? new Date(run.started_at).toLocaleString() : '—'}</td>
                <td>{source?.name ?? `#${run.institution_id}`}</td>
                <td>{run.status}</td><td>{run.found}</td><td>{run.created}</td><td>{run.modified}</td><td>{run.unchanged}</td><td>{run.error ?? '—'}</td>
              </tr>
            })}</tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h2>Add an institution</h2>
        <form onSubmit={addSource}>
          <label>Name<input value={name} onChange={(ev) => setName(ev.target.value)} required /></label>
          <label>Slug<input value={slug} onChange={(ev) => setSlug(ev.target.value)} required /></label>
          <label>
            Scraper
            <select value={scrapeType} onChange={(ev) => setScrapeType(ev.target.value as ScrapeType)}>
              {SCRAPERS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <label>
            Listing/feed URL
            <input
              value={sourceUrl}
              onChange={(ev) => setSourceUrl(ev.target.value)}
              placeholder={
                scrapeType === 'thapar_html' ? 'https://www.thapar.edu/students/pages/dean-academics-notice-board'
                  : scrapeType === 'nitj_api' ? 'https://www.nitj.ac.in/api/academicnotices/get/all'
                    : scrapeType === 'iitb_html' ? 'https://acad.iitb.ac.in/circulars'
                      : scrapeType === 'vtu_examination' ? 'https://vtu.ac.in/category/examination/'
                        : scrapeType === 'du_examination' ? 'https://exam.du.ac.in/exam/index.php/notifications'
                          : scrapeType === 'mumbai_circulars' ? 'https://mu.ac.in/circular.php'
                          : 'Enter the HTTPS listing URL on the official institution domain'
              }
              required
            />
          </label>
          <button type="submit" disabled={busy}>Add source</button>
        </form>
      </div>
    </div>
  )
}
