import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, errorMessage } from '../../api/client'
import type {
  CandidateOut,
  ComparisonResponse,
  NoticeDetail,
  VerifyResponse,
} from '../../api/types'
import { loadResult, saveResult } from '../../api/resultCache'
import LabelBadge from '../../components/LabelBadge'

// The result / evidence-trail screen for a submission: shows the relationship
// label + model score where a relationship was resolved, extracted fields,
// the matched candidate,
// the model rationale, and an integrity-check button.
export default function ResultPage() {
  const { id } = useParams<{ id: string }>()
  const submissionId = Number(id)

  const [submission, setSubmission] = useState<NoticeDetail | null>(null)
  const [candidates, setCandidates] = useState<CandidateOut[]>([])
  const [verify, setVerify] = useState<VerifyResponse | null>(null)
  const [outcome, setOutcome] = useState<ComparisonResponse | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [verifying, setVerifying] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const cachedOutcome = loadResult(submissionId)
    setOutcome(cachedOutcome)
    try {
      const [sub, cands] = await Promise.all([
        api.get<NoticeDetail>(`/notices/${submissionId}`),
        api.get<CandidateOut[]>(`/notices/${submissionId}/candidates`),
      ])
      setSubmission(sub.data)
      setCandidates(cands.data)
      try {
        const persisted = await api.get<ComparisonResponse>(
          `/ingest/submissions/${submissionId}/result`,
        )
        setOutcome(persisted.data)
        saveResult(persisted.data)
      } catch (err) {
        // Keep the immediate local result visible when the persisted-result
        // endpoint is temporarily unavailable or an older backend is running.
        if (!cachedOutcome) setError(errorMessage(err))
      }
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [submissionId])

  useEffect(() => {
    void load()
  }, [load, submissionId])

  const runVerify = async (tamper: boolean) => {
    const officialNoticeId = outcome?.candidate_id ?? candidates[0]?.notice.id
    if (!officialNoticeId) {
      setError('No matched official notice is available to verify.')
      return
    }
    setVerifying(true)
    setError('')
    try {
      const res = await api.get<VerifyResponse>(
        `/provenance/verify/${officialNoticeId}`,
        { params: { tamper } },
      )
      setVerify(res.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setVerifying(false)
    }
  }

  if (loading) return <p className="muted">Loading result…</p>
  if (error && !submission) return <p className="error">{error}</p>
  if (!submission) return <p className="muted">No submission found.</p>

  const topCandidate = candidates[0]
  const matchedCandidate = candidates.find(
    (item) => item.notice.id === outcome?.candidate_id,
  )?.notice ?? topCandidate?.notice
  const hasExtractedSourceDocument = Boolean(
    outcome?.candidate_supplemental_extractions?.some(
      (item) => item.extraction_quality === 'extracted' && item.extracted_text.trim(),
    ),
  )
  const listingOnlyMatch = Boolean(
    matchedCandidate &&
      !hasExtractedSourceDocument &&
      (['listing_only', 'unextractable'].includes(matchedCandidate.extraction_quality) ||
        (matchedCandidate.extraction_quality === 'unknown' &&
          /official listing\s*:/i.test(outcome?.candidate_text ?? ''))),
  )
  const integrityMessage = (status: VerifyResponse['integrity_status']) => {
    switch (status) {
      case 'VERIFIED': return 'Public Polygon Amoy anchor and notice integrity verified.'
      case 'LOCAL_VERIFIED': return 'Local hash and Merkle proof match. This notice is not anchored to a public chain.'
      case 'TAMPERED': return 'Tampering detected: the notice hash or Merkle proof does not match.'
      case 'PENDING': return 'The anchor transaction is pending confirmation.'
      case 'VERIFICATION_UNAVAILABLE': return 'The public chain could not be reached; verification is unavailable.'
      default: return 'No confirmed public blockchain anchor exists for this notice.'
    }
  }
  const detailText = (key: string) => {
    const value = verify?.details[key]
    return typeof value === 'string' ? value : null
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Verification result</h1>
        <p className="muted">Submission #{submission.id}</p>
        {outcome ? (
          <div className="stack-sm">
            <p className="result-head">
              <LabelBadge label={outcome.label} />
              {outcome.label !== 'unresolved' && (
                <span className="confidence">
                  raw model score {outcome.confidence.toFixed(3)} (uncalibrated)
                </span>
              )}
              {outcome.gated && <span className="tag">routed to review</span>}
            </p>
            <p>
              <strong>Rationale:</strong> {outcome.rationale}
            </p>
            <p className="muted">
              Scores are raw model rankings, not calibrated probabilities. Results marked
              unresolved are routed to review; other labels are applied only above the
              configured threshold.
            </p>
            {outcome.evidence && outcome.evidence.length > 0 && (
              <div>
                <strong>Comparison evidence</strong>
                <ul>{outcome.evidence.map((item, index) => <li key={index}>{item}</li>)}</ul>
              </div>
            )}
            <p className="muted">
              Model: {outcome.model || 'mock'} · edge status: {outcome.status}
            </p>
          </div>
        ) : (
          <p className="muted">
            The relationship label is shown right after submitting. Re-submit from{' '}
            <Link to="/submit">Submit</Link> to see it again.
          </p>
        )}
        {outcome?.candidate_id || topCandidate ? (
          <p>
            Matched against official notice <strong>#{outcome?.candidate_id ?? topCandidate?.notice.id}</strong>{' '}
            {outcome?.candidate_score != null && `(combined retrieval rank ${outcome.candidate_score.toFixed(3)})`}
          </p>
        ) : (
          <p className="muted">No candidate official notice was found for this submission.</p>
        )}
        {listingOnlyMatch && (
          <div className="banner" role="status">
            <strong>Official document text is unavailable for this match.</strong>
            <p>
              FinalSay found a related portal listing, but could not verify its PDF or
              attachment. Any relationship that depends on changed dates is sent for
              review instead of being presented as confirmed.
            </p>
          </div>
        )}
      </div>

      <div className="card">
        <h2>Extracted fields (evidence)</h2>
        {submission.fields.length === 0 ? (
          <p className="muted">No fields extracted.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Field</th>
                <th>Value</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {submission.fields.map((f) => (
                <tr key={f.field_name}>
                  <td>{f.field_name}</td>
                  <td>{f.value ?? <span className="muted">—</span>}</td>
                  <td>{f.confidence != null ? f.confidence.toFixed(2) : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {submission.redacted_text && (
          <>
            <h3>Redacted text</h3>
            <pre className="pre">{submission.redacted_text}</pre>
          </>
        )}
      </div>

      {(outcome?.candidate_id || topCandidate) && (
        <div className="card">
          <h2>Closest official notice</h2>
          <dl className="kv">
            <dt>Notice</dt>
            <dd>#{outcome?.candidate_id ?? topCandidate?.notice.id}</dd>
            <dt>Institution</dt>
            <dd>{outcome?.candidate_institution ?? '—'}</dd>
            <dt>Issuer</dt>
            <dd>{outcome?.candidate_issuer ?? topCandidate?.notice.issuer ?? '—'}</dd>
            <dt>Date</dt>
            <dd>{outcome?.candidate_notice_date ?? topCandidate?.notice.notice_date ?? '—'}</dd>
            <dt>Deadline</dt>
            <dd>{outcome?.candidate_deadline ?? topCandidate?.notice.deadline ?? '—'}</dd>
            <dt>Audience</dt>
            <dd>{topCandidate?.notice.audience ?? '—'}</dd>
            <dt>Source</dt>
            <dd>{outcome?.candidate_source_url ? <a href={outcome.candidate_source_url} target="_blank" rel="noreferrer">{outcome.candidate_source_url}</a> : '—'}</dd>
            <dt>Retrieved</dt>
            <dd>{topCandidate?.notice.retrieved_at ? new Date(topCandidate.notice.retrieved_at).toLocaleString() : '—'}</dd>
            <dt>Content hash</dt>
            <dd className="mono">{topCandidate?.notice.sha256 ?? '—'}</dd>
          </dl>
          {outcome?.candidate_text && <><h3>Official notice text</h3><pre className="pre">{outcome.candidate_text}</pre></>}
          {outcome?.candidate_supplemental_extractions?.map((extraction) => (
            <section key={`${extraction.source_url}-${extraction.extracted_text_sha256}`}>
              <h3>Additional text extracted from the linked document</h3>
              <p className="muted">{extraction.extraction_quality} · {extraction.extraction_method} · <a href={extraction.source_url} target="_blank" rel="noreferrer">Source document</a></p>
              <pre className="pre">{extraction.extracted_text}</pre>
            </section>
          ))}
          <Link to={`/notices`}>Browse all official notices</Link>
        </div>
      )}

      <div className="card">
        <h2>Official notice integrity</h2>
        <p className="muted">
          Verify the matched official notice’s SHA-256 hash and Merkle proof against its recorded anchor.
        </p>
        <div className="row">
          <button disabled={verifying || (!outcome?.candidate_id && !topCandidate)} onClick={() => runVerify(false)}>
            Verify official notice
          </button>
          <button
            className="btn-secondary"
            disabled={verifying || (!outcome?.candidate_id && !topCandidate)}
            onClick={() => runVerify(true)}
          >
            Simulate tamper
          </button>
        </div>
        {verify && (
          <div className={`banner ${verify.integrity_status === 'TAMPERED' ? 'banner-bad' : verify.integrity_status === 'VERIFIED' || verify.integrity_status === 'LOCAL_VERIFIED' ? 'banner-ok' : ''}`}>
            <strong>{integrityMessage(verify.integrity_status)}</strong>
            <dl className="kv">
              <dt>Notice</dt><dd>#{outcome?.candidate_id ?? topCandidate?.notice.id}</dd>
              <dt>Integrity status</dt><dd>{verify.integrity_status}</dd>
              <dt>Hash check</dt><dd>{verify.details.integrity_ok === true ? 'Passed' : 'Failed'}</dd>
              <dt>Merkle proof</dt><dd>{verify.details.recomputed_root === verify.details.stored_root ? 'Passed' : 'Failed'}</dd>
              <dt>Network</dt><dd>{detailText('anchor_network') ?? (detailText('anchor_kind') === 'local' ? 'Local hash chain' : '—')}</dd>
              <dt>Publisher</dt><dd className="mono">{detailText('anchor_issuer_address') ?? '—'}</dd>
              <dt>Issuer-set hash</dt><dd className="mono">{detailText('anchor_issuer_id') ?? '—'}</dd>
              <dt>Transaction status</dt><dd>{detailText('transaction_status') ?? detailText('anchor_status') ?? '—'}</dd>
              <dt>Transaction hash</dt><dd className="mono">{detailText('transaction_hash') ?? '—'}</dd>
              <dt>Contract</dt><dd className="mono">{detailText('anchor_contract_address') ?? '—'}</dd>
              <dt>Block</dt><dd>{detailText('anchor_block_number') ?? '—'}</dd>
              <dt>Timestamp</dt><dd>{detailText('anchor_timestamp') ? new Date(detailText('anchor_timestamp')!).toLocaleString() : '—'}</dd>
            </dl>
            {detailText('explorer_transaction_url') && (
              <p><a href={detailText('explorer_transaction_url')!} target="_blank" rel="noreferrer">Open transaction on Polygon Amoy</a></p>
            )}
            {detailText('explorer_contract_url') && (
              <p><a href={detailText('explorer_contract_url')!} target="_blank" rel="noreferrer">Open contract on Polygon Amoy</a></p>
            )}
            {detailText('anchor_error') && <p>{detailText('anchor_error')}</p>}
            <pre className="pre">{JSON.stringify(verify.details, null, 2)}</pre>
          </div>
        )}
      </div>

      {error && <p className="error">{error}</p>}
    </div>
  )
}
