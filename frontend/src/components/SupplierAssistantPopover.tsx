import CloseRoundedIcon from '@mui/icons-material/CloseRounded'
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded'
import SendRoundedIcon from '@mui/icons-material/SendRounded'
import SupportAgentRoundedIcon from '@mui/icons-material/SupportAgentRounded'
import { Alert, Box, Button, Chip, CircularProgress, Drawer, Fab, IconButton, Stack, TextField, Typography } from '@mui/material'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api, ApiError } from '../api/client'
import type { GeneralAssistantMessage } from '../api/types'

const welcomeMessage: GeneralAssistantMessage = {
  role: 'assistant',
  content: 'Hi! I can guide you through the supplier application and review journey. Choose a quick answer below or ask a question.',
}

const quickGuides = [
  { label: 'What do I need?', answer: 'Choose the service that best describes your business. Then enter your registered name, contact email, tax reference, bank account and IFSC. Your document page will show exactly what to upload and what each item should contain.' },
  { label: 'Can I save and return?', answer: 'Yes. Create a supplier account with your email and password. Each completed step and uploaded document is saved to your account. Sign in with the same email to continue.' },
  { label: 'What happens next?', answer: 'After the requested files are uploaded, submit your application. A reviewer checks their contents and will tell you if anything needs correction.' },
]

function recentConversation(messages: GeneralAssistantMessage[]): GeneralAssistantMessage[] {
  const recent = messages.slice(-12)
  while (recent.length > 1 && recent.reduce((total, message) => total + message.content.length, 0) > 10000) recent.shift()
  return recent
}

function assistantErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 502) return 'The assistant could not get an answer right now. Please try again.'
    if (error.status === 503) return 'The assistant is temporarily unavailable. Please try again later.'
    if (error.status === 422) return 'This chat could not be sent. Start a new chat and try again.'
    return error.message
  }
  return 'Cannot reach the portal server right now. Please try again when it is running.'
}

export function SupplierAssistantPopover() {
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState<GeneralAssistantMessage[]>([welcomeMessage])
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [error, setError] = useState('')

  async function handleSubmit() {
    const trimmedQuestion = question.trim()
    if (trimmedQuestion.length < 3) return
    const nextMessages: GeneralAssistantMessage[] = [...messages, { role: 'user', content: trimmedQuestion }]
    setMessages(nextMessages)
    setQuestion('')
    setAsking(true)
    setError('')
    try {
      const result = await api.askGeneralAssistant(recentConversation(nextMessages))
      setMessages((current) => [...current, { role: 'assistant', content: result.answer }])
    } catch (requestError) {
      setMessages(messages)
      setQuestion(trimmedQuestion)
      setError(assistantErrorMessage(requestError))
    } finally { setAsking(false) }
  }

  function resetChat() {
    setMessages([welcomeMessage])
    setQuestion('')
    setError('')
  }

  return <>
    {!open && <Fab color="primary" variant="extended" aria-label="Open onboarding help" onClick={() => setOpen(true)}
      sx={{ position: 'fixed', right: { xs: 16, sm: 24 }, bottom: { xs: 16, sm: 24 }, zIndex: (theme) => theme.zIndex.fab, gap: 1, px: 2.5, boxShadow: 4 }}>
      <SupportAgentRoundedIcon /> Ask VendorLens
    </Fab>}
    <Drawer anchor="right" open={open} onClose={() => setOpen(false)} PaperProps={{ sx: { width: { xs: '100%', sm: 480 }, maxWidth: '100vw', bgcolor: '#FAFBFF' } }}>
      <Stack sx={{ height: '100%' }}>
        <Stack direction="row" alignItems="center" spacing={1.5} sx={{ px: 2.5, py: 2, bgcolor: 'white', borderBottom: '1px solid', borderColor: 'divider' }}>
          <Box sx={{ width: 42, height: 42, display: 'grid', placeItems: 'center', bgcolor: '#EDE9FE', color: 'tertiary.main', borderRadius: 2 }}><SupportAgentRoundedIcon /></Box>
          <Box sx={{ flexGrow: 1 }}><Typography fontWeight={750}>VendorLens guide</Typography><Typography variant="caption" color="text.secondary">Supplier onboarding help</Typography></Box>
          <IconButton title="Start a new chat" aria-label="Start a new chat" onClick={resetChat} disabled={asking}><RefreshRoundedIcon /></IconButton>
          <IconButton title="Close assistant" aria-label="Close assistant" onClick={() => setOpen(false)}><CloseRoundedIcon /></IconButton>
        </Stack>

        <Box sx={{ flex: 1, overflowY: 'auto', p: 2.5 }}>
          <Stack spacing={2}>
            {messages.map((message, index) => <Box key={index} sx={{ alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: message.role === 'user' ? '92%' : '100%', p: 1.75, borderRadius: 2.5, bgcolor: message.role === 'user' ? 'primary.main' : 'white', color: message.role === 'user' ? 'white' : 'text.primary', boxShadow: '0 3px 14px rgba(15, 23, 42, 0.08)' }}>
              {message.role === 'assistant' ? <Box sx={{ fontSize: '0.875rem', lineHeight: 1.65, overflowWrap: 'anywhere',
                '& p': { m: 0, mb: 1.25 }, '& p:last-child': { mb: 0 },
                '& ol, & ul': { mt: 1, mb: 1.5, pl: 2.75 }, '& ol:last-child, & ul:last-child': { mb: 0 },
                '& li': { pl: 0.5, mb: 1.25 }, '& li:last-child': { mb: 0 },
                '& li::marker': { color: 'primary.main', fontWeight: 700 },
                '& li > p': { mb: 0.5 }, '& li > ul, & li > ol': { mt: 0.5, mb: 0 },
                '& strong': { fontWeight: 750 }, '& a': { color: 'primary.main' },
                '& h1, & h2, & h3': { fontSize: '1rem', lineHeight: 1.4, mt: 1.5, mb: 0.75 },
                '& h1:first-child, & h2:first-child, & h3:first-child': { mt: 0 },
              }}><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown></Box>
                : <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{message.content}</Typography>}
            </Box>)}
            {asking && <CircularProgress size={20} />}
          </Stack>
          {messages.length === 1 && <Box sx={{ mt: 3 }}><Typography variant="caption" color="text.secondary" fontWeight={700}>QUICK ANSWERS</Typography>
            <Stack direction="row" useFlexGap flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
              {quickGuides.map((guide) => <Chip key={guide.label} label={guide.label} clickable variant="outlined" color="primary" onClick={() => setMessages((current) => [...current, { role: 'user', content: guide.label }, { role: 'assistant', content: guide.answer }])} />)}
            </Stack></Box>}
          {error && <Alert severity="info" sx={{ mt: 2 }}>{error}</Alert>}
        </Box>

        <Box sx={{ p: 2.5, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'white' }}>
          <Stack component="form" direction="row" spacing={1} onSubmit={(event) => { event.preventDefault(); void handleSubmit() }}>
            <TextField fullWidth size="small" placeholder="Ask about onboarding..." aria-label="Ask the assistant" value={question} onChange={(event) => setQuestion(event.target.value)} slotProps={{ htmlInput: { maxLength: 2000 } }} disabled={asking} />
            <Button type="submit" variant="contained" aria-label="Send question" disabled={asking || question.trim().length < 3} sx={{ minWidth: 44, px: 1.5 }}><SendRoundedIcon fontSize="small" /></Button>
          </Stack>
          <Typography display="block" variant="caption" color="text.secondary" sx={{ mt: 1 }}>This guide can explain requirements but cannot inspect your uploads or application result.</Typography>
        </Box>
      </Stack>
    </Drawer>
  </>
}
