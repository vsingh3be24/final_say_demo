import { useEffect, useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { api, errorMessage } from '../api/client'
import type { InstitutionChoice } from '../api/types'
import type { Role } from '../api/types'

interface NavItem {
  to: string
  label: string
  roles: Role[]
}

// Role-aware navigation: only links the signed-in role can use are shown.
const NAV: NavItem[] = [
  { to: '/submit', label: 'Submit', roles: ['student'] },
  { to: '/notices', label: 'Notices', roles: ['student', 'reviewer', 'admin', 'issuer'] },
  { to: '/alerts', label: 'Alerts', roles: ['student'] },
  { to: '/reviewer/queue', label: 'Queue', roles: ['reviewer', 'admin'] },
  { to: '/reviewer/benchmark', label: 'Benchmark', roles: ['reviewer'] },
  { to: '/admin/sources', label: 'Sources', roles: ['admin'] },
  { to: '/admin/provenance', label: 'Integrity', roles: ['admin'] },
  { to: '/issuer/publish', label: 'Publish', roles: ['issuer'] },
]

export default function NavBar() {
  const { user, logout, updateInstitution } = useAuth()
  const navigate = useNavigate()
  const [institutions, setInstitutions] = useState<InstitutionChoice[]>([])
  const [campusBusy, setCampusBusy] = useState(false)
  const [campusError, setCampusError] = useState('')

  useEffect(() => {
    if (user?.role !== 'student') {
      setInstitutions([])
      return
    }
    api
      .get<InstitutionChoice[]>('/institutions')
      .then((res) => setInstitutions(res.data))
      .catch(() => setInstitutions([]))
  }, [user?.role])

  const onInstitutionChange = async (institutionId: number) => {
    if (!institutionId || institutionId === user?.institution_id || campusBusy) return
    setCampusBusy(true)
    setCampusError('')
    try {
      await updateInstitution(institutionId)
      navigate('/notices')
    } catch (err) {
      setCampusError(errorMessage(err))
    } finally {
      setCampusBusy(false)
    }
  }

  const onLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <header className="navbar">
      <div className="nav-inner">
        <Link to="/" className="brand">
          <span className="brand-mark" aria-hidden="true">F</span>
          <span className="brand-wordmark">FinalSay</span>
          <span className="brand-caption">Notice intelligence</span>
        </Link>
        <nav className="nav-links">
          {user &&
            NAV.filter((item) => item.roles.includes(user.role)).map((item) => (
              <NavLink key={item.to} to={item.to} className="nav-link">
                {item.label}
              </NavLink>
            ))}
        </nav>
        <div className="nav-user">
          {user ? (
            <>
              {user.role === 'student' && user.institution_id !== null && (
                <div className="campus-switcher">
                  <span className="campus-caption">My college</span>
                  <select
                    aria-label="Change my college"
                    value={user.institution_id}
                    disabled={campusBusy}
                    onChange={(event) => void onInstitutionChange(Number(event.target.value))}
                  >
                    {institutions.map((institution) => (
                      <option key={institution.id} value={institution.id}>
                        {institution.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <span className="muted">
                {user.display_name || user.email} ({user.role})
              </span>
              <button className="btn-secondary" onClick={onLogout}>
                Log out
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login" className="nav-link">
                Log in
              </NavLink>
              <NavLink to="/register" className="nav-link">
                Register
              </NavLink>
            </>
          )}
        </div>
        {campusError && <span className="nav-campus-error" role="alert">{campusError}</span>}
      </div>
    </header>
  )
}
