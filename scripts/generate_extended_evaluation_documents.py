"""Add scanned originals, contradictory evidence and procurement scenarios to v3.

Synthetic source records are authored before a live model run. Scans contain
images only; their pinned authoring transcripts are never sent to the backend.
The baseline v3 originals and gold records remain unchanged.
"""

import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.generate_evaluation_documents import SUPPLIERS, manifest_entry

ROOT = Path(__file__).resolve().parents[1] / "sample_documents" / "evaluation_sets"


def pdf(path, title, records, scan=False, compressed=False):
    """Use a large-font source layout; image-only output exercises actual OCR."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(page.rect, fill=(1, 1, 1), color=None)
    page.insert_text((40, 45), "SYNTHETIC EVALUATION DOCUMENT", fontsize=10, color=(.29, .35, .43))
    page.insert_text((40, 77), title, fontsize=18, fontname="hebo", color=(.14, .39, .92))
    y = 105
    for label, value in records:
        page.insert_text((40, y + 14), label, fontsize=10, fontname="hebo")
        box = pymupdf.Rect(40, y + 22, 555, y + 67)
        if page.insert_textbox(box, value, fontsize=12, fontname="helv") < 0:
            raise ValueError(f"Source text does not fit: {label}")
        y += 62
    if y > 800:
        raise ValueError("Too many source rows")
    page.insert_text((40, 820), "Fictional supplier evidence. No production or government document.", fontsize=8)
    transcript = "\n".join([title, *(f"{k}: {v}" for k, v in records)])
    if scan:
        pix = page.get_pixmap(dpi=250, colorspace=pymupdf.csGRAY)
        scanned = pymupdf.open()
        raster_page = scanned.new_page(width=595, height=842)
        if compressed:
            # A reduced rectangle mimics scanner margins. JPEG reduces fidelity.
            raster_page.insert_image(pymupdf.Rect(6, 8, 589, 834), stream=pix.tobytes("jpeg", jpg_quality=72))
        else:
            raster_page.insert_image(raster_page.rect, stream=pix.tobytes("png"))
        doc.close()
        doc = scanned
        path.with_suffix(".source.txt").write_text(transcript, encoding="utf-8", newline="\n")
    doc.save(path, garbage=4, deflate=True, no_new_id=True)
    doc.close()


def pack(i, slug, name, address, cohort):
    state, gst_prefix = {1:("KA", "29"),2:("GJ", "24"),3:("RJ", "08"),4:("TN", "33"),5:("KA", "29")}[i]
    return replace(SUPPLIERS[0], slug=slug, legal_name=f"{name} Private Limited",
                   trading_name=name, address=address, cin=f"U29120{state}2020PTC{150100+i:06d}",
                   pan=f"AABCR{1200+i:04d}F", gstin=f"{gst_prefix}AABCR{1200+i:04d}F1Z8",
                   incorporation_date="12 September 2020", contact_name="Riya Menon",
                   contact_email=f"evaluation.{slug}@example.com", contact_phone=f"+91 90010 {20000+i}",
                   product_category="Industrial sensors and calibration services",
                   payment_terms="Net 30 days from invoice receipt", signatory="Arun Rao",
                   policy_number=f"HPGL/2026/EV/{18000+i}", policy_start="01 JUL 2026",
                   policy_expiry="30 JUN 2027", occurrence_limit="INR 3,00,00,000")


def conflict_cases(s, alternate_address, cohort):
    reg, tax, ins = "01_supplier_registration_form.pdf", "02_gst_registration_certificate.pdf", "03_certificate_of_liability_insurance.pdf"
    cases = manifest_entry(s)["questions"]
    cases = [q for q in cases if q["id"] in {"legal_name", "insurance_provider", "trading_name_paraphrase", "insurance_provider_and_expiry", "absent_bank_balance", "absent_credit_rating"}]
    pairs = [
        ("address_disagreement", "For the vendor master, what registered address should we use? Check the registration and tax originals and explain whether they establish a single confirmed address.", [s.address, alternate_address], [reg, tax]),
        ("payment_disagreement", "Before I set payment terms in ERP, compare the stated standard payment terms in the registration and tax documents. Is there one agreed term?", ["Net 30", "Net 60"], [reg, tax]),
        ("expiry_disagreement", "When does liability cover end? Compare the registration summary and liability certificate and explain whether I can diary one confirmed expiry date.", [], [reg, ins]),
        ("conflict_review_note", "Prepare a review note about the address and payment-term conflicts between the registration and tax originals. Include both addresses and both terms, and identify the need for clarification.", [s.address, alternate_address, "Net 30", "Net 60"], [reg, tax]),
    ]
    for qid, question, terms, sources in pairs:
        q = {"id": qid, "question_type": "conflict_resolution", "question": question,
             "expected_terms": terms, "expected_sources": sources, "required_sources": sources,
             "information_found": True, "requires_conflict_acknowledgement": True,
             "requires_uncertainty": True,
             "gold_rationale": "Both originals assert the same field but disagree. No precedence, correction or confirmation is supplied. Report both source-attributed values and request clarification instead of declaring either authoritative."}
        q["expected_term_groups"] = [["registration", "supplier form"], ["insurance", "liability"] if ins in sources else ["tax", "GST"]]
        if qid == "expiry_disagreement":
            q["expected_dates"] = ["2027-06-30", "2027-07-31"]
        cases.append(q)
    return cases


def scenario_cases(s):
    reg, tax, ins = "01_supplier_registration_form.pdf", "02_gst_registration_certificate.pdf", "03_certificate_of_liability_insurance.pdf"
    specs = [
        ("erp_names", "I am setting up the vendor in ERP. Give the legal name and the trading name separately so I do not swap them.", [s.legal_name, s.trading_name], [], [reg]),
        ("gst_status", "Finance needs the legal name and GST registration status for the vendor master. What does the tax certificate state? Do not include identifiers.", [s.legal_name, "Registered"], [], [tax]),
        ("accounts_payable", "Our AP team starts the payment clock on invoice receipt. What number of days does this supplier allow and what is the trigger?", ["30", "invoice receipt"], [], [reg]),
        ("insurance_diary", "I need to diary the last day of liability cover. Convert the end of the policy period to a calendar date and tell me the insurer.", [s.insurance_provider], ["2027-06-30"], [ins]),
        ("supplier_handover", "Write a short handover for procurement with the legal name, product/service description and standard payment terms. Use only the uploaded originals.", [s.legal_name, s.product_category, s.payment_terms], [], [reg]),
        ("address_for_master", "Fill the address section of our vendor master: street, locality, city, state and PIN code. Please include every address component.", [v.strip() for v in s.address.split(',')], [], [reg, tax]),
        ("policy_identifiers", "For the insurance check, distinguish the policy number from the PAN and GSTIN. Which policy identifier and insurer should I record?", [s.policy_number, s.insurance_provider], [], [ins]),
        ("registration_date", "The team needs the incorporation date in a readable format, along with the registration status. What do the registration particulars say?", ["Active"], ["2020-09-12"], [reg]),
    ]
    cases = [{"id": qid, "question_type": "scenario_based", "question": question,
              "expected_terms": terms, "expected_dates": dates, "expected_sources": sources,
              "information_found": True} for qid, question, terms, dates, sources in specs]
    for qid, question in [
        ("payment_bank_missing", "AP is ready to pay. Which beneficiary bank account number should we use?"),
        ("approval_missing", "Can you confirm that the reviewer has approved this supplier for ERP onboarding from these uploaded documents?")]:
        cases.append({"id": qid, "question_type": "safe_not_found", "question": question,
                      "expected_terms": ["Information not found in uploaded supplier documents."],
                      "expected_sources": [], "information_found": False})
    return cases


def main():
    baseline = json.loads((ROOT / "baseline_manifest_v3.json").read_text())
    entries = list(baseline["suppliers"])
    definitions = [
        (1, "mallige_precision_works", "Mallige Precision Works", "Unit 21, Peenya Industrial Estate, Bengaluru, Karnataka 560058", "ocr"),
        (2, "narmada_instrumentation", "Narmada Instrumentation", "Plot 32, Makarpura Industrial Estate, Vadodara, Gujarat 390010", "ocr"),
        (3, "aravali_process_equipment", "Aravali Process Equipment", "Plot 41, Sitapura Industrial Area, Jaipur, Rajasthan 302022", "conflicting_evidence"),
        (4, "coromandel_sensor_systems", "Coromandel Sensor Systems", "Unit 52, Guindy Industrial Estate, Chennai, Tamil Nadu 600032", "conflicting_evidence"),
        (5, "tungabhadra_industrial_services", "Tungabhadra Industrial Services", "Unit 63, Bommasandra Industrial Area, Bengaluru, Karnataka 560099", "scenario_questions"),
    ]
    for i, slug, name, address, cohort in definitions:
        s = pack(i, slug, name, address, cohort)
        entry = manifest_entry(s)
        entry["cohort"] = cohort
        directory = ROOT / slug
        directory.mkdir(parents=True, exist_ok=True)
        conflict = cohort == "conflicting_evidence"
        alternate_address = ("Plot 91, Mansarovar Industrial Area, Jaipur, Rajasthan 302020" if i == 3 else "Unit 92, Ambattur Industrial Estate, Chennai, Tamil Nadu 600058")
        registration = [("Legal name", s.legal_name), ("Trading name", s.trading_name), ("Country", "India"),
                        ("CIN", s.cin), ("Incorporation date", s.incorporation_date),
                        ("Issuing registry / registration status", "Registrar of Companies, India / Active"),
                        ("Registered address", s.address), ("Standard payment terms", s.payment_terms),
                        ("Products / services", s.product_category)]
        if conflict:
            registration.append(("Liability policy expiry stated in registration", "31 JUL 2027"))
        tax = [("Legal name", s.legal_name), ("Trading name", s.trading_name), ("Country", "India"),
               ("Permanent Account Number (PAN)", s.pan), ("GSTIN", s.gstin),
               ("GST registration status", "Registered"),
               ("Registered address", alternate_address if conflict else s.address)]
        if conflict:
            tax.append(("Standard payment terms", "Net 60 days from invoice receipt"))
        insurance = [("Named insured", s.legal_name), ("Country", "India"), ("Insurance provider", s.insurance_provider),
                     ("Policy number", s.policy_number), ("Policy period", "01 JUL 2026 - 30 JUN 2027"),
                     ("Business activity", s.product_category), ("Coverage", "Commercial General Liability and Product Liability"),
                     ("Each occurrence limit", s.occurrence_limit)]
        entry["document_modes"] = {}
        entry["source_transcript_sha256"] = {}
        for kind, records in [("registration", registration), ("tax", tax), ("insurance", insurance)]:
            path = directory / entry["documents"][kind]
            scanned = cohort == "ocr"
            pdf(path, {"registration":"Supplier Registration Form", "tax":"GST Registration Certificate", "insurance":"Certificate of Liability Insurance"}[kind], records, scan=scanned, compressed=i==2)
            entry["document_modes"][kind] = "ocr" if scanned else "native"
            if scanned:
                entry["source_transcript_sha256"][kind] = hashlib.sha256(path.with_suffix(".source.txt").read_bytes()).hexdigest()
        if conflict:
            entry["questions"] = conflict_cases(s, alternate_address, cohort)
        elif cohort == "scenario_questions":
            entry["questions"] = scenario_cases(s)
        entry["document_sha256"] = {kind:hashlib.sha256((directory/name).read_bytes()).hexdigest() for kind,name in entry["documents"].items()}
        (directory / "ground_truth.json").write_text(json.dumps(entry, indent=2), encoding="utf-8")
        entries.append(entry)
    manifest = {"version":4, "description":"Baseline facts plus image-only scans, contradictory originals and procurement-style scenarios; all synthetic.",
                "expected_counts":{"suppliers":10,"documents":30,"questions":100,
                  "question_types":{"direct_fact":32,"paraphrased_fact":16,"date_interpretation":7,"multi_fact":9,"safe_not_found":20,"conflict_resolution":8,"scenario_based":8}},
                "suppliers":entries}
    (ROOT / "evaluation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Generated v4: 10 suppliers, 30 PDFs, 100 questions; six image-only scans.")


if __name__ == "__main__":
    main()
