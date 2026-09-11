"""Seed a clean, presentation-ready set of VendorLens demo supplier flows.

The script talks to the running FastAPI API so the seeded records exercise the
same upload, processing, review, compliance, approval, rejection, and audit
paths as the UI. Use --reset-all only against a disposable local demo database.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000/api"
OUTPUT_PATH = ROOT / "sample_documents" / "demo_seed_manifest.json"

FLOWS = [
    # {
    #     "key": "empty_intake",
    #     "name": "VendorLens Empty Intake Demo",
    #     "country": "India",
    #     "contact_email": "empty.intake@example.com",
    #     "documents": {},
    #     "desired_status": "new",
    # },
    {
        "key": "featured_review",
        "name": "Asteron Industrial Components Private Limited",
        "country": "India",
        "contact_email": "priya.nair@example.com",
        "pack": ROOT / "sample_documents",
        "documents": {
            "registration": "01_supplier_registration_form.pdf",
            "tax": "02_gst_registration_certificate.pdf",
            "insurance": "03_certificate_of_liability_insurance.pdf",
        },
        "desired_status": "needs_review",
        "role": "Keep this supplier open for the live demo.",
    },
    {
        "key": "approved",
        "name": "Kaveri Flow Controls Private Limited",
        "country": "India",
        "contact_email": "ananya.rao@example.com",
        "pack": ROOT / "sample_documents" / "evaluation_sets" / "kaveri_flow_controls",
        "documents": {
            "registration": "01_supplier_registration_form.pdf",
            "tax": "02_gst_registration_certificate.pdf",
            "insurance": "03_certificate_of_liability_insurance.pdf",
        },
        "desired_status": "approved",
    },
    {
        "key": "pending",
        "name": "Norwood Clinical Systems Private Limited",
        "country": "India",
        "contact_email": "rohan.kulkarni@example.com",
        "pack": ROOT / "sample_documents" / "evaluation_sets" / "norwood_clinical_systems",
        "documents": {
            "registration": "01_supplier_registration_form.pdf",
            "tax": "02_gst_registration_certificate.pdf",
            "insurance": "03_certificate_of_liability_insurance.pdf",
        },
        "desired_status": "needs_review",
    },
    {
        "key": "rejected",
        "name": "Prithvi Sustainable Packaging Private Limited",
        "country": "India",
        "contact_email": "devika.shah@example.com",
        "pack": ROOT / "sample_documents" / "evaluation_sets" / "prithvi_sustainable_packaging",
        "documents": {
            "registration": "01_supplier_registration_form.pdf",
            "tax": "02_gst_registration_certificate.pdf",
            "insurance": "03_certificate_of_liability_insurance.pdf",
        },
        "desired_status": "rejected",
    },
]


def request_json(method: str, url: str, *, timeout: int = 120, **kwargs):
    response = requests.request(method, url, timeout=timeout, **kwargs)
    if not response.ok:
        raise RuntimeError(
            f"{method} {url} returned {response.status_code}: {response.text[:500]}"
        )
    return response.json() if response.content else {}


def reset_all_local_data() -> None:
    """Delete all supplier cases and their local files/vectors.

    This is deliberately only reachable through the explicit --reset-all flag.
    """

    backend_root = ROOT / "backend"
    backend_path = str(backend_root)
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)

    previous_cwd = Path.cwd()
    os.chdir(backend_root)
    try:
        from sqlalchemy import select

        from app.config import get_settings
        from app.database import SessionLocal
        from app.models import Supplier
        from app.services.retrieval import delete_supplier_chunks, get_chunk_collection

        settings = get_settings()
        upload_root = settings.upload_dir.resolve()
        db = SessionLocal()
        file_paths: list[Path] = []
        try:
            suppliers = list(db.scalars(select(Supplier)).all())
            collection = get_chunk_collection()
            for supplier in suppliers:
                for document in supplier.documents:
                    file_paths.append(Path(document.storage_path))
                delete_supplier_chunks(collection, str(supplier.id))
                db.delete(supplier)
            db.commit()
        finally:
            db.close()
    finally:
        os.chdir(previous_cwd)

    print(f"Reset {len(suppliers)} local supplier case(s), documents, and vectors.")

    for file_path in file_paths:
        resolved = (backend_root / file_path).resolve() if not file_path.is_absolute() else file_path.resolve()
        if resolved.is_relative_to(upload_root):
            resolved.unlink(missing_ok=True)


def get_or_create_supplier(base_url: str, flow: dict) -> dict:
    suppliers = request_json("GET", f"{base_url}/suppliers")
    matches = [item for item in suppliers if item["name"] == flow["name"]]
    if matches:
        return matches[-1]
    return request_json(
        "POST",
        f"{base_url}/suppliers",
        json={
            "name": flow["name"],
            "country": flow["country"],
            "contact_email": flow["contact_email"],
        },
    )


def upload_documents(base_url: str, flow: dict, supplier_id: str) -> None:
    if not flow["documents"]:
        return
    detail = request_json("GET", f"{base_url}/suppliers/{supplier_id}")
    existing_types = {item["document_type"] for item in detail["documents"]}
    for document_type, filename in flow["documents"].items():
        if document_type in existing_types:
            continue
        document_path = flow["pack"] / filename
        with document_path.open("rb") as handle:
            response = requests.post(
                f"{base_url}/suppliers/{supplier_id}/documents",
                data={"document_type": document_type},
                files={"file": (filename, handle, "application/pdf")},
                timeout=120,
            )
        if not response.ok:
            raise RuntimeError(
                f"Upload {document_path} returned {response.status_code}: {response.text[:500]}"
            )


def process_supplier(base_url: str, supplier_id: str) -> dict:
    return request_json(
        "POST",
        f"{base_url}/suppliers/{supplier_id}/process",
        timeout=360,
    )


def review_all_uncertain_fields(base_url: str, supplier_id: str) -> int:
    detail = request_json("GET", f"{base_url}/suppliers/{supplier_id}")
    corrected = 0
    for field in detail["extracted_fields"]:
        if not field["needs_review"]:
            continue
        request_json(
            "PATCH",
            f"{base_url}/suppliers/{supplier_id}/fields/{field['id']}",
            json={
                "value": field["value"],
                "page_number": field["page_number"],
                "reviewer_name": "Demo reviewer",
            },
        )
        corrected += 1
    return corrected


def run_compliance(base_url: str, supplier_id: str) -> dict:
    return request_json("POST", f"{base_url}/suppliers/{supplier_id}/compliance/run")


def seed_flow(base_url: str, flow: dict) -> dict:
    supplier = get_or_create_supplier(base_url, flow)
    supplier_id = supplier["id"]
    upload_documents(base_url, flow, supplier_id)

    if flow["documents"]:
        process_supplier(base_url, supplier_id)

    if flow["key"] == "approved":
        corrected = review_all_uncertain_fields(base_url, supplier_id)
        run_compliance(base_url, supplier_id)
        decision = request_json(
            "POST",
            f"{base_url}/suppliers/{supplier_id}/approve",
            json={"confirmed": True, "reviewer_name": "Demo reviewer"},
        )
        print(f"  reviewed {corrected} uncertain field(s); approved as {decision['erp_supplier_id']}")
    elif flow["key"] == "rejected":
        run_compliance(base_url, supplier_id)
        request_json(
            "POST",
            f"{base_url}/suppliers/{supplier_id}/reject",
            json={
                "confirmed": True,
                "reason": "Rejected for demo because the supplier did not meet the procurement risk threshold.",
                "reviewer_name": "Demo reviewer",
            },
        )
    elif flow["documents"]:
        run_compliance(base_url, supplier_id)

    detail = request_json("GET", f"{base_url}/suppliers/{supplier_id}")
    return {
        "key": flow["key"],
        "name": flow["name"],
        "supplier_id": supplier_id,
        "status": detail["status"],
        "document_count": detail["document_count"],
        "role": flow.get("role"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument(
        "--reset-all",
        action="store_true",
        help="Delete all local supplier cases, uploaded files, and Chroma vectors before seeding.",
    )
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    health = request_json("GET", f"{base_url}/health")
    if health.get("status") != "healthy":
        raise RuntimeError(f"API health check did not pass: {health}")

    if args.reset_all:
        reset_all_local_data()
    else:
        existing = request_json("GET", f"{base_url}/suppliers")
        existing_names = {item["name"] for item in existing}
        collisions = sorted(existing_names & {flow["name"] for flow in FLOWS})
        if collisions:
            raise RuntimeError(
                "Demo names already exist. Re-run with --reset-all against the disposable demo database, "
                f"or remove these cases manually: {', '.join(collisions)}"
            )

    seeded = []
    for flow in FLOWS:
        print(f"Seeding {flow['key']}: {flow['name']}", flush=True)
        seeded.append(seed_flow(base_url, flow))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"base_url": base_url, "flows": seeded}, indent=2), encoding="utf-8")
    print("\nSeeded demo flows:")
    for item in seeded:
        marker = "  <-- live demo" if item["key"] == "featured_review" else ""
        print(f"- {item['name']}: {item['status']} ({item['document_count']} documents){marker}")
    print(f"\nManifest: {args.output}")


if __name__ == "__main__":
    main()
