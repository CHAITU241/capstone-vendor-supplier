export const erpFieldLabels: Record<string, string> = {
  supplier_reference: 'Supplier reference',
  legal_name: 'Legal name',
  registered_address: 'Registered address',
  country: 'Country',
  tax_reference: 'Tax reference',
  contact_name: 'Contact name',
  contact_email: 'Contact email',
  bank_account_number: 'Bank account',
  bank_ifsc: 'Bank IFSC',
  category: 'Category',
  subcategory: 'Subcategory',
  insurance_provider: 'Insurance provider',
  insurance_expiry: 'Insurance expiry',
  payment_terms: 'Payment terms',
}

export function erpFieldLabel(name: string) {
  return erpFieldLabels[name] ?? name.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase())
}
