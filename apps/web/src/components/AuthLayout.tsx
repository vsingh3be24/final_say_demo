import type { ReactNode } from 'react'
import { ArrowDown, CalendarDays, Check, FileText, ShieldCheck } from 'lucide-react'

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth-shell">
      <section className="auth-story" aria-labelledby="auth-story-title">
        <div className="auth-story-copy">
          <div className="story-icon"><ShieldCheck size={22} aria-hidden="true" /></div>
          <h2 id="auth-story-title">The official notice,<br /><em>in focus.</em></h2>
          <p>Check a forwarded circular against the official record and see what changed.</p>
        </div>
        <div className="story-example" aria-label="Illustrative verification result">
          <div className="story-example-label">Example comparison</div>
          <div className="story-document">
            <span className="story-document-icon"><FileText size={21} aria-hidden="true" /></span>
            <div><strong>Exam registration</strong><small>Forwarded notice</small></div>
            <span className="story-date"><CalendarDays size={14} aria-hidden="true" /> 18 Nov</span>
          </div>
          <span className="story-connector"><ArrowDown size={16} aria-hidden="true" /></span>
          <div className="story-document story-official">
            <span className="story-document-icon"><Check size={21} aria-hidden="true" /></span>
            <div><strong>Deadline extension</strong><small>Official notice</small></div>
            <span className="story-date"><CalendarDays size={14} aria-hidden="true" /> 22 Nov</span>
          </div>
        </div>
      </section>
      <section className="auth-panel" aria-labelledby="auth-title">{children}</section>
    </div>
  )
}
