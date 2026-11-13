import { Link, NavLink, useNavigate } from 'react-router-dom'
import { Bell, BookOpen, ClipboardList, FileCheck2, Globe2, Landmark, LogOut, Send, ShieldCheck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import type { Role } from '../api/types'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  roles: Role[]
}

// Role-aware navigation: only links the signed-in role can use are shown.
const NAV: NavItem[] = [
  { to: '/submit', label: 'Verify a notice', icon: FileCheck2, roles: ['student'] },
  { to: '/notices', label: 'Official notices', icon: Landmark, roles: ['student', 'reviewer', 'admin', 'issuer'] },
  { to: '/alerts', label: 'Recent updates', icon: Bell, roles: ['student'] },
  { to: '/reviewer/queue', label: 'Review queue', icon: ClipboardList, roles: ['reviewer', 'admin'] },
  { to: '/reviewer/benchmark', label: 'Benchmark', icon: BookOpen, roles: ['reviewer'] },
  { to: '/admin/sources', label: 'Sources', icon: Globe2, roles: ['admin'] },
  { to: '/admin/provenance', label: 'Integrity', icon: ShieldCheck, roles: ['admin'] },
  { to: '/issuer/publish', label: 'Publish', icon: Send, roles: ['issuer'] },
]

export default function NavBar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const accountName = user?.display_name || user?.email || ''

  const onLogout = () => {
    logout()
    navigate('/login')
  }

  return (
    <header className="navbar">
      <div className="nav-inner">
        <Link to="/" className="brand">
          <span className="brand-mark"><ShieldCheck size={22} aria-hidden="true" /></span>
          <span>FinalSay</span>
        </Link>
        {user && (
          <nav className="nav-links" aria-label="Main navigation">
            {NAV.filter((item) => item.roles.includes(user.role)).map(({ to, label, icon: Icon }) => (
              <NavLink key={to} to={to} className="nav-link">
                <Icon size={17} aria-hidden="true" /> {label}
              </NavLink>
            ))}
          </nav>
        )}
        <div className="nav-user">
          {user ? (
            <>
              <div className="account">
                <span className="avatar" aria-hidden="true">{accountName.charAt(0).toUpperCase()}</span>
                <span className="account-text"><strong>{accountName}</strong><small>{user.role}</small></span>
              </div>
              <button className="icon-button btn-secondary" onClick={onLogout} aria-label="Log out" title="Log out">
                <LogOut size={17} aria-hidden="true" />
              </button>
            </>
          ) : (
            <>
              <NavLink to="/login" className="nav-link">
                Log in
              </NavLink>
              <NavLink to="/register" className="button btn-secondary">
                Create account
              </NavLink>
            </>
          )}
        </div>
      </div>
    </header>
  )
}
