# Supplier portal demo flow

1. Start the existing stack with `docker compose up --build -d`.
2. Visit `http://localhost:5173`. The home page has separate supplier and reviewer paths.
3. Create a supplier account with an email and password (at least eight characters). The email is the sign in identity; the account owns one application draft in PostgreSQL.
4. Choose one of eight policy categories and 24 primary subcategories. Read its definition, examples and boundary, then enter an India-based business name, contact email, synthetic tax reference, synthetic bank account and IFSC. The document checklist lists the three baseline IDs plus the exact additional IDs from that subcategory's policy. Open each item for accepted evidence, required fields and numbered checks. Each completed step and upload persists across sign in sessions. Use **View original** to open an uploaded PDF or text file; previous uploads remain in the upload history after removal or replacement.
5. Submit the application. The reviewer workspace then lists it; drafts do not appear there.
6. From home, use **Enter reviewer demo** to inspect submitted cases and run the existing processing, RAG and compliance actions.
7. Open **Ask VendorLens** on the right. Quick answers work without an AI key. With OpenRouter configured, open questions retrieve relevant passages from the 12 synthetic policy texts and cite their source; the assistant cannot inspect an individual application or decide its result.

The reviewer entry is deliberately open for a capstone demo. Supplier passwords are hashed and supplier draft endpoints check account ownership, but the reviewer demo is not company authentication. Use synthetic supplier and payment information only. The version 1.1 rules are invented for this capstone, not statutory or company policy. The app accepts text PDFs and UTF-8 text files; combine multi-part evidence into one PDF per requirement. PNG, JPG, scans and image-only PDFs from the written policy are not yet supported. The current processing pipeline extracts general fields, but does **not** verify the 22 sets of numbered policy checks. Review results explicitly flag each applicable ID for verification and block automated approval.

The `0006` through `0009_document_revisions` Alembic migrations run at backend startup. Submitted applications keep their checklist snapshot when the rules change. Existing cases remain visible to reviewers; older drafts must choose a new policy code. Keep `backend/.env` local; it is ignored by Git.

## Original evidence storage

The original bytes are written under `/app/uploads/<supplier UUID>/<document UUID>.<extension>` in the backend container. Docker Compose stores this directory in its named `uploads_data` volume. PostgreSQL holds active document metadata and archived revision records; each new upload stores a SHA-256 digest. Removing an upload removes it from the active checklist but retains the original bytes and archived metadata. Supplier-owned and reviewer-only API routes stream active and archived files after authorization, check the file digest, and record a view event. Reviewer access to account-owned suppliers begins after submission. A supplier cannot open another supplier's original.

The Docker volume survives container rebuilds, but it is not a backup. `docker compose down -v` destroys it. A production deployment would need durable object storage, coordinated database/file backup and restore, retention rules, malware scanning, and company reviewer authentication. OCR remains out of scope for this slice; scanned PDFs and image uploads cannot be processed by the current text extractor.

## Admin maintenance

Set `ADMIN_EMAIL` and a strong, unique `ADMIN_PASSWORD` in the local `backend/.env`, then recreate the backend. Both must be nonempty to enable admin sign in. A small **Admin** link sits below the supplier sign in form. The admin page lists draft and submitted profiles, lets you copy the login email, and offers **Reset password**. Supplier passwords are one-way hashes, so the old password cannot be shown. Reset generates a new random password shown only in that response and signs out all of that supplier's sessions. Copy it before leaving the page.

**Delete profile** requires typing its email or profile name. It deletes the supplier account, database records, active and archived originals in the supplier's upload directory, and its search chunks. Reviewer-created cases without an account can also be deleted. This is permanent, so do not use it as a replacement for retention and backup controls. Admin authentication is separate from the open reviewer demo; do not share the admin credentials or commit `backend/.env`.
