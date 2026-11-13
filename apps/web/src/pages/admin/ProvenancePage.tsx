import { useState } from 'react'
import { api, errorMessage } from '../../api/client'
import type { MerkleBuildResponse } from '../../api/types'

export default function ProvenancePage() {
  const [result, setResult] = useState<MerkleBuildResponse | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [day, setDay] = useState(() => new Date().toISOString().slice(0, 10))

  const buildToday = async () => {
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const response = await api.post<MerkleBuildResponse>('/provenance/build', { day })
      setResult(response.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const retryAnchor = async () => {
    if (!result) return
    setBusy(true)
    setError('')
    try {
      const response = await api.post<MerkleBuildResponse>(`/provenance/retry/${result.root_id}`)
      setResult(response.data)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h1>Integrity anchoring</h1>
        <p className="muted">
          Build or refresh a Merkle root for notices created on the selected UTC
          date. Existing proofs are updated when a new notice was added later that
          day. Local mode uses a hash chain; Polygon mode reports its transaction
          and receipt state.
        </p>
        <label className="field">
          <span>Notice creation date (UTC)</span>
          <input type="date" value={day} onChange={(event) => setDay(event.target.value)} />
        </label>
        <button onClick={buildToday} disabled={busy}>
          {busy ? 'Building root…' : 'Build selected date’s root'}
        </button>
        {error && <p className="error">{error}</p>}
      </div>
      {result && (
        <div className="card">
          <h2>Root #{result.root_id} · {result.day}</h2>
          <dl className="kv">
            <dt>Notices</dt><dd>{result.leaf_count}</dd>
            <dt>Anchor mode</dt><dd>{result.anchor_kind}</dd>
            <dt>Status</dt><dd>{result.anchor_status}</dd>
            <dt>Chain</dt><dd>{result.anchor_chain_id ?? '—'}</dd>
            <dt>Network</dt><dd>{result.anchor_network ?? 'Local hash chain'}</dd>
            <dt>Contract</dt><dd className="mono">{result.anchor_contract_address ?? '—'}</dd>
            <dt>Publisher</dt><dd className="mono">{result.anchor_issuer_address ?? '—'}</dd>
            <dt>Issuer-set hash</dt><dd className="mono">{result.anchor_issuer_id ?? '—'}</dd>
            <dt>Transaction status</dt><dd>{result.anchor_status}</dd>
            <dt>Block</dt><dd>{result.anchor_block_number ?? '—'}</dd>
            <dt>Anchored at</dt><dd>{result.anchor_timestamp ? new Date(result.anchor_timestamp).toLocaleString() : '—'}</dd>
            <dt>Transaction hash</dt><dd className="mono">{result.anchor_ref ?? '—'}</dd>
            <dt>Batch ID</dt><dd className="mono">{result.anchor_batch_id ?? '—'}</dd>
            {result.anchor_error && <><dt>Detail</dt><dd>{result.anchor_error}</dd></>}
          </dl>
          {result.anchor_kind === 'polygon' && result.anchor_ref && (
            <p>
              <a href={`https://amoy.polygonscan.com/tx/${result.anchor_ref}`} target="_blank" rel="noreferrer">
                Open transaction on Polygon Amoy
              </a>
            </p>
          )}
          {result.anchor_kind === 'polygon' && result.anchor_contract_address && (
            <p>
              <a href={`https://amoy.polygonscan.com/address/${result.anchor_contract_address}`} target="_blank" rel="noreferrer">
                Open contract on Polygon Amoy
              </a>
            </p>
          )}
          <p className="mono">{result.root_hash}</p>
          {result.anchor_kind === 'polygon' && ['pending', 'failed'].includes(result.anchor_status) && (
            <button className="btn-secondary" disabled={busy} onClick={retryAnchor}>
              {busy ? 'Checking transaction…' : 'Check or retry transaction'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
