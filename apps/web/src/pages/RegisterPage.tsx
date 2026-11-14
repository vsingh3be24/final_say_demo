import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { api, errorMessage } from '../api/client'
import type { InstitutionChoice } from '../api/types'

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [institutions, setInstitutions] = useState<InstitutionChoice[]>([])
  const [institutionId, setInstitutionId] = useState('')
  const [loadingInstitutions, setLoadingInstitutions] = useState(true)
  const [institutionLoadError, setInstitutionLoadError] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .get<InstitutionChoice[]>('/institutions')
      .then((res) => setInstitutions(res.data))
      .catch((err) => setInstitutionLoadError(errorMessage(err)))
      .finally(() => setLoadingInstitutions(false))
  }, [])

  const onSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault()
    if (busy) return
    setError('')
    setBusy(true)
    try {
      await register(
        email.trim(),
        password,
        displayName.trim(),
        institutionId ? Number(institutionId) : undefined,
      )
      navigate('/', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="narrow">
      <div className="card">
        <p className="eyebrow">Your campus, your updates</p>
        <h1>Create your account</h1>
        <p className="muted">Choose your college to start with a focused feed of its official notices.</p>
        <form onSubmit={onSubmit}>
          <label>
            Display name
            <input
              value={displayName}
              onChange={(ev) => setDisplayName(ev.target.value)}
              autoComplete="name"
              required
            />
          </label>
          <label>
            Email
            <input
              type="email"
              value={email}
              onChange={(ev) => setEmail(ev.target.value)}
              autoComplete="email"
              required
            />
          </label>
          <label>
            Password (min 6 characters)
            <input
              type="password"
              value={password}
              minLength={6}
              onChange={(ev) => setPassword(ev.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
          <label>
            College
            {institutions.length > 0 ? (
              <select
                value={institutionId}
                onChange={(ev) => setInstitutionId(ev.target.value)}
                required
              >
                <option value="">Choose your college</option>
                {institutions.map((institution) => (
                  <option key={institution.id} value={institution.id}>
                    {institution.name}
                    {institution.current_notice_count > 0
                      ? ` · ${institution.current_notice_count.toLocaleString()} notices`
                      : ' · source coming soon'}
                  </option>
                ))}
              </select>
            ) : (
              <div className="institution-empty">
                {loadingInstitutions
                  ? 'Loading supported colleges…'
                  : 'College selection will appear once an official source is configured.'}
              </div>
            )}
          </label>
          {institutionLoadError && <p className="error" role="alert">{institutionLoadError}</p>}
          {error && <p className="error" role="alert">{error}</p>}
          <button type="submit" disabled={busy}>
            {busy ? 'Creating…' : 'Create account'}
          </button>
        </form>
        <p className="muted">
          New accounts are student accounts. Your college choice sets the default
          notice feed and comparison source; you can change it later.
        </p>
        <p className="muted">
          Already have an account? <Link to="/login">Log in</Link>
        </p>
      </div>
    </div>
  )
}
