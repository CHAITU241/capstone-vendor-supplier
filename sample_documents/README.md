# Supplier Document Pack

These three PDFs represent one coherent fictional supplier: **Asteron Industrial Components Private Limited**.
Every organization, identifier, address, signature, policy, and government-style record is synthetic.
Do not use the documents for identity verification, tax filings, insurance evidence, or any official purpose.

## Upload Mapping

| File | VendorLens document type | Purpose |
|---|---|---|
| `01_supplier_registration_form.pdf` | `registration` | Supplier-entered master data and declaration |
| `02_gst_registration_certificate.pdf` | `tax` | Tax identity and principal business address |
| `03_certificate_of_liability_insurance.pdf` | `insurance` | Policy coverage and future expiry date |

## Ground Truth

- Legal name: `Asteron Industrial Components Private Limited`
- Trading name: `Asteron Components`
- CIN: `U28999MH2024PTC000117`
- PAN: `AAECA0000A`
- GSTIN: `27AAECA0000A1Z5`
- Incorporation date: `17 May 2024`
- Address: `Unit 14B, Orion Industrial Estate, Phase II, Chakan, Pune, Maharashtra 410501`
- Contact: `Priya Nair`, `priya.nair@example.com`, `+91 90000 12345`
- Insurance policy: `SSG/GL/2026/004871`
- Insurance expiry: `31 March 2027`

The common legal name and address should match across all three documents.
The pack is deliberately consistent so it can serve as the positive or happy-path evaluation case.

## Regeneration

From the repository root:

```powershell
.\backend\.venv\Scripts\python.exe scripts\generate_mock_documents.py
```

## Additional Evaluation Sets

Four additional three-document supplier packs and their machine-readable Q&A ground truth are available under `evaluation_sets/`.
See `evaluation_sets/README.md` for generation and live evaluation commands.
