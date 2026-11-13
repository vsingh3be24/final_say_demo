import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import {
  RELATIONSHIP_LABELS,
  type BenchmarkStatusOut,
  type BenchmarkPairOut,
  type KappaResponse,
  type RelationshipLabel,
} from '../../api/types'

// Reviewer benchmark annotation screen with a kappa summary. Seed demo labels
// are identified separately from account-bound human annotations.
export default function BenchmarkPage() {
  const { user } = useAuth()
  const [pairs, setPairs] = useState<BenchmarkPairOut[]>([])
  const [status, setStatus] = useState<BenchmarkStatusOut | null>(null)
  const [kappa, setKappa] = useState<KappaResponse | null>(null)
  const [drafts, setDrafts] = useState<Record<number, RelationshipLabel>>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [savingId, setSavingId] = useState<number | null>(null)
  const [completing, setCompleting] = useState(false)

  const loadKappa = useCallback(async () => {
    try {
      const res = await api.get<KappaResponse>('/reviewer/benchmark/kappa')
      setKappa(res.data)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  const loadBenchmark = useCallback(async () => {
    try {
      const [pairRes, statusRes] = await Promise.all([
        api.get<BenchmarkPairOut[]>('/reviewer/benchmark/pairs'),
        api.get<BenchmarkStatusOut>('/reviewer/benchmark/status'),
      ])
      setPairs(pairRes.data)
      setStatus(statusRes.data)
      setDrafts(Object.fromEntries(
        pairRes.data
          .filter((pair) => pair.your_label)
          .map((pair) => [pair.id, pair.your_label as RelationshipLabel]),
      ))
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadBenchmark()
    void loadKappa()
  }, [loadBenchmark, loadKappa])

  const annotate = async (pairId: number) => {
    const pair = pairs.find((item) => item.id === pairId)
    const label = drafts[pairId] ?? pair?.your_label
    if (!label || status?.completed) return
    setSavingId(pairId)
    setError('')
    try {
      const response = await api.post<BenchmarkPairOut>('/reviewer/benchmark/annotate', {
        pair_id: pairId,
        label,
      })
      setPairs((current) => current.map((item) => item.id === pairId ? response.data : item))
      const statusResponse = await api.get<BenchmarkStatusOut>('/reviewer/benchmark/status')
      setStatus(statusResponse.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setSavingId(null)
    }
  }

  const complete = async () => {
    setCompleting(true)
    setError('')
    try {
      const response = await api.post<BenchmarkStatusOut>('/reviewer/benchmark/complete')
      setStatus(response.data)
      await loadKappa()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setCompleting(false)
    }
  }

  const savedCount = pairs.filter((pair) => pair.your_label !== null).length

  return (
    <div className="stack">
      <div className="card">
        <h1>Benchmark annotation</h1>
        <p className="muted">
          Your signed-in reviewer account records your annotations as {user?.email ?? 'the current user'}.
          Pair labels and reviewer progress stay hidden from other reviewers. Generated seed labels are not used for agreement.
        </p>
      </div>

      <div className="card">
        <h2>Cohen's kappa</h2>
        {kappa?.ready && kappa.kappa !== null ? (
          <>
            <p className="result-head">
              <span className="kappa">{kappa.kappa.toFixed(4)}</span>
              <span className="muted">
                {kappa.annotators.join(' vs ') || 'not enough annotators'} ·{' '}
                {kappa.pairs_compared} shared pairs
              </span>
            </p>
            <pre className="pre">{JSON.stringify(kappa.per_label, null, 2)}</pre>
          </>
        ) : (
          <p className="muted">Agreement stays hidden until two reviewers independently label every pair and submit their passes.</p>
        )}
      </div>

      <div className="card">
        <h2>Pairs</h2>
        {loading ? (
          <p className="muted">Loading…</p>
        ) : pairs.length === 0 ? (
          <p className="muted">
            No real pairs have been curated yet. An Admin can add actual student
            comparisons or source-linked official revision pairs to start a
            blind benchmark pass.
          </p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Pair type</th>
                <th>Earlier or submitted notice</th>
                <th>Later or reference notice</th>
                <th>Your label (private)</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {pairs.map((p) => (
                <tr key={p.id}>
                  <td>
                    {p.pair_kind === 'source_revision' ? 'Official revision' : 'Student comparison'}
                    {p.institution_name && <p className="muted">{p.institution_name}</p>}
                  </td>
                  <td>
                    <strong>{p.left_title ?? `Notice #${p.submission_id}`}</strong>
                    <pre className="pre">{p.submission_text ?? ''}</pre>
                  </td>
                  <td>
                    <strong>{p.right_title ?? `Notice #${p.official_id}`}</strong>
                    <pre className="pre">{p.official_text ?? ''}</pre>
                  </td>
                  <td>
                    <select
                      value={drafts[p.id] ?? p.your_label ?? ''}
                      disabled={Boolean(status?.completed)}
                      onChange={(ev) =>
                        setDrafts({
                          ...drafts,
                          [p.id]: ev.target.value as RelationshipLabel,
                        })
                      }
                    >
                      <option value="" disabled>Select a label</option>
                      {RELATIONSHIP_LABELS.map((l) => (
                        <option key={l} value={l}>
                          {l}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <button
                      className="btn-secondary"
                      disabled={savingId === p.id || Boolean(status?.completed) || !drafts[p.id]}
                      onClick={() => annotate(p.id)}
                    >
                      {savingId === p.id ? 'Saving…' : 'Save'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {!loading && pairs.length > 0 && (
          <div className="stack">
            <p className="muted">Saved by you: {status?.annotated_count ?? savedCount} / {status?.pair_count ?? pairs.length}</p>
            {status?.completed ? (
              <div className="banner banner-ok" role="status">
                Your labels are submitted and locked. Agreement becomes visible after the second reviewer submits.
              </div>
            ) : (
              <button
                onClick={complete}
                disabled={completing || (status?.annotated_count ?? savedCount) !== pairs.length}
              >
                {completing ? 'Submitting…' : 'Submit completed blind pass'}
              </button>
            )}
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
