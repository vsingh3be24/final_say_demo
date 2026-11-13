import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { errorMessage } from '../api/client'
import AuthLayout from '../components/AuthLayout'
import PasswordField from '../components/PasswordField'

export default function RegisterPage() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const onSubmit = async (ev: React.FormEvent) => {
    ev.preventDefault()
    setError('')
    setBusy(true)
    try {
      await register(email, password, displayName)
      navigate('/', { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      <div className="auth-form">
        <h1 id="auth-title">Create your account</h1>
        <p className="muted">Get started with a student account.</p>
        <form onSubmit={onSubmit}>
          <label>
            Display name <span className="muted">(optional)</span>
            <input autoComplete="name" placeholder="Your name" value={displayName} onChange={(ev) => setDisplayName(ev.target.value)} />
          </label>
          <label>
            Email address
            <input
              type="email"
              autoComplete="email"
              placeholder="you@university.edu"
              value={email}
              onChange={(ev) => setEmail(ev.target.value)}
              required
            />
          </label>
          <PasswordField value={password} onChange={setPassword} newPassword />
          {error && <p className="error" role="alert">{error}</p>}
          <button className="auth-submit" type="submit" disabled={busy}>
            {busy ? 'Creating…' : 'Create account'} <ArrowRight size={18} aria-hidden="true" />
          </button>
        </form>
        <p className="auth-switch muted">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </div>
    </AuthLayout>
  )
}
