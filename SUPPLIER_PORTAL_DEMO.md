# Supplier portal demo flow

1. Start the existing stack with `docker compose up --build -d`.
2. Visit `http://localhost:5173`. The home page has separate supplier and reviewer paths.
3. Create a supplier account with an email and password (at least eight characters). The email is the sign in identity; the account owns one application draft in PostgreSQL.
4. Choose category and subcategory, enter business details, then upload one registration, tax and insurance PDF or text file. Each completed step and upload persists across sign in sessions.
5. Submit the application. The reviewer workspace then lists it; drafts do not appear there.
6. From home, use **Enter reviewer demo** to inspect submitted cases and run the existing processing, RAG and compliance actions.
7. Open **Ask VendorLens** on the right. Quick answers work without an AI key. Open questions use the existing `/api/assistant/chat` endpoint and need an AI provider configured in `backend/.env` (OpenRouter takes priority when its key is set).

The reviewer entry is deliberately open for a capstone demo. Supplier passwords are hashed and supplier draft endpoints check account ownership, but the reviewer demo is not company authentication. Do not use this build for real supplier information. The taxonomy is illustrative and the current three document types are inherited from the initial app. Password reset, email verification, and company SSO are outside this MVP.

The `0006_supplier_portal` Alembic migration runs at backend startup. Existing cases remain visible to reviewers. Keep `backend/.env` local; it is ignored by Git.
