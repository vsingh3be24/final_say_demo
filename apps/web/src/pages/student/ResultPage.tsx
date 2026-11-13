import { useEffect, useState } from 'react'
import { isAxiosError } from 'axios'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, ArrowUpRight, CircleCheck, Clock3, FileText, Fingerprint, GitCompareArrows, Landmark, ShieldCheck, TriangleAlert } from 'lucide-react'
import { api, errorMessage } from '../../api/client'
import type { ComparisonResponse, NoticeDetail, RelationshipLabel, VerifyResponse } from '../../api/types'
import LabelBadge from '../../components/LabelBadge'

const GUIDANCE: Record<RelationshipLabel, { title: string; summary: string; next: string }> = {
  consistent: {
    title: 'The details match',
    summary: 'The submitted details align with the matched official record.',
    next: 'Use the matched official notice as your reference and check its instructions before you act.',
  },
  contradictory: {
    title: 'The notices disagree',
    summary: 'The submitted notice conflicts with information in the matched official record.',
    next: 'Check the dates and instructions on the institution’s official notice before relying on the forwarded copy.',
  },
  superseded: {
    title: 'A newer version may apply',
    summary: 'The notices contain different dates or instructions for the same activity.',
    next: 'Look for the latest version on the official notice board before acting on either date.',
  },
  corrected: {
    title: 'A correction was identified',
    summary: 'One of the notices contains a correction to information in the other.',
    next: 'Open the official source and follow the instructions in its latest correction.',
  },
  extended: {
    title: 'The deadline appears to have changed',
    summary: 'The comparison found wording or dates that indicate an extension.',
    next: 'Confirm the current deadline on the official source before making plans.',
  },
  cancelled: {
    title: 'A cancellation was identified',
    summary: 'The notices include a cancellation for the activity being compared.',
    next: 'Confirm which activity was cancelled on the official notice board before changing your plans.',
  },
  unresolved: {
    title: 'No clear conclusion yet',
    summary: 'The available records do not establish a clear relationship between the notices.',
    next: 'Check the institution’s official notice board for the most recent instructions.',
  },
}

const INTEGRITY_MESSAGES: Record<VerifyResponse['integrity_status'], string> = {
  VERIFIED: 'The notice matches its public Polygon Amoy anchor.',
  LOCAL_VERIFIED: 'The notice matches its local hash and Merkle proof.',
  TAMPERED: 'The notice hash or Merkle proof did not match.',
  PENDING: 'The anchor transaction is awaiting confirmation.',
  VERIFICATION_UNAVAILABLE: 'The public chain could not be reached. Try the integrity check again later.',
  NOT_ANCHORED: 'This notice has no confirmed anchor.',
}

interface RecentComparison {
  edgeId: number
  evidence?: string[]
  candidateScore?: number | null
}

export default function ResultPage() {
  const { id } = useParams()
  const { state } = useLocation()
  const recent = state as RecentComparison | null
  const submissionId = Number(id)
  const [submission, setSubmission] = useState<NoticeDetail | null>(null)
  const [outcome, setOutcome] = useState<ComparisonResponse | null>(null)
  const [verify, setVerify] = useState<VerifyResponse | null>(null)
  const [error, setError] = useState('')
  const [verifyError, setVerifyError] = useState('')
  const [loading, setLoading] = useState(true)
  const [verifying, setVerifying] = useState(false)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    setVerify(null)
    setVerifyError('')
    const result = api.get<ComparisonResponse>('/compare/' + submissionId, { signal: controller.signal })
      .catch((err: unknown) => {
        if (isAxiosError(err) && err.response?.status === 404) return null
        throw err
      })
    Promise.all([
      api.get<NoticeDetail>('/notices/' + submissionId, { signal: controller.signal }),
      result,
    ])
      .then(([notice, comparison]) => {
        setSubmission(notice.data)
        setOutcome(comparison?.data ?? null)
      })
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err))
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })
    return () => controller.abort()
  }, [submissionId, attempt])

  async function runVerify(candidateId: number, tamper: boolean) {
    setVerifying(true)
    setVerify(null)
    setVerifyError('')
    try {
      const { data } = await api.get<VerifyResponse>('/provenance/verify/' + candidateId, { params: { tamper } })
      setVerify(data)
    } catch (err) {
      setVerifyError(errorMessage(err))
    } finally {
      setVerifying(false)
    }
  }

  const back = <Link to="/submit" className="back-link"><ArrowLeft size={17} aria-hidden="true" /> Check another notice</Link>
  if (loading) return <div className="card loading-card" role="status">Loading saved verification…</div>
  if (error || !submission) {
    return <div className="stack">{back}<div className="card"><h1>Verification result</h1>
      <p className="error" role="alert">{error || 'This submission could not be found.'}</p>
      <button type="button" onClick={() => setAttempt(attempt + 1)}>Try again</button>
    </div></div>
  }

  const candidateId = outcome?.candidate_id
  const advice = outcome && GUIDANCE[outcome.label]
  const reviewed = outcome?.status === 'confirmed' || outcome?.status === 'corrected'
  const sourceUrl = outcome?.candidate_source_url
  const sourceLink = sourceUrl && /^https?:\/\//i.test(sourceUrl) ? sourceUrl : null
  const catalogue = submission.institution_id ? '/notices?institution_id=' + submission.institution_id : '/notices'
  const matchedRecord = candidateId ? '/notices?notice=' + candidateId : catalogue
  const transient = recent && recent.edgeId === outcome?.edge_id ? recent : null
  const evidence = transient?.evidence ?? outcome?.evidence ?? []
  const retrievalScore = transient?.candidateScore ?? outcome?.candidate_score
  const ResultIcon = outcome?.gated ? Clock3 : outcome?.label === 'consistent' ? CircleCheck : TriangleAlert
  const comparedFields = [
    { field: 'Issuer', submitted: submission.issuer, official: outcome?.candidate_issuer },
    { field: 'Notice date', submitted: submission.notice_date, official: outcome?.candidate_notice_date },
    { field: 'Deadline', submitted: submission.deadline, official: outcome?.candidate_deadline },
  ]
  const proof = verify?.details
  const hashPassed = proof?.integrity_ok
  const hasMerkleProof = typeof proof?.recomputed_root === 'string' && typeof proof?.stored_root === 'string'
  const transactionUrl = proof?.explorer_transaction_url

  return (
    <div className="stack result-workspace">
      {back}
      <header className="page-heading">
        <div><h1>Verification result</h1><p className="muted">Submission #{submission.id}</p></div>
        {outcome && <LabelBadge label={outcome.label} />}
      </header>
      <div className={'result-overview ' + (outcome?.label === 'consistent' ? 'result-overview-ok' : '')}>
        <div className="outcome-summary">
          <span className="result-icon"><ResultIcon size={24} aria-hidden="true" /></span>
          <div>
            <h2>{outcome?.gated ? 'In the review queue' : advice?.title ?? 'Comparison unavailable'}</h2>
            <p>{advice?.summary ?? 'No saved comparison is available for this submission.'}</p>
            {reviewed && <p className="review-state"><CircleCheck size={16} aria-hidden="true" /> Reviewed by a human reviewer</p>}
          </div>
        </div>
        <aside className="next-step">
          <h3>Suggested next step</h3>
          <p>{outcome?.gated ? 'A reviewer will look at this submission. Check the official notice board in the meantime.' : advice?.next ?? 'Look for the notice in the official catalogue.'}</p>
          <div className="row">
            {sourceLink ? (
              <a className="button" href={sourceLink} target="_blank" rel="noreferrer">Open official source <ArrowUpRight size={17} aria-hidden="true" /></a>
            ) : (
              <Link className="button" to={matchedRecord}>{candidateId ? 'Open matched record' : 'Browse official notices'} <ArrowRight size={17} aria-hidden="true" /></Link>
            )}
            {outcome?.gated && <button type="button" className="text-button" onClick={() => setAttempt(attempt + 1)}>Refresh review status</button>}
          </div>
        </aside>
      </div>

      <section className="card" aria-labelledby="comparison-title">
        <div className="section-title">
          <span className="section-icon"><GitCompareArrows size={22} aria-hidden="true" /></span>
          <div><h2 id="comparison-title">Compare the details</h2><p className="muted">
            {candidateId ? [outcome?.candidate_institution, 'Official notice #' + candidateId].filter(Boolean).join(' · ') : 'No official match was found for this submission.'}
          </p></div>
        </div>
        {candidateId && (
          <div className="table-wrap">
            <table className="comparison-table">
              <thead><tr><th scope="col">Field</th><th scope="col">Your notice</th><th scope="col">Official match</th></tr></thead>
              <tbody>{comparedFields.map(({ field, submitted, official }) => (
                <tr key={field} className={submitted && official && submitted.toLowerCase() !== official.toLowerCase() ? 'field-difference' : ''}>
                  <th scope="row">{field}</th><td>{submitted ?? '—'}</td><td>{official ?? '—'}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
        <div className="document-details">
          <details>
            <summary><FileText size={17} aria-hidden="true" /> Submitted notice and extracted fields</summary>
            {submission.fields.some((field) => field.value) && (
              <dl className="kv">{submission.fields.filter((field) => field.value).map(({ field_name, value }) => (
                <div className="kv-pair" key={field_name}><dt>{field_name.replace(/_/g, ' ')}</dt><dd>{value}</dd></div>
              ))}</dl>
            )}
            <pre className="pre">{submission.redacted_text || 'No readable notice text was saved.'}</pre>
          </details>
          {candidateId && (
            <details>
              <summary><Landmark size={17} aria-hidden="true" /> Matched official notice</summary>
              {sourceLink && <a href={sourceLink} target="_blank" rel="noreferrer">View original notice ↗</a>}
              <pre className="pre">{outcome?.candidate_text || 'No notice text is available for this source.'}</pre>
              {outcome?.candidate_supplemental_extractions?.map((extraction) => (
                <section key={extraction.extracted_text_sha256 + extraction.source_url}>
                  <h3>Extracted source document</h3>
                  <p className="muted">{extraction.extraction_quality} · {extraction.extraction_method}</p>
                  <pre className="pre">{extraction.extracted_text}</pre>
                </section>
              ))}
            </details>
          )}
          {outcome && (
            <details>
              <summary><FileText size={17} aria-hidden="true" /> Model evidence</summary>
              {outcome.model && <p className="muted">Comparison model: {outcome.model}</p>}
              {!reviewed && outcome.label !== 'unresolved' && <p className="muted">Raw model score: {outcome.confidence.toFixed(3)} (uncalibrated)</p>}
              {retrievalScore != null && <p className="muted">Retrieval score: {retrievalScore.toFixed(3)}</p>}
              {outcome.rationale && <p>{outcome.rationale}</p>}
              {evidence.some((item) => item !== outcome.rationale) && <ul>{evidence.filter((item) => item !== outcome.rationale).map((item, index) => <li key={index}>{item}</li>)}</ul>}
            </details>
          )}
        </div>
      </section>

      {candidateId && (
        <section className="card integrity-card" aria-labelledby="integrity-title">
          <div className="section-title">
            <span className="section-icon"><Fingerprint size={22} aria-hidden="true" /></span>
            <div><h2 id="integrity-title">Official notice integrity</h2><p className="muted">Check the stored content hash and Merkle proof.</p></div>
          </div>
          <div className="row">
            <button type="button" disabled={verifying} onClick={() => void runVerify(candidateId, false)}><ShieldCheck size={17} aria-hidden="true" /> Verify integrity</button>
            <button type="button" className="btn-secondary" disabled={verifying} onClick={() => void runVerify(candidateId, true)}>Simulate tampering</button>
          </div>
          {verifying && <p className="muted" role="status">Checking the stored proof…</p>}
          {verifyError && <p className="error" role="alert">{verifyError}</p>}
          {verify && (
            <div className={'banner ' + (verify.tamper ? 'banner-bad' : verify.ok ? 'banner-ok' : '')} role="status">
              <strong>{INTEGRITY_MESSAGES[verify.integrity_status]}</strong>
              <div className="proof-checks">
                {typeof hashPassed === 'boolean' && <span>Hash check · {hashPassed ? 'Passed' : 'Failed'}</span>}
                {hasMerkleProof && <span>Merkle proof · {proof?.recomputed_root === proof?.stored_root ? 'Passed' : 'Failed'}</span>}
              </div>
              {typeof transactionUrl === 'string' && /^https:\/\//i.test(transactionUrl) && <a href={transactionUrl} target="_blank" rel="noreferrer">View Polygon Amoy transaction ↗</a>}
              <details><summary>Technical details</summary><pre className="pre">{JSON.stringify(proof, null, 2)}</pre></details>
            </div>
          )}
        </section>
      )}
    </div>
  )
}
