import type { RelationshipLabel } from '../api/types'

export default function LabelBadge({ label }: { label: RelationshipLabel }) {
  return (
    <span className={`badge badge-${label}`}>
      {label}
    </span>
  )
}
