import { Chip } from '@mui/material'
import type { ProcessingStatus, SupplierStatus } from '../api/types'

interface StatusChipProps {
  status: SupplierStatus | ProcessingStatus
}

const labels: Record<StatusChipProps['status'], string> = {
  new: 'New',
  processing: 'Processing',
  needs_review: 'Needs review',
  approved: 'Approved',
  rejected: 'Rejected',
  ready: 'Ready',
  failed: 'Failed',
}

export function StatusChip({ status }: StatusChipProps) {
  const color = status === 'approved' || status === 'ready'
    ? 'success'
    : status === 'failed' || status === 'rejected'
      ? 'error'
      : status === 'needs_review'
        ? 'warning'
        : 'default'

  return <Chip label={labels[status]} color={color} size="small" />
}

