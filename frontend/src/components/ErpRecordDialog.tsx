import { Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from '@mui/material'
import type { ErpRecord } from '../api/types'
import { erpFieldLabel } from './erpRecordLabels'

interface ErpRecordDialogProps {
  open: boolean
  record: ErpRecord | null
  onClose: () => void
}

export function ErpRecordDialog({ open, record, onClose }: ErpRecordDialogProps) {
  return <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
    <DialogTitle>Vendor Master · {record?.vendor_id}</DialogTitle>
    <DialogContent>
      <Typography color="text.secondary" sx={{ mb: 2 }}>Retrieved live from the downstream mock ERP through the MCP get_supplier_record tool.</Typography>
      {record && <><Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5} sx={{ mb: 2 }}>
        {[
          ['Vendor ID', record.vendor_id, 'Primary Vendor Master identifier'],
          ['ERP record ID', record.erp_record_id, 'Downstream approval workflow record'],
          ['Portal reference', record.supplier_reference, 'Onboarding application'],
        ].map(([label, value, helper]) => <Box key={label} sx={{ p: 1.5, bgcolor: '#F3F8FD', border: 1, borderColor: 'primary.light', borderRadius: 1.5, flex: 1 }}><Typography variant="caption" color="text.secondary">{label}</Typography><Typography fontWeight={750} sx={{ overflowWrap: 'anywhere' }}>{value || 'Not available'}</Typography><Typography variant="caption" color="text.secondary">{helper}</Typography></Box>)}
      </Stack><Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)' }, gap: 1.5 }}>
        {Object.entries(record.payload).filter(([name]) => name !== 'supplier_reference').map(([name, value]) => <Box key={name} sx={{ p: 1.5, bgcolor: 'action.hover', borderRadius: 1.5 }}>
          <Typography variant="caption" color="text.secondary">{erpFieldLabel(name)}</Typography>
          <Typography variant="body2" fontWeight={650} sx={{ overflowWrap: 'anywhere' }}>{value == null || value === '' ? 'Not provided' : String(value)}</Typography>
        </Box>)}
      </Box></>}
    </DialogContent>
    <DialogActions><Button onClick={onClose}>Close</Button></DialogActions>
  </Dialog>
}
