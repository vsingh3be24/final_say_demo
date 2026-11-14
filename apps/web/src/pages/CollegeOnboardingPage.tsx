import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, errorMessage } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import type { InstitutionChoice } from '../api/types'

export default function CollegeOnboardingPage() {
  const { user, updateInstitution } = useAuth()
  const navigate = useNavigate()
  const [institutions, setInstitutions] = useState<InstitutionChoice[]>([])
  const [institutionId, setInstitutionId] = useState(user?.institution_id?.toString() ?? '')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get<InstitutionChoice[]>('/institutions')
      .then((res) => setInstitutions(res.data))
      .catch((err) => setError(errorMessage(err)))
      .finally(() => setLoading(false))
  }, [])

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!institutionId || busy) return
    setBusy(true)
    setError('')
    try {
      await updateInstitution(Number(institutionId))
      navigate('/notices', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="narrow">
      <section className="card college-onboarding">
        <p className="eyebrow">One quick setup</p>
        <h1>Choose your college</h1>
        <p className="muted">
          We’ll use this to show the right official notices and compare your submissions
          against your college’s updates. You can change it any time.
        </p>
        {loading ? (
          <p className="muted">Loading supported colleges…</p>
        ) : institutions.length === 0 ? (
          <div className="institution-empty" role="status">
            There are no active college sources to choose from yet. An administrator needs to
            configure an official source before student notices can be shown.
          </div>
        ) : (
          <form onSubmit={save}>
            <label>
              College
              <select
                value={institutionId}
                onChange={(event) => setInstitutionId(event.target.value)}
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
            </label>
            <button type="submit" disabled={!institutionId || busy}>
              {busy ? 'Saving…' : 'Continue to my notices'}
            </button>
          </form>
        )}
        {error && <p className="error" role="alert">{error}</p>}
      </section>
    </div>
  )
}
