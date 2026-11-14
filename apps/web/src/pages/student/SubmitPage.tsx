import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, errorMessage } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { saveResult } from '../../api/resultCache'
import type { ComparisonResponse, InstitutionChoice } from '../../api/types'

// Student submission: paste text and/or upload a PDF/image. Posts multipart to
// /api/ingest/submit and navigates to the result once classified.
export default function SubmitPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [institution, setInstitution] = useState<InstitutionChoice | null>(null)
  const [loadingInstitution, setLoadingInstitution] = useState(true)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!user?.institution_id) {
      setLoadingInstitution(false)
      return
    }
    api
      .get<InstitutionChoice[]>('/institutions')
      .then((res) => {
        setInstitution(res.data.find((item) => item.id === user.institution_id) ?? null)
      })
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoadingInstitution(false))
  }, [user?.institution_id])

  const onSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setError('')
    if (!text.trim() && !file) {
      setError('Provide pasted text or upload a PDF/image.')
      return
    }
    setBusy(true)
    try {
      const form = new FormData()
      if (text.trim()) form.append('text', text)
      if (file) form.append('file', file)
      if (user?.institution_id) form.append('institution_id', String(user.institution_id))
      const res = await api.post<ComparisonResponse>('/ingest/submit', form)
      saveResult(res.data)
      navigate(`/result/${res.data.submission_id}`)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="submit-page">
      <section className="card submit-form-card">
        <div className="submit-card-top">
          <div className="submit-form-heading">
            <div>
              <p className="eyebrow">Official source comparison</p>
              <h1>Check a notice</h1>
              <p className="muted submit-form-description">
                Paste a message or add a document to compare it with your college’s official updates.
              </p>
            </div>
          </div>
          <div className="submit-mini-art" aria-hidden="true">
            <svg viewBox="0 0 250 150" role="presentation" xmlns="http://www.w3.org/2000/svg">
              <rect width="250" height="150" rx="18" fill="#f3efe7" />
              <path d="M0 113c42-19 76-5 108 7s86 15 142-8v38H0z" fill="#e7dfd1" />
              <path d="M157 70h75M164 70V36h61v34M155 36l39-23 40 23" fill="#e8e1d4" stroke="#aa9c84" strokeLinejoin="round" strokeWidth="2" />
              <path d="M175 70V48h10v22M197 70V43h10v27M219 70V48h8" fill="none" stroke="#aa9c84" strokeWidth="2" />
              <g transform="rotate(-5 83 86)">
                <rect x="36" y="35" width="98" height="98" rx="8" fill="#fffefa" stroke="#d4c9b6" strokeWidth="1.5" />
                <path d="M49 53h48M49 64h69M49 75h57M49 93h63M49 104h42" stroke="#c9bda8" strokeLinecap="round" strokeWidth="4" />
                <circle cx="112" cy="113" r="11" fill="#f1ece1" stroke="#c5b79f" strokeWidth="1.5" />
                <path d="m107 113 4 4 7-9" fill="none" stroke="#80745e" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.5" />
              </g>
              <circle cx="181" cy="103" r="21" fill="#f7f4ed" fillOpacity=".92" stroke="#897e69" strokeWidth="4" />
              <path d="m196 119 16 17m-39-33 5 5 10-11" fill="none" stroke="#897e69" strokeLinecap="round" strokeLinejoin="round" strokeWidth="5" />
            </svg>
          </div>
        </div>
        <div className="institution-context">
          <span className="institution-context-label">Your comparison source</span>
          {loadingInstitution ? (
            <span className="institution-loading" role="status">Finding your college’s official record…</span>
          ) : institution ? (
            <>
              <strong>{institution.name}</strong>
              <span className="institution-count">{institution.current_notice_count.toLocaleString()} current notices</span>
              <Link to="/notices">Browse source</Link>
            </>
          ) : (
            <span className="error">Your selected college is unavailable. Choose another college in the header.</span>
          )}
        </div>
        {institution && institution.current_notice_count === 0 && (
          <p className="institution-empty" role="status">
            There are no current official notices for {institution.name} yet, so we can’t
            compare a submission against it.
          </p>
        )}
        <form className="submit-form" onSubmit={onSubmit}>
          <label>
            Notice text <span className="form-optional">Paste the message or its key details</span>
            <textarea
              rows={5}
              className="submit-textarea"
              value={text}
              placeholder={'Paste the notice text here…\n\nInclude its title, date, and any changed details if available.'}
              onChange={(ev) => setText(ev.target.value)}
            />
          </label>
          <label>
            Add a document <span className="form-optional">Optional · PDF or image</span>
            <input
              className="submit-file"
              type="file"
              accept=".pdf,.png,.jpg,.jpeg,.gif,.webp,application/pdf,image/*"
              onChange={(ev) => setFile(ev.target.files?.[0] ?? null)}
            />
          </label>
          {error && <p className="error">{error}</p>}
          <div className="submit-actions">
            <button
              type="submit"
              disabled={busy || loadingInstitution || !institution || institution.current_notice_count === 0}
            >
              {busy ? 'Analyzing…' : 'Compare this notice'}
            </button>
            <span>Compared with your selected college’s current official notices</span>
          </div>
        </form>
      </section>
    </div>
  )
}
