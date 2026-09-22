import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Typography } from '@mui/material'
import type { ErpRecord } from '../api/types'
import { erpFieldLabel } from './erpRecordLabels'

interface ErpRecordDialogProps {
  open: boolean
  record: ErpRecord | null
  onClose: () => void
}

export function ErpRecordDialog({ open, record, onClose }: ErpRecordDialogProps) {
  return <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
    <DialogTitle>ERP supplier record {record?.erp_supplier_id}</DialogTitle>
    <DialogContent>
      <Typography color="text.secondary" sx={{ mb: 2 }}>Retrieved from the mock ERP through the MCP get_supplier_record tool.</Typography>
      {record && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)' }, gap: 1.5 }}>
        {Object.entries(record.payload).map(([name, value]) => <Box key={name} sx={{ p: 1.5, bgcolor: 'action.hover', borderRadius: 1.5 }}>
          <Typography variant="caption" color="text.secondary">{erpFieldLabel(name)}</Typography>
          <Typography variant="body2" fontWeight={650} sx={{ overflowWrap: 'anywhere' }}>{value == null || value === '' ? 'Not provided' : String(value)}</Typography>
        </Box>)}
      </Box>}
    </DialogContent>
    <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
  </Dialog>
}
