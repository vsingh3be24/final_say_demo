import { useState } from 'react'
import { useLocation, useNavigate, Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { errorMessage } from '../api/client'
import AuthLayout from '../components/AuthLayout'
import PasswordField from '../components/PasswordField'

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const from = (location.state as { from?: string } | null)?.from || '/'

  const doLogin = async (e: string, p: string) => {
    setError('')
    setBusy(true)
    try {
      await login(e, p)
      navigate(from, { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      <div className="auth-form">
        <h1 id="auth-title">Welcome back</h1>
        <p className="muted">Sign in to your FinalSay workspace.</p>
        <form
          onSubmit={(ev) => {
            ev.preventDefault()
            void doLogin(email, password)
          }}
        >
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
          <PasswordField value={password} onChange={setPassword} />
          {error && <p className="error" role="alert">{error}</p>}
          <button className="auth-submit" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'} <ArrowRight size={18} aria-hidden="true" />
          </button>
        </form>
        <p className="auth-switch muted">
          New to FinalSay? <Link to="/register">Create an account</Link>
        </p>
      </div>

    </AuthLayout>
  )
}
