const baselineIds: Record<string, string> = {
  registration: 'BASE-001',
  tax: 'BASE-002',
  bank: 'BASE-003',
}

export function supplierReference(supplierId: string): string {
  return `SUP-${supplierId.replaceAll('-', '').slice(0, 8).toUpperCase()}`
}

function filenameLabel(label: string): string {
  return label
    .normalize('NFKD')
    .replace(/[^a-zA-Z0-9]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean)
    .map((word) => `${word.charAt(0).toUpperCase()}${word.slice(1).toLowerCase()}`)
    .join('-') || 'Document'
}

export function evidenceDownloadFilename(input: {
  supplierId: string
  documentType: string
  revision: number
  originalFilename: string
  requirementId?: string
  label?: string
}): string {
  const extension = input.originalFilename.match(/\.([a-zA-Z0-9]{1,10})$/)?.[1].toLowerCase() ?? 'pdf'
  const requirementId = input.requirementId || baselineIds[input.documentType] || input.documentType.toUpperCase()
  const label = filenameLabel(input.label || input.documentType)
  return `${supplierReference(input.supplierId)}_${requirementId}_v${input.revision}_${label}.${extension}`
}
