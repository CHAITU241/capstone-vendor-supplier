import LaunchRoundedIcon from '@mui/icons-material/LaunchRounded'
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded'
import { Alert, Box, Button, Card, CardContent, Chip, CircularProgress, Divider, FormControl, InputLabel, MenuItem, Select, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from '@mui/material'
import { useCallback, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../api/client'
import type { AdminLangfuseCostGroup, AdminLangfuseScoreGroup, AdminMetricGroup, AdminObservability } from '../api/types'

const number = new Intl.NumberFormat()
const currency = new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 4 })

function duration(milliseconds: number) {
  return milliseconds >= 1000 ? `${(milliseconds / 1000).toFixed(1)}s` : `${milliseconds}ms`
}

function MetricCard({ label, value, helper }: { label: string; value: string; helper: string }) {
  return <Card variant="outlined"><CardContent>
    <Typography variant="caption" color="text.secondary" fontWeight={700}>{label.toUpperCase()}</Typography>
    <Typography variant="h4" sx={{ mt: .5 }}>{value}</Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{helper}</Typography>
  </CardContent></Card>
}

function IntegrationCard({ title, status, color, summary, detail, action }: {
  title: string
  status: string
  color: 'success' | 'warning' | 'error' | 'default'
  summary: string
  detail: string
  action?: ReactNode
}) {
  return <Card variant="outlined"><CardContent sx={{ height: '100%' }}>
    <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
      <Typography variant="h6">{title}</Typography>
      <Chip size="small" color={color} label={status} />
    </Stack>
    <Typography fontWeight={750} sx={{ mt: 2 }}>{summary}</Typography>
    <Typography variant="body2" color="text.secondary" sx={{ mt: .5 }}>{detail}</Typography>
    {action && <Box sx={{ mt: 2 }}>{action}</Box>}
  </CardContent></Card>
}

function CostByModel({ rows }: { rows: AdminLangfuseCostGroup[] }) {
  const largest = Math.max(...rows.map((row) => row.cost_usd), 0)
  return <Card><CardContent sx={{ p: 3 }}>
    <Typography variant="h6">Cost by model</Typography>
    <Typography variant="body2" color="text.secondary">Langfuse-calculated generation and embedding cost.</Typography>
    <Stack spacing={2} sx={{ mt: 2 }}>
      {rows.length === 0 && <Typography color="text.secondary">No priced model observations in this window.</Typography>}
      {rows.map((row) => <Box key={row.model}>
        <Stack direction="row" justifyContent="space-between" gap={2}>
          <Typography variant="body2" fontWeight={700} sx={{ overflowWrap: 'anywhere' }}>{row.model}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>{currency.format(row.cost_usd)} · {row.observations} observations</Typography>
        </Stack>
        <Box sx={{ mt: .75, height: 7, borderRadius: 9, bgcolor: 'action.hover', overflow: 'hidden' }}>
          <Box sx={{ width: `${largest ? Math.max(4, row.cost_usd / largest * 100) : 4}%`, height: '100%', bgcolor: 'primary.main', borderRadius: 9 }} />
        </Box>
      </Box>)}
    </Stack>
  </CardContent></Card>
}

function scoreValue(row: AdminLangfuseScoreGroup) {
  const isRate = row.average >= 0 && row.average <= 1 && /(success|rate|guard|completed)/i.test(row.name)
  return isRate ? `${(row.average * 100).toFixed(1)}%` : row.average.toFixed(2)
}

function QualityScores({ rows }: { rows: AdminLangfuseScoreGroup[] }) {
  return <Card><CardContent sx={{ p: 3 }}>
    <Typography variant="h6">Quality scores</Typography>
    <Typography variant="body2" color="text.secondary">Averages from the scores already emitted to Langfuse.</Typography>
    <Stack divider={<Divider flexItem />} sx={{ mt: 1.5 }}>
      {rows.length === 0 && <Typography color="text.secondary" sx={{ py: 1 }}>No numeric scores in this window.</Typography>}
      {rows.map((row) => <Stack key={row.name} direction="row" justifyContent="space-between" alignItems="center" spacing={2} sx={{ py: 1.15 }}>
        <Box><Typography variant="body2" fontWeight={700}>{row.name.replaceAll('_', ' ')}</Typography><Typography variant="caption" color="text.secondary">{row.count} scored traces</Typography></Box>
        <Typography variant="h6" color={row.average >= .95 && row.average <= 1 ? 'success.main' : 'text.primary'}>{scoreValue(row)}</Typography>
      </Stack>)}
    </Stack>
  </CardContent></Card>
}

function Breakdown({ title, rows }: { title: string; rows: AdminMetricGroup[] }) {
  const largest = Math.max(...rows.map((row) => row.calls), 1)
  return <Card><CardContent sx={{ p: 3 }}>
    <Typography variant="h6">{title}</Typography>
    <Stack spacing={2} sx={{ mt: 2 }}>
      {rows.length === 0 && <Typography color="text.secondary">No runs in this window.</Typography>}
      {rows.map((row) => <Box key={row.label}>
        <Stack direction="row" justifyContent="space-between" gap={2}>
          <Typography variant="body2" fontWeight={700} sx={{ overflowWrap: 'anywhere' }}>{row.label}</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>{row.calls} calls · {number.format(row.input_tokens + row.output_tokens)} tokens · {duration(row.average_latency_ms)}</Typography>
        </Stack>
        <Box sx={{ mt: .75, height: 7, borderRadius: 9, bgcolor: 'action.hover', overflow: 'hidden' }}>
          <Box sx={{ width: `${Math.max(4, row.calls / largest * 100)}%`, height: '100%', bgcolor: row.failures ? 'warning.main' : 'primary.main', borderRadius: 9 }} />
        </Box>
      </Box>)}
    </Stack>
  </CardContent></Card>
}

export function AdminObservabilityPanel() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState<AdminObservability | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try { setData(await api.adminObservability(days)) }
    catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not load observability metrics.') }
    finally { setLoading(false) }
  }, [days])

  useEffect(() => { void load() }, [load])

  if (loading && !data) return <Box sx={{ display: 'grid', placeItems: 'center', py: 8 }}><CircularProgress /></Box>
  if (!data) return <Alert severity="error">{error || 'Observability metrics are unavailable.'}</Alert>

  const totalTokens = data.input_tokens + data.output_tokens
  const groundingRate = data.question_runs ? data.grounded_answers / data.question_runs * 100 : 0

  return <Stack spacing={3}>
    <Stack direction={{ xs: 'column', md: 'row' }} justifyContent="space-between" gap={2} alignItems={{ md: 'center' }}>
      <Box>
        <Typography variant="h5">AI observability</Typography>
        <Typography color="text.secondary">Privacy-safe operational metrics from persisted VendorLens runs. Langfuse provides generation-level traces and cost analysis.</Typography>
      </Box>
      <Stack direction="row" spacing={1} alignItems="center">
        <FormControl size="small" sx={{ minWidth: 125 }}><InputLabel id="metrics-window">Window</InputLabel><Select labelId="metrics-window" label="Window" value={days} onChange={(event) => setDays(Number(event.target.value))}>
          <MenuItem value={7}>Last 7 days</MenuItem><MenuItem value={30}>Last 30 days</MenuItem><MenuItem value={90}>Last 90 days</MenuItem><MenuItem value={0}>All time</MenuItem>
        </Select></FormControl>
        <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => void load()} disabled={loading}>Refresh</Button>
      </Stack>
    </Stack>

    {error && <Alert severity="warning" onClose={() => setError('')}>{error}</Alert>}
    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' }, gap: 2 }}>
      <MetricCard label="Persisted AI runs" value={number.format(data.total_runs)} helper={`${data.successful_runs} succeeded · ${data.failed_runs} failed`} />
      <MetricCard label="Success rate" value={`${data.success_rate.toFixed(1)}%`} helper={`${data.in_progress_runs} currently processing`} />
      <MetricCard label="Total tokens" value={number.format(totalTokens)} helper={`${number.format(data.input_tokens)} input · ${number.format(data.output_tokens)} output`} />
      <MetricCard label="P95 latency" value={duration(data.p95_latency_ms)} helper={`${duration(data.average_latency_ms)} average`} />
    </Box>

    <Box>
      <Typography variant="h5">Integration health</Typography>
      <Typography color="text.secondary" variant="body2" sx={{ mt: .5 }}>Live status for the services that power document processing and supplier approval.</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 2, mt: 2 }}>
        <IntegrationCard
          title="Langfuse"
          status={data.langfuse_metrics_available ? 'Connected' : data.langfuse_configured ? 'Metrics unavailable' : 'Not configured'}
          color={data.langfuse_metrics_available ? 'success' : 'warning'}
          summary={data.langfuse_metrics_available ? `${number.format(data.langfuse_trace_count)} traces · ${currency.format(data.langfuse_total_cost_usd)}` : 'Tracing dashboard is not currently readable'}
          detail={`Content capture ${data.langfuse_content_capture ? 'enabled' : 'off (metadata only)'} · ${data.langfuse_score_count} scores`}
          action={data.langfuse_dashboard_url ? <Button component="a" href={data.langfuse_dashboard_url} target="_blank" rel="noreferrer" size="small" endIcon={<LaunchRoundedIcon />}>Open Langfuse</Button> : undefined}
        />
        <IntegrationCard
          title="OCR"
          status={data.ocr_enabled ? (data.failed_text_extractions ? 'Attention' : 'Healthy') : 'Disabled'}
          color={!data.ocr_enabled ? 'default' : data.failed_text_extractions ? 'warning' : 'success'}
          summary={`${number.format(data.ocr_assisted_documents)} OCR-assisted documents`}
          detail={`${data.native_documents} native documents · ${data.ocr_pages} OCR pages · ${data.failed_text_extractions} failed extractions`}
        />
        <IntegrationCard
          title="ERP"
          status={data.erp_failures ? 'Attention' : data.erp_attempts ? 'Healthy' : 'Ready'}
          color={data.erp_failures ? 'warning' : 'success'}
          summary={`${number.format(data.erp_attempts)} tool calls · ${data.erp_failures} failed`}
          detail={`${data.erp_mode} · ${duration(data.erp_average_latency_ms)} average latency`}
        />
      </Box>
    </Box>

    <Box>
      <Typography variant="h5">Langfuse cost and quality</Typography>
      <Typography color="text.secondary" variant="body2" sx={{ mt: .5 }}>Read-only telemetry for the selected window. No prompts, document text, or outputs are retrieved.</Typography>
      {data.langfuse_metrics_error && <Alert severity="warning" sx={{ mt: 2 }}>{data.langfuse_metrics_error}</Alert>}
      {!data.langfuse_configured && <Alert severity="info" sx={{ mt: 2 }}>Add Langfuse credentials to populate cost, trace, and score metrics.</Alert>}
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, 1fr)', lg: 'repeat(4, 1fr)' }, gap: 2, mt: 2 }}>
        <MetricCard label="Langfuse cost" value={data.langfuse_metrics_available ? currency.format(data.langfuse_total_cost_usd) : '—'} helper="Calculated using Langfuse model pricing" />
        <MetricCard label="Traces" value={data.langfuse_metrics_available ? number.format(data.langfuse_trace_count) : '—'} helper="End-to-end instrumented workflows" />
        <MetricCard label="Observations" value={data.langfuse_metrics_available ? number.format(data.langfuse_observation_count) : '—'} helper="Spans, generations, tools and embeddings" />
        <MetricCard label="Quality scores" value={data.langfuse_metrics_available ? number.format(data.langfuse_score_count) : '—'} helper="Automated success and grounding signals" />
      </Box>
      {data.langfuse_metrics_available && <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(2, 1fr)' }, gap: 2, mt: 2 }}>
        <CostByModel rows={data.langfuse_cost_by_model} />
        <QualityScores rows={data.langfuse_scores} />
      </Box>}
    </Box>

    <Card><CardContent sx={{ p: 3 }}>
      <Typography variant="h6">Active AI configuration</Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(3, 1fr)' }, gap: 2, mt: 2 }}>
        {[['Extraction', data.extraction_model], ['Answers', data.answer_model], ['Embeddings', data.embedding_model]].map(([label, value]) => <Box key={label} sx={{ p: 2, borderRadius: 2, bgcolor: 'action.hover' }}><Typography variant="caption" color="text.secondary" fontWeight={700}>{label.toUpperCase()}</Typography><Typography variant="body2" fontWeight={750} sx={{ mt: .5, overflowWrap: 'anywhere' }}>{value}</Typography></Box>)}
      </Box>
    </CardContent></Card>

    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', lg: 'repeat(3, 1fr)' }, gap: 2 }}>
      <Breakdown title="Usage by model" rows={data.by_model} />
      <Breakdown title="Usage by operation" rows={data.by_operation} />
      <Breakdown title="Usage by prompt version" rows={data.by_prompt_version} />
    </Box>

    <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', md: 'repeat(2, 1fr)' }, gap: 2 }}>
      <MetricCard label="RAG grounding guard" value={`${groundingRate.toFixed(1)}%`} helper={`${data.grounded_answers}/${data.question_runs} answers grounded · ${data.guarded_not_found_answers} safe not-found`} />
      <MetricCard label="AI configuration" value={data.ai_configured ? 'Ready' : 'Incomplete'} helper={`${data.provider} provider · extraction, answers and embeddings`} />
    </Box>

    <Card><CardContent sx={{ p: 0 }}>
      <Box sx={{ px: 3, pt: 3, pb: 1 }}><Typography variant="h6">Recent persisted AI runs</Typography><Typography variant="body2" color="text.secondary">Supplier names and document filenames are deliberately excluded.</Typography></Box>
      <TableContainer><Table size="small">
        <TableHead><TableRow><TableCell>Run</TableCell><TableCell>Model / prompt</TableCell><TableCell align="right">Tokens</TableCell><TableCell align="right">Latency</TableCell><TableCell>Status</TableCell></TableRow></TableHead>
        <TableBody>{data.recent_runs.length === 0 ? <TableRow><TableCell colSpan={5}><Typography color="text.secondary">No runs in this window.</Typography></TableCell></TableRow> : data.recent_runs.map((run) => <TableRow key={run.id} hover>
          <TableCell><Typography variant="body2" fontWeight={700}>{run.run_type.replace('_', ' ')}</Typography><Typography variant="caption" color="text.secondary">{run.supplier_reference} · {new Date(run.created_at).toLocaleString()}</Typography></TableCell>
          <TableCell><Typography variant="body2" sx={{ overflowWrap: 'anywhere' }}>{run.model}</Typography><Typography variant="caption" color="text.secondary">{run.prompt_version}</Typography></TableCell>
          <TableCell align="right">{number.format(run.input_tokens + run.output_tokens)}</TableCell><TableCell align="right">{duration(run.latency_ms)}</TableCell>
          <TableCell><Chip size="small" color={run.status === 'succeeded' ? 'success' : run.status === 'failed' ? 'error' : 'warning'} label={run.status.replace('_', ' ')} /></TableCell>
        </TableRow>)}</TableBody>
      </Table></TableContainer>
    </CardContent></Card>
  </Stack>
}
