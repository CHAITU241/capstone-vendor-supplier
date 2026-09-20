import CloseRoundedIcon from '@mui/icons-material/CloseRounded'
import RefreshRoundedIcon from '@mui/icons-material/RefreshRounded'
import SendRoundedIcon from '@mui/icons-material/SendRounded'
import SupportAgentRoundedIcon from '@mui/icons-material/SupportAgentRounded'
import { Alert, Box, Button, Chip, CircularProgress, Drawer, Fab, IconButton, Stack, TextField, Typography } from '@mui/material'
import { useState } from 'react'
import { api } from '../api/client'
import type { GeneralAssistantMessage } from '../api/types'

const welcomeMessage: GeneralAssistantMessage = {
  role: 'assistant',
  content: 'Hi! I can guide you through the supplier application and review journey. Choose a quick answer below or ask a question.',
}

const quickGuides = [
  { label: 'What do I need?', answer: 'Enter your business category, subcategory, registered name, country and contact email. The document page then shows your checklist and why each document is requested. The current rules are illustrative until your company policy is supplied.' },
  { label: 'Can I save and return?', answer: 'Yes. Create a supplier account with your email and password. Each completed step and uploaded document is saved to your account. Sign in with the same email to continue.' },
  { label: 'What happens next?', answer: 'After the requested documents are uploaded, submit your application. It will then appear in the reviewer workspace for document processing and review.' },
]

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
      const result = await api.askGeneralAssistant(nextMessages.slice(-12))
      setMessages((current) => [...current, { role: 'assistant', content: result.answer }])
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'The assistant could not answer right now.')
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
    <Drawer anchor="right" open={open} onClose={() => setOpen(false)} PaperProps={{ sx: { width: { xs: '100%', sm: 430 }, maxWidth: '100vw', bgcolor: '#FAFBFF' } }}>
      <Stack sx={{ height: '100%' }}>
        <Stack direction="row" alignItems="center" spacing={1.5} sx={{ px: 2.5, py: 2, bgcolor: 'white', borderBottom: '1px solid', borderColor: 'divider' }}>
          <Box sx={{ width: 42, height: 42, display: 'grid', placeItems: 'center', bgcolor: '#EDE9FE', color: 'tertiary.main', borderRadius: 2 }}><SupportAgentRoundedIcon /></Box>
          <Box sx={{ flexGrow: 1 }}><Typography fontWeight={750}>VendorLens guide</Typography><Typography variant="caption" color="text.secondary">Onboarding help · OpenRouter ready</Typography></Box>
          <IconButton title="Start a new chat" aria-label="Start a new chat" onClick={resetChat} disabled={asking}><RefreshRoundedIcon /></IconButton>
          <IconButton title="Close assistant" aria-label="Close assistant" onClick={() => setOpen(false)}><CloseRoundedIcon /></IconButton>
        </Stack>

        <Box sx={{ flex: 1, overflowY: 'auto', p: 2.5 }}>
          <Stack spacing={2}>
            {messages.map((message, index) => <Box key={index} sx={{ alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '92%', p: 1.75, borderRadius: 2.5, bgcolor: message.role === 'user' ? 'primary.main' : 'white', color: message.role === 'user' ? 'white' : 'text.primary', boxShadow: '0 3px 14px rgba(15, 23, 42, 0.08)' }}>
              <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>{message.content}</Typography>
            </Box>)}
            {asking && <CircularProgress size={20} />}
          </Stack>
          {messages.length === 1 && <Box sx={{ mt: 3 }}><Typography variant="caption" color="text.secondary" fontWeight={700}>QUICK ANSWERS</Typography>
            <Stack direction="row" useFlexGap flexWrap="wrap" gap={1} sx={{ mt: 1 }}>
              {quickGuides.map((guide) => <Chip key={guide.label} label={guide.label} clickable variant="outlined" color="primary" onClick={() => setMessages((current) => [...current, { role: 'user', content: guide.label }, { role: 'assistant', content: guide.answer }])} />)}
            </Stack></Box>}
          {error && <Alert severity="info" sx={{ mt: 2 }}>{error} Quick answers above work without an AI key; open questions need a configured OpenRouter provider.</Alert>}
        </Box>

        <Box sx={{ p: 2.5, borderTop: '1px solid', borderColor: 'divider', bgcolor: 'white' }}>
          <Stack component="form" direction="row" spacing={1} onSubmit={(event) => { event.preventDefault(); void handleSubmit() }}>
            <TextField fullWidth size="small" placeholder="Ask about onboarding..." aria-label="Ask the assistant" value={question} onChange={(event) => setQuestion(event.target.value)} disabled={asking} />
            <Button type="submit" variant="contained" aria-label="Send question" disabled={asking || question.trim().length < 3} sx={{ minWidth: 44, px: 1.5 }}><SendRoundedIcon fontSize="small" /></Button>
          </Stack>
          <Typography display="block" variant="caption" color="text.secondary" sx={{ mt: 1 }}>General guidance only. Uploaded supplier documents are not used in this chat.</Typography>
        </Box>
      </Stack>
    </Drawer>
  </>
}
