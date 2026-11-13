import { useEffect, useState } from 'react'
import { api, errorMessage } from '../../api/client'
import type { InstitutionOut, NoticeDetail } from '../../api/types'

// Issuers can publish only for institutions explicitly granted by an admin.
export default function PublishPage() {
  const [text, setText] = useState('')
  const [institutions, setInstitutions] = useState<InstitutionOut[]>([])
  const [institutionId, setInstitutionId] = useState('')
  const [sourceUrl, setSourceUrl] = useState('')
  const [published, setPublished] = useState<NoticeDetail | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.get<InstitutionOut[]>('/issuer/institutions')
      .then((res) => setInstitutions(res.data))
      .catch((err) => setError(errorMessage(err)))
  }, [])

  const onSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setError('')
    setPublished(null)
    setBusy(true)
    try {
      const res = await api.post<NoticeDetail>('/issuer/publish', {
        text,
        institution_id: institutionId ? Number(institutionId) : null,
        source_url: sourceUrl || null,
      })
      setPublished(res.data)
      setText('')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Publish official notice</h1>
        <p className="muted">
          Publish a notice for an institution granted to your account. The notice uses
          the same extraction and SHA-256 provenance pipeline as fetched notices.
        </p>
        <form onSubmit={onSubmit}>
          <label>
            Notice text
            <textarea
              rows={8}
              value={text}
              onChange={(ev) => setText(ev.target.value)}
              placeholder="Enter the official notice text…"
              required
            />
          </label>
          <label>
            Institution
            <select value={institutionId} onChange={(ev) => setInstitutionId(ev.target.value)} required>
              <option value="">Select institution</option>
              {institutions.map((institution) => (
                <option key={institution.id} value={institution.id}>{institution.name}</option>
              ))}
            </select>
          </label>
          <label>
            Source URL (optional)
            <input value={sourceUrl} onChange={(ev) => setSourceUrl(ev.target.value)} />
          </label>
          {error && <p className="error">{error}</p>}
          <button type="submit" disabled={busy || institutions.length === 0}>
            {busy ? 'Publishing…' : 'Publish'}
          </button>
        </form>
        {institutions.length === 0 && !error && (
          <p className="muted">No institution has been granted to this issuer yet. Ask an administrator to add a publishing grant.</p>
        )}
      </div>

      {published && (
        <div className="card">
          <h2>Published notice #{published.id}</h2>
          <dl className="kv">
            <dt>Issuer</dt>
            <dd>{published.issuer ?? '—'}</dd>
            <dt>Date</dt>
            <dd>{published.notice_date ?? '—'}</dd>
            <dt>Deadline</dt>
            <dd>{published.deadline ?? '—'}</dd>
            <dt>Audience</dt>
            <dd>{published.audience ?? '—'}</dd>
            <dt>SHA-256</dt>
            <dd className="mono">{published.sha256 ?? '—'}</dd>
          </dl>
          {published.redacted_text && <pre className="pre">{published.redacted_text}</pre>}
        </div>
      )}
    </div>
  )
}
