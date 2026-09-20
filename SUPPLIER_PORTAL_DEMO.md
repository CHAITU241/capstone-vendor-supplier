# Supplier portal demo flow

1. Start the existing stack with `docker compose up --build -d`.
2. Visit `http://localhost:5173`. The home page has separate supplier and reviewer paths.
3. Create a supplier account with an email and password (at least eight characters). The email is the sign in identity; the account owns one application draft in PostgreSQL.
4. Choose one of eight policy categories and 24 primary subcategories. Read its definition, examples and boundary, then enter an India-based business name, contact email, synthetic tax reference, synthetic bank account and IFSC. The document checklist lists the three baseline IDs plus the exact additional IDs from that subcategory's policy. Open each item for accepted evidence, required fields and numbered checks. Each completed step and upload persists across sign in sessions.
5. Submit the application. The reviewer workspace then lists it; drafts do not appear there.
6. From home, use **Enter reviewer demo** to inspect submitted cases and run the existing processing, RAG and compliance actions.
7. Open **Ask VendorLens** on the right. Quick answers work without an AI key. With OpenRouter configured, open questions retrieve relevant passages from the 12 synthetic policy texts and cite their source; the assistant cannot inspect an individual application or decide its result.

The reviewer entry is deliberately open for a capstone demo. Supplier passwords are hashed and supplier draft endpoints check account ownership, but the reviewer demo is not company authentication. Use synthetic supplier and payment information only. The version 1.1 rules are invented for this capstone, not statutory or company policy. The app accepts text PDFs and UTF-8 text files; combine multi-part evidence into one PDF per requirement. PNG, JPG, scans and image-only PDFs from the written policy are not yet supported. The current processing pipeline extracts general fields, but does **not** verify the 22 sets of numbered policy checks. Review results explicitly flag each applicable ID for verification and block automated approval.

The `0006`, `0007` and `0008_synthetic_policy_v1` Alembic migrations run at backend startup. Submitted applications keep their checklist snapshot when the rules change. Existing cases remain visible to reviewers; older drafts must choose a new policy code. Keep `backend/.env` local; it is ignored by Git.
