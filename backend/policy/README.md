# Document requirements and future policy sources

`requirements.json` is the deterministic checklist used by the application. It selects required document types from saved category, subcategory and country; the first matching rule wins. The current Software & SaaS variation is **illustrative only**, not an actual company policy. The fallback matches the original three uploads. Keep each rule's reason explicit, review it with the team, and change the `version` when changing requirements. Existing submitted applications keep a snapshot of their checklist.

`source/` is reserved for written policy references you may provide later. This repository is public: only commit material you are allowed to publish. There is no policy document or policy RAG ingestion wired into the application yet. If real policy is private, keep it out of Git and use a private store when ingestion is built.

The checklist engine makes a yes/no requirement decision. A later RAG pipeline can retrieve written policy passages for explanations and citations, but its answer should not silently change the checklist. That keeps the required uploads predictable even when an AI provider is unavailable.
