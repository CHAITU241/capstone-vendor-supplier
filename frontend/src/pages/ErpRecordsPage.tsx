import ArrowBackRoundedIcon from '@mui/icons-material/ArrowBackRounded'
import DownloadRoundedIcon from '@mui/icons-material/DownloadRounded'
import OpenInNewRoundedIcon from '@mui/icons-material/OpenInNewRounded'
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded'
import SearchRoundedIcon from '@mui/icons-material/SearchRounded'
import StorageRoundedIcon from '@mui/icons-material/StorageRounded'
import TableRowsRoundedIcon from '@mui/icons-material/TableRowsRounded'
import VisibilityRoundedIcon from '@mui/icons-material/VisibilityRounded'
import {
  Alert, Box, Button, Card, CardContent, Chip, CircularProgress, InputAdornment,
  MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead,
  TablePagination, TableRow, TableSortLabel, TextField, Tooltip, Typography,
} from '@mui/material'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { ErpRecord } from '../api/types'
import { ErpRecordDialog } from '../components/ErpRecordDialog'
import {
  buildVendorMasterCsv, formatVendorMasterDate, toVendorMasterRow,
  vendorMasterColumns, type VendorMasterRow,
} from '../features/vendorMaster'

type SortKey = 'vendorId' | 'legalName' | 'status' | 'category' | 'country' | 'createdAt'
type SortDirection = 'asc' | 'desc'

const tableColumns: Array<{
  key: keyof VendorMasterRow
  label: string
  width: number
  sortKey?: SortKey
  kind?: 'status' | 'date' | 'multiline'
}> = [
  { key: 'vendorId', label: 'Vendor ID', width: 150, sortKey: 'vendorId' },
  { key: 'legalName', label: 'Vendor name', width: 230, sortKey: 'legalName' },
  { key: 'portalReference', label: 'Portal reference', width: 150 },
  { key: 'status', label: 'Status', width: 110, sortKey: 'status', kind: 'status' },
  { key: 'category', label: 'Category', width: 120, sortKey: 'category' },
  { key: 'subcategory', label: 'Subcategory', width: 150 },
  { key: 'contactName', label: 'Contact name', width: 160 },
  { key: 'contactPhone', label: 'Contact phone', width: 145 },
  { key: 'contactEmail', label: 'Contact email', width: 220 },
  { key: 'registeredAddress', label: 'Registered address', width: 260, kind: 'multiline' },
  { key: 'city', label: 'City', width: 120 },
  { key: 'state', label: 'State', width: 130 },
  { key: 'postalCode', label: 'ZIP / postal code', width: 135 },
  { key: 'country', label: 'Country', width: 120, sortKey: 'country' },
  { key: 'taxReference', label: 'Tax reference', width: 160 },
  { key: 'bankAccountNumber', label: 'Bank account number', width: 190 },
  { key: 'bankIfsc', label: 'Bank IFSC', width: 145 },
  { key: 'insuranceProvider', label: 'Insurance provider', width: 180 },
  { key: 'insuranceExpiry', label: 'Insurance expiry', width: 145 },
  { key: 'paymentTerms', label: 'Payment terms', width: 150 },
  { key: 'comments', label: 'Comments / notes', width: 230, kind: 'multiline' },
  { key: 'createdAt', label: 'ERP created at', width: 180, sortKey: 'createdAt', kind: 'date' },
  { key: 'updatedAt', label: 'ERP updated at', width: 180, kind: 'date' },
]

const groupHeaderSx = {
  bgcolor: '#0F4C81', color: 'common.white', py: .75, fontSize: 12,
  fontWeight: 750, letterSpacing: '.04em', textTransform: 'uppercase',
  borderColor: 'rgba(255,255,255,.2)',
}

function displayValue(value: unknown) {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

export function ErpRecordsPage() {
  const [records, setRecords] = useState<ErpRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [viewError, setViewError] = useState('')
  const [viewingRecordId, setViewingRecordId] = useState<string | null>(null)
  const [selectedRecord, setSelectedRecord] = useState<ErpRecord | null>(null)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [categoryFilter, setCategoryFilter] = useState('all')
  const [sortKey, setSortKey] = useState<SortKey>('createdAt')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')
  const [page, setPage] = useState(0)
  const [rowsPerPage, setRowsPerPage] = useState(10)
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null)

  const loadRecords = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setRecords(await api.listErpRecords())
      setPage(0)
      setRefreshedAt(new Date())
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The Vendor Master could not be loaded.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadRecords() }, [loadRecords])

  const rows = useMemo(() => records.map(toVendorMasterRow), [records])
  const categories = useMemo(() => [...new Set(rows.map((row) => row.category).filter(Boolean))].sort(), [rows])
  const statuses = useMemo(() => [...new Set(rows.map((row) => row.status).filter(Boolean))].sort(), [rows])
  const filteredRows = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase()
    return rows.filter((row) => {
      if (statusFilter !== 'all' && row.status !== statusFilter) return false
      if (categoryFilter !== 'all' && row.category !== categoryFilter) return false
      if (!normalizedQuery) return true
      return vendorMasterColumns.some((column) => String(row[column.key] ?? '').toLocaleLowerCase().includes(normalizedQuery))
    }).sort((left, right) => {
      const leftValue = String(left[sortKey] ?? '')
      const rightValue = String(right[sortKey] ?? '')
      const comparison = leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: 'base' })
      return sortDirection === 'asc' ? comparison : -comparison
    })
  }, [categoryFilter, query, rows, sortDirection, sortKey, statusFilter])
  const visibleRows = filteredRows.slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)
  const activeCount = rows.filter((row) => row.status.toLocaleLowerCase() === 'active').length

  function changeSort(nextKey: SortKey) {
    if (sortKey === nextKey) setSortDirection((current) => current === 'asc' ? 'desc' : 'asc')
    else { setSortKey(nextKey); setSortDirection('asc') }
    setPage(0)
  }

  async function viewErpRecord(row: VendorMasterRow) {
    setViewingRecordId(row.vendorId)
    setViewError('')
    try {
      setSelectedRecord(await api.getErpRecord(row.sourceSupplierId))
    } catch (recordError) {
      setViewError(recordError instanceof Error ? recordError.message : 'The ERP record could not be retrieved.')
    } finally {
      setViewingRecordId(null)
    }
  }

  function downloadCsv() {
    const blob = new Blob([buildVendorMasterCsv(filteredRows)], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `vendor-master-${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(link)
    link.click()
    link.remove()
    URL.revokeObjectURL(url)
  }

  return <Stack spacing={3}>
    <Button component={Link} to="/review" startIcon={<ArrowBackRoundedIcon />} sx={{ alignSelf: 'flex-start' }}>Back to reviewer workspace</Button>

    <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" alignItems={{ md: 'flex-start' }} spacing={2}>
      <Stack direction="row" spacing={1.25} alignItems="center">
        <Box sx={{ display: 'grid', placeItems: 'center', width: 42, height: 42, borderRadius: 1.5, bgcolor: '#EAF2F8', color: '#0F4C81' }}><TableRowsRoundedIcon /></Box>
        <Box><Typography variant="h4">Vendor Master</Typography><Typography color="text.secondary">Reviewed and accepted suppliers created in the downstream ERP.</Typography></Box>
      </Stack>
      <Stack direction="row" spacing={1}>
        <Button variant="outlined" startIcon={<RefreshRoundedIcon />} disabled={loading} onClick={() => void loadRecords()}>Refresh</Button>
        <Button variant="contained" startIcon={<DownloadRoundedIcon />} disabled={loading || filteredRows.length === 0} onClick={downloadCsv}>Download CSV ({filteredRows.length})</Button>
      </Stack>
    </Stack>

    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, 1fr)' }, gap: 1.5 }}>
      {[
        ['ERP vendors', rows.length, 'Approved records in the Vendor Master'],
        ['Active vendors', activeCount, 'Available for procurement'],
        ['Categories', categories.length, refreshedAt ? `Last refreshed ${refreshedAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Waiting for ERP'],
      ].map(([label, value, detail]) => <Card key={String(label)}><CardContent sx={{ py: 2.25 }}><Typography variant="caption" color="text.secondary" fontWeight={700}>{label}</Typography><Typography variant="h5" sx={{ mt: .25 }}>{value}</Typography><Typography variant="caption" color="text.secondary">{detail}</Typography></CardContent></Card>)}
    </Box>

    {error && <Alert severity="error" action={<Button color="inherit" size="small" onClick={() => void loadRecords()}>Retry</Button>}>{error}</Alert>}
    {viewError && <Alert severity="error" onClose={() => setViewError('')}>{viewError}</Alert>}

    <Paper variant="outlined" sx={{ overflow: 'hidden', borderRadius: 2 }}>
      <Stack direction={{ xs: 'column', lg: 'row' }} spacing={1.25} alignItems={{ lg: 'center' }} sx={{ p: 2, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}>
        <TextField
          size="small" placeholder="Search Vendor ID, name, tax, bank, contact…" value={query}
          onChange={(event) => { setQuery(event.target.value); setPage(0) }} sx={{ minWidth: { lg: 360 }, flexGrow: 1 }}
          slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchRoundedIcon fontSize="small" /></InputAdornment> } }}
        />
        <TextField select size="small" label="Status" value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(0) }} sx={{ minWidth: 150 }}>
          <MenuItem value="all">All statuses</MenuItem>{statuses.map((status) => <MenuItem key={status} value={status}>{status}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Category" value={categoryFilter} onChange={(event) => { setCategoryFilter(event.target.value); setPage(0) }} sx={{ minWidth: 180 }}>
          <MenuItem value="all">All categories</MenuItem>{categories.map((category) => <MenuItem key={category} value={category}>{category}</MenuItem>)}
        </TextField>
        <Chip label={`${filteredRows.length} matching`} color="primary" variant="outlined" />
      </Stack>

      {loading ? <Box sx={{ display: 'grid', placeItems: 'center', py: 10 }}><CircularProgress /></Box> : rows.length === 0 ? <Box sx={{ py: 8, textAlign: 'center' }}><StorageRoundedIcon sx={{ fontSize: 48, color: 'primary.main', mb: 1 }} /><Typography variant="h6">No ERP vendors yet</Typography><Typography color="text.secondary">A vendor appears here only after policy review, ERP validation, and explicit reviewer acceptance.</Typography></Box> : <>
        <TableContainer sx={{ maxHeight: '62vh' }}>
          <Table stickyHeader size="small" aria-label="Vendor Master" sx={{ minWidth: 3450, tableLayout: 'fixed' }}>
            <TableHead>
              <TableRow><TableCell colSpan={3} sx={{ ...groupHeaderSx, top: 0, zIndex: 4 }}>Vendor identity</TableCell><TableCell colSpan={3} sx={{ ...groupHeaderSx, top: 0, zIndex: 4 }}>Classification</TableCell><TableCell colSpan={8} sx={{ ...groupHeaderSx, top: 0, zIndex: 4 }}>Contact and address</TableCell><TableCell colSpan={3} sx={{ ...groupHeaderSx, top: 0, zIndex: 4 }}>Tax and payment</TableCell><TableCell colSpan={4} sx={{ ...groupHeaderSx, top: 0, zIndex: 4 }}>Risk and terms</TableCell><TableCell colSpan={2} sx={{ ...groupHeaderSx, top: 0, zIndex: 4 }}>Lifecycle</TableCell><TableCell rowSpan={2} align="center" sx={{ ...groupHeaderSx, position: 'sticky', top: 0, right: 0, zIndex: 5 }}>Actions</TableCell></TableRow>
              <TableRow>{tableColumns.map((column) => <TableCell key={column.key} sx={{ top: 31, width: column.width, minWidth: column.width, bgcolor: '#EAF2F8', color: '#16324F', fontWeight: 750, borderBottom: '2px solid #9CBBD4', zIndex: 3 }} sortDirection={sortKey === column.sortKey ? sortDirection : false}>{column.sortKey ? <TableSortLabel active={sortKey === column.sortKey} direction={sortKey === column.sortKey ? sortDirection : 'asc'} onClick={() => changeSort(column.sortKey!)}>{column.label}</TableSortLabel> : column.label}</TableCell>)}</TableRow>
            </TableHead>
            <TableBody>
              {visibleRows.map((row, rowIndex) => <TableRow key={row.vendorId} hover sx={{ bgcolor: rowIndex % 2 ? '#F7FAFC' : 'background.paper', '&:hover': { bgcolor: '#EDF5FC !important' } }}>
                {tableColumns.map((column) => {
                  const rawValue = row[column.key]
                  const value = column.kind === 'date' ? formatVendorMasterDate(String(rawValue)) : displayValue(rawValue)
                  return <TableCell key={column.key} sx={{ width: column.width, minWidth: column.width, py: 1, whiteSpace: column.kind === 'multiline' ? 'normal' : 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', verticalAlign: 'top' }}>
                    {column.kind === 'status' ? <Chip label={value} size="small" color={String(rawValue).toLocaleLowerCase() === 'active' ? 'success' : 'default'} sx={{ textTransform: 'capitalize' }} /> : <Tooltip title={value === '—' ? '' : value} enterDelay={700}><Typography variant="body2" fontWeight={column.key === 'vendorId' || column.key === 'legalName' ? 650 : 400} color={value === '—' ? 'text.disabled' : column.key === 'vendorId' ? 'primary.main' : 'text.primary'} sx={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</Typography></Tooltip>}
                  </TableCell>
                })}
                <TableCell align="center" sx={{ position: 'sticky', right: 0, zIndex: 2, bgcolor: rowIndex % 2 ? '#F7FAFC' : 'background.paper', width: 210, minWidth: 210, py: .75 }}>
                  <Stack direction="row" spacing={.5} justifyContent="center">
                    <Tooltip title="Retrieve the full record from ERP"><span><Button size="small" startIcon={<VisibilityRoundedIcon />} disabled={viewingRecordId === row.vendorId} onClick={() => void viewErpRecord(row)}>{viewingRecordId === row.vendorId ? 'Loading…' : 'View'}</Button></span></Tooltip>
                    <Button component={Link} to={`/review/suppliers/${row.sourceSupplierId}`} size="small" endIcon={<OpenInNewRoundedIcon />}>Onboarding</Button>
                  </Stack>
                </TableCell>
              </TableRow>)}
              {visibleRows.length === 0 && <TableRow><TableCell colSpan={24} align="center" sx={{ py: 7 }}><Typography fontWeight={700}>No vendors match these filters</Typography><Typography variant="body2" color="text.secondary">Change the search or filter values.</Typography></TableCell></TableRow>}
            </TableBody>
          </Table>
        </TableContainer>
        <TablePagination component="div" count={filteredRows.length} page={Math.min(page, Math.max(Math.ceil(filteredRows.length / rowsPerPage) - 1, 0))} onPageChange={(_, nextPage) => setPage(nextPage)} rowsPerPage={rowsPerPage} onRowsPerPageChange={(event) => { setRowsPerPage(Number(event.target.value)); setPage(0) }} rowsPerPageOptions={[10, 25, 50]} labelRowsPerPage="Vendors per page" />
      </>}
    </Paper>

    <Alert severity="info">The Vendor Master is read-only in VendorLens. Changes to master data belong in the ERP; the onboarding record remains available as the review and evidence audit trail.</Alert>
    <ErpRecordDialog open={selectedRecord !== null} record={selectedRecord} onClose={() => setSelectedRecord(null)} />
  </Stack>
}
