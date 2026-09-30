import type { ErpRecord } from '../api/types'

export interface VendorMasterRow {
  vendorId: string
  portalReference: string
  legalName: string
  status: string
  category: string
  subcategory: string
  contactName: string
  contactPhone: string
  contactEmail: string
  registeredAddress: string
  city: string
  state: string
  postalCode: string
  country: string
  taxReference: string
  bankAccountNumber: string
  bankIfsc: string
  insuranceProvider: string
  insuranceExpiry: string
  paymentTerms: string
  comments: string
  createdAt: string
  updatedAt: string
  sourceSupplierId: string
  record: ErpRecord
}

export interface VendorMasterColumn {
  key: keyof VendorMasterRow
  label: string
}

export const vendorMasterColumns: VendorMasterColumn[] = [
  { key: 'vendorId', label: 'Vendor ID' },
  { key: 'legalName', label: 'Vendor name' },
  { key: 'portalReference', label: 'Portal reference' },
  { key: 'status', label: 'Status' },
  { key: 'category', label: 'Category' },
  { key: 'subcategory', label: 'Subcategory' },
  { key: 'contactName', label: 'Contact name' },
  { key: 'contactPhone', label: 'Contact phone' },
  { key: 'contactEmail', label: 'Contact email' },
  { key: 'registeredAddress', label: 'Registered address' },
  { key: 'city', label: 'City' },
  { key: 'state', label: 'State' },
  { key: 'postalCode', label: 'ZIP / postal code' },
  { key: 'country', label: 'Country' },
  { key: 'taxReference', label: 'Tax reference' },
  { key: 'bankAccountNumber', label: 'Bank account number' },
  { key: 'bankIfsc', label: 'Bank IFSC' },
  { key: 'insuranceProvider', label: 'Insurance provider' },
  { key: 'insuranceExpiry', label: 'Insurance expiry' },
  { key: 'paymentTerms', label: 'Payment terms' },
  { key: 'comments', label: 'Comments / notes' },
  { key: 'createdAt', label: 'ERP created at' },
  { key: 'updatedAt', label: 'ERP updated at' },
]

function payloadValue(record: ErpRecord, ...keys: string[]) {
  for (const key of keys) {
    const value = record.payload[key]
    if (value !== null && value !== undefined && String(value).trim()) return String(value).trim()
  }
  return ''
}

export function toVendorMasterRow(record: ErpRecord): VendorMasterRow {
  return {
    vendorId: record.erp_supplier_id,
    portalReference: record.supplier_reference ?? payloadValue(record, 'supplier_reference'),
    legalName: record.legal_name,
    status: record.status,
    category: record.category,
    subcategory: record.subcategory,
    contactName: payloadValue(record, 'contact_name'),
    contactPhone: payloadValue(record, 'contact_phone', 'phone'),
    contactEmail: payloadValue(record, 'contact_email'),
    registeredAddress: payloadValue(record, 'registered_address', 'address'),
    city: payloadValue(record, 'city'),
    state: payloadValue(record, 'state', 'province'),
    postalCode: payloadValue(record, 'postal_code', 'zip_code', 'zip'),
    country: payloadValue(record, 'country'),
    taxReference: record.tax_reference,
    bankAccountNumber: payloadValue(record, 'bank_account_number'),
    bankIfsc: payloadValue(record, 'bank_ifsc'),
    insuranceProvider: payloadValue(record, 'insurance_provider'),
    insuranceExpiry: payloadValue(record, 'insurance_expiry_date', 'insurance_expiry'),
    paymentTerms: payloadValue(record, 'payment_terms'),
    comments: payloadValue(record, 'comments', 'notes'),
    createdAt: record.created_at ?? '',
    updatedAt: record.updated_at ?? '',
    sourceSupplierId: record.source_supplier_id,
    record,
  }
}

export function formatVendorMasterDate(value: string) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function csvCell(value: unknown) {
  let text = value === null || value === undefined ? '' : String(value)
  // Prevent user-provided supplier values from becoming spreadsheet formulas.
  if (/^[=+\-@]/.test(text)) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}

export function buildVendorMasterCsv(rows: VendorMasterRow[]) {
  const header = vendorMasterColumns.map((column) => csvCell(column.label)).join(',')
  const body = rows.map((row) => vendorMasterColumns.map((column) => {
    const value = row[column.key]
    if (column.key === 'createdAt' || column.key === 'updatedAt') {
      return csvCell(formatVendorMasterDate(String(value)))
    }
    return csvCell(value)
  }).join(','))
  return `\uFEFF${[header, ...body].join('\r\n')}`
}
