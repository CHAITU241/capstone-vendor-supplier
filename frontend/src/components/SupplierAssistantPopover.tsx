import SupportAgentRoundedIcon from '@mui/icons-material/SupportAgentRounded'
import { Box, Button, CircularProgress, Fab, Popover, Stack, TextField, Typography } from '@mui/material'
import { useState } from 'react'
import { api } from '../api/client'
import type { GeneralAssistantMessage, GeneralAssistantResponse } from '../api/types'

const welcomeMessage: GeneralAssistantMessage = {
  role: 'assistant',
  content: 'Hi! I can help with general supplier onboarding questions, document preparation, and the review process. I do not read this supplier’s uploaded files.',
}

export function SupplierAssistantPopover() {
  const [messages, setMessages] = useState<GeneralAssistantMessage[]>([welcomeMessage])
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [run, setRun] = useState<GeneralAssistantResponse['run'] | null>(null)
  const [error, setError] = useState('')
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)

  async function handleSubmit() {
    const trimmedQuestion = question.trim()
    if (trimmedQuestion.length < 3) return
    const nextMessages: GeneralAssistantMessage[] = [
      ...messages,
      { role: 'user', content: trimmedQuestion },
    ]
    setMessages(nextMessages)
    setQuestion('')
    setAsking(true)
    setError('')
    try {
      const result = await api.askGeneralAssistant(nextMessages)
      setMessages((current) => [...current, { role: 'assistant', content: result.answer }])
      setRun(result.run)
    } catch (requestError) {
      setQuestion(trimmedQuestion)
      setError(requestError instanceof Error ? requestError.message : 'The supplier assistant could not answer.')
    } finally {
      setAsking(false)
    }
  }

  function resetChat() {
    setMessages([welcomeMessage])
    setQuestion('')
    setRun(null)
    setError('')
  }

  return (
    <>
      <Fab
        color="primary"
        aria-label="Open supplier onboarding assistant"
        onClick={(event) => setAnchorEl(event.currentTarget)}
        sx={{
          position: 'fixed',
          right: { xs: 16, sm: 24 },
          bottom: { xs: 16, sm: 24 },
          zIndex: (theme) => theme.zIndex.fab,
        }}
      >
        <SupportAgentRoundedIcon />
      </Fab>
      <Popover
        open={Boolean(anchorEl)}
        anchorEl={anchorEl}
        onClose={() => setAnchorEl(null)}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        slotProps={{
          paper: {
            sx: {
              width: { xs: 'calc(100vw - 32px)', sm: 420 },
              maxWidth: 'calc(100vw - 32px)',
              overflow: 'hidden',
            },
          },
        }}
      >
        <Box sx={{ p: 2.5 }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1}>
            <Stack direction="row" spacing={1} alignItems="center">
              <SupportAgentRoundedIcon color="primary" />
              <Typography variant="h6">Onboarding assistant</Typography>
            </Stack>
            <Button size="small" onClick={resetChat} disabled={asking}>New chat</Button>
          </Stack>
          <Typography color="text.secondary" variant="caption" display="block" sx={{ mt: 0.75, mb: 1.75 }}>
            General guidance only. Uploaded supplier documents are not used.
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.25, maxHeight: 'min(360px, 48vh)', overflowY: 'auto', p: 1.5, bgcolor: 'action.hover', borderRadius: 2 }}>
            {messages.map((message, index) => (
              <Box
                key={`${message.role}-${index}`}
                sx={{
                  alignSelf: message.role === 'user' ? 'flex-end' : 'flex-start',
                  maxWidth: '92%',
                  px: 1.5,
                  py: 1.1,
                  borderRadius: 2,
                  bgcolor: message.role === 'user' ? 'primary.main' : 'background.paper',
                  color: message.role === 'user' ? 'primary.contrastText' : 'text.primary',
                  boxShadow: 1,
                }}
              >
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>{message.content}</Typography>
              </Box>
            ))}
            {asking && (
              <Box sx={{ alignSelf: 'flex-start', px: 1.5, py: 1.1 }}>
                <CircularProgress size={18} />
              </Box>
            )}
          </Box>
          {error && <Typography color="error" variant="caption" display="block" sx={{ mt: 1 }}>{error}</Typography>}
          <Box
            component="form"
            onSubmit={(event) => { event.preventDefault(); void handleSubmit() }}
            sx={{ display: 'flex', gap: 1, mt: 1.5, alignItems: 'flex-start' }}
          >
            <TextField
              fullWidth
              size="small"
              label="Ask a question"
              placeholder="What should I prepare?"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              disabled={asking}
            />
            <Button type="submit" variant="contained" disabled={asking || question.trim().length < 3} sx={{ minWidth: 64, minHeight: 40 }}>
              Send
            </Button>
          </Box>
          {run && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1.25 }}>
              {run.model} / {run.input_tokens + run.output_tokens} tokens / {(run.latency_ms / 1000).toFixed(1)}s
              {Object.keys(run.redaction_counts).length > 0 && ' / PII protected before AI call'}
            </Typography>
          )}
        </Box>
      </Popover>
    </>
  )
}
