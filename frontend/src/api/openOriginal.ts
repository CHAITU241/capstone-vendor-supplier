/** Open a browser tab during the click so the authenticated download is not blocked as a popup. */
export async function openOriginal(load: () => Promise<Blob>): Promise<void> {
  const tab = window.open('', '_blank')
  if (!tab) throw new Error('Allow pop-ups to view the original document.')
  tab.opener = null
  try {
    const file = await load()
    const url = URL.createObjectURL(file)
    tab.location.href = url
    window.setTimeout(() => URL.revokeObjectURL(url), 10 * 60 * 1000)
  } catch (error) {
    tab.close()
    throw error
  }
}


export async function downloadOriginal(load: () => Promise<Blob>, filename: string): Promise<void> {
  const file = await load()
  const url = URL.createObjectURL(file)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 60 * 1000)
}
