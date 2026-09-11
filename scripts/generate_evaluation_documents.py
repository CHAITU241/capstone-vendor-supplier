"""Generate four coherent supplier packs for VendorLens quality evaluation."""

import json
from dataclasses import dataclass
from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = ROOT / "sample_documents" / "evaluation_sets"
PAGE_WIDTH, PAGE_HEIGHT = pymupdf.paper_size("a4")

NAVY = (0.055, 0.12, 0.23)
BLUE = (0.145, 0.388, 0.922)
TEAL = (0.078, 0.62, 0.56)
PURPLE = (0.43, 0.25, 0.78)
GOLD = (0.82, 0.52, 0.08)
SLATE = (0.29, 0.35, 0.43)
LIGHT = (0.96, 0.975, 0.99)
WHITE = (1, 1, 1)
BLACK = (0.06, 0.08, 0.11)


@dataclass(frozen=True)
class SupplierPack:
    slug: str
    legal_name: str
    trading_name: str
    address: str
    country: str
    cin: str
    pan: str
    gstin: str
    incorporation_date: str
    contact_name: str
    contact_role: str
    contact_email: str
    contact_phone: str
    product_category: str
    payment_terms: str
    signatory: str
    insurance_provider: str
    policy_number: str
    policy_start: str
    policy_expiry: str
    occurrence_limit: str
    registration_reference: str
    tax_reference: str
    insurance_reference: str


SUPPLIERS = [
    SupplierPack(
        slug="kaveri_flow_controls",
        legal_name="Kaveri Flow Controls Private Limited",
        trading_name="Kaveri FlowTech",
        address="Plot 22, SIDCO Industrial Estate, Kurichi, Coimbatore, Tamil Nadu 641021",
        country="India",
        cin="U29120TZ2018PTC030945",
        pan="AABCK1234F",
        gstin="33AABCK1234F1Z8",
        incorporation_date="12 September 2018",
        contact_name="Ananya Rao",
        contact_role="Head of Finance and Compliance",
        contact_email="ananya.rao@example.com",
        contact_phone="+91 90001 23456",
        product_category="Industrial valves, actuator assemblies and flow-control skids",
        payment_terms="Net 30 days from invoice receipt",
        signatory="Vikram Iyer",
        insurance_provider="HarborPoint General Insurance Company Limited",
        policy_number="HPGL/2026/FC/01842",
        policy_start="01 JUL 2026",
        policy_expiry="30 JUN 2027",
        occurrence_limit="INR 3,00,00,000",
        registration_reference="KFC/SUP/2026/1042",
        tax_reference="GST/TN/2026/4198",
        insurance_reference="COI/HP/2026/01842",
    ),
    SupplierPack(
        slug="norwood_clinical_systems",
        legal_name="Norwood Clinical Systems Private Limited",
        trading_name="Norwood Clinical",
        address="48, KIADB Health Technology Park, Whitefield, Bengaluru, Karnataka 560066",
        country="India",
        cin="U33110KA2020PTC141208",
        pan="AABCN5678K",
        gstin="29AABCN5678K1Z2",
        incorporation_date="03 December 2020",
        contact_name="Rohan Kulkarni",
        contact_role="Commercial Operations Manager",
        contact_email="rohan.kulkarni@example.com",
        contact_phone="+91 90002 34567",
        product_category="Diagnostic equipment carts, instrument stands and clinical workstations",
        payment_terms="Net 45 days from accepted delivery",
        signatory="Meera Thomas",
        insurance_provider="CedarSure Commercial Insurance Company Limited",
        policy_number="CSC/PLI/2025/77309",
        policy_start="16 DEC 2025",
        policy_expiry="15 DEC 2026",
        occurrence_limit="INR 5,00,00,000",
        registration_reference="NCS/VEN/2026/773",
        tax_reference="GST/KA/2026/5521",
        insurance_reference="COI/CSC/2025/77309",
    ),
    SupplierPack(
        slug="prithvi_sustainable_packaging",
        legal_name="Prithvi Sustainable Packaging Private Limited",
        trading_name="Prithvi EcoPack",
        address="Survey 118, Sanand Industrial Cluster, Ahmedabad, Gujarat 382110",
        country="India",
        cin="U21099GJ2019PTC109844",
        pan="AAGCP4321L",
        gstin="24AAGCP4321L1Z6",
        incorporation_date="21 August 2019",
        contact_name="Devika Shah",
        contact_role="Finance Controller",
        contact_email="devika.shah@example.com",
        contact_phone="+91 90003 45678",
        product_category="Recycled corrugated cartons, molded fibre inserts and protective packaging",
        payment_terms="Net 60 days from invoice date",
        signatory="Nikhil Desai",
        insurance_provider="Meridian Risk Assurance Company Limited",
        policy_number="MRA/CGL/2027/11028",
        policy_start="01 FEB 2027",
        policy_expiry="31 JAN 2028",
        occurrence_limit="INR 2,50,00,000",
        registration_reference="PSP/ONB/2027/228",
        tax_reference="GST/GJ/2027/6104",
        insurance_reference="COI/MRA/2027/11028",
    ),
    SupplierPack(
        slug="eastbridge_logistics",
        legal_name="Eastbridge Logistics and Warehousing Private Limited",
        trading_name="Eastbridge Logistics",
        address="Warehouse 7, Jalan Logistics Park, Dankuni, Hooghly, West Bengal 712311",
        country="India",
        cin="U63030WB2017PTC221706",
        pan="AACCE8765M",
        gstin="19AACCE8765M1Z4",
        incorporation_date="14 July 2017",
        contact_name="Souvik Banerjee",
        contact_role="Senior Manager - Accounts",
        contact_email="souvik.banerjee@example.com",
        contact_phone="+91 90004 56789",
        product_category="Contract warehousing, inventory handling and regional freight coordination",
        payment_terms="Net 15 days after monthly service acceptance",
        signatory="Ishita Sen",
        insurance_provider="AtlasGuard General Insurance Company Limited",
        policy_number="AGG/LOG/2026/90441",
        policy_start="01 OCT 2026",
        policy_expiry="30 SEP 2027",
        occurrence_limit="INR 4,00,00,000",
        registration_reference="ELW/SUP/2026/904",
        tax_reference="GST/WB/2026/7310",
        insurance_reference="COI/AGG/2026/90441",
    ),
]


def initials(name: str) -> str:
    ignored = {"and", "private", "limited"}
    words = [word for word in name.split() if word.casefold() not in ignored]
    return "".join(word[0] for word in words[:3]).upper()


def new_document(title: str, subject: str) -> tuple[pymupdf.Document, pymupdf.Page]:
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": title,
            "subject": subject,
            "creator": "Business Document Services",
            "producer": "PyMuPDF",
        }
    )
    return document, document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)


def header(
    page: pymupdf.Page,
    supplier: SupplierPack,
    title: str,
    subtitle: str,
    reference: str,
    accent: tuple[float, float, float],
) -> None:
    page.draw_rect((0, 0, PAGE_WIDTH, 94), fill=NAVY, color=NAVY)
    page.draw_rect((0, 90, PAGE_WIDTH, 94), fill=accent, color=accent)
    page.draw_rect((34, 24, 74, 64), fill=accent, color=accent, radius=0.12)
    page.insert_textbox((37, 35, 71, 58), initials(supplier.legal_name), fontname="hebo", fontsize=12, color=WHITE, align=1)
    page.insert_text((86, 39), supplier.trading_name.upper(), fontname="hebo", fontsize=13, color=WHITE)
    page.insert_text((86, 57), subtitle, fontname="helv", fontsize=7.5, color=(0.78, 0.84, 0.92))
    page.insert_text((310, 39), title, fontname="hebo", fontsize=12, color=WHITE)
    page.insert_text((430, 77), reference, fontname="helv", fontsize=7.5, color=WHITE)


def section(page: pymupdf.Page, y: float, title: str, accent=BLUE) -> float:
    page.draw_rect((34, y, PAGE_WIDTH - 34, y + 24), fill=LIGHT, color=(0.86, 0.9, 0.95))
    page.draw_rect((34, y, 39, y + 24), fill=accent, color=accent)
    page.insert_text((49, y + 16), title.upper(), fontname="hebo", fontsize=8.5, color=NAVY)
    return y + 31


def rows(page: pymupdf.Page, y: float, values: list[tuple[str, str]], row_height=27.0) -> float:
    left, right, split = 34, PAGE_WIDTH - 34, 190
    for index, (label, value) in enumerate(values):
        top = y + index * row_height
        fill = WHITE if index % 2 == 0 else (0.98, 0.985, 0.995)
        page.draw_rect((left, top, right, top + row_height), fill=fill, color=(0.84, 0.87, 0.91), width=0.5)
        page.draw_line((split, top), (split, top + row_height), color=(0.84, 0.87, 0.91), width=0.5)
        page.insert_text((left + 9, top + 17), label, fontname="hebo", fontsize=7.5, color=SLATE)
        page.insert_textbox((split + 9, top + 5, right - 8, top + row_height - 3), value, fontname="helv", fontsize=8, color=BLACK)
    return y + len(values) * row_height


def footer(page: pymupdf.Page, reference: str) -> None:
    page.draw_line((34, 802), (PAGE_WIDTH - 34, 802), color=(0.82, 0.85, 0.89), width=0.7)
    page.insert_text((34, 819), f"Reference: {reference}", fontname="helv", fontsize=7, color=SLATE)
    page.insert_text((489, 819), "Page 1 of 1", fontname="helv", fontsize=7, color=SLATE)


def save(document: pymupdf.Document, directory: Path, filename: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    document.save(directory / filename, garbage=4, deflate=True)
    document.close()


def registration_pdf(supplier: SupplierPack, directory: Path) -> None:
    document, page = new_document("Supplier Registration Form", "Supplier onboarding particulars")
    header(page, supplier, "SUPPLIER REGISTRATION FORM", "Procurement and Finance Onboarding", supplier.registration_reference, BLUE)
    y = section(page, 112, "Organization profile")
    y = rows(page, y, [
        ("Legal name", supplier.legal_name),
        ("Trading name", supplier.trading_name),
        ("Country", supplier.country),
        ("Incorporation / CIN", f"{supplier.incorporation_date} / {supplier.cin}"),
        ("PAN / GSTIN", f"{supplier.pan} / {supplier.gstin}"),
        ("Registered address", supplier.address),
    ])
    y = section(page, y + 12, "Commercial and contact details", TEAL)
    rows(page, y, [
        ("Primary contact", f"{supplier.contact_name}, {supplier.contact_role}"),
        ("Email / phone", f"{supplier.contact_email} / {supplier.contact_phone}"),
        ("Products / services", supplier.product_category),
        ("Standard payment terms", supplier.payment_terms),
        ("Authorized signatory", supplier.signatory),
    ])
    footer(page, supplier.registration_reference)
    save(document, directory, "01_supplier_registration_form.pdf")


def tax_pdf(supplier: SupplierPack, directory: Path) -> None:
    document, page = new_document("GST Registration Certificate", "Goods and Services Tax registration")
    header(page, supplier, "GST REGISTRATION CERTIFICATE", "Registration Particulars", supplier.tax_reference, PURPLE)
    y = 112
    page.draw_rect((34, y, PAGE_WIDTH - 34, y + 50), fill=(0.96, 0.94, 1), color=(0.78, 0.68, 0.95))
    page.insert_text((48, y + 18), "GOODS AND SERVICES TAX IDENTIFICATION NUMBER", fontname="helv", fontsize=7.5, color=SLATE)
    page.insert_text((48, y + 39), supplier.gstin, fontname="hebo", fontsize=15, color=PURPLE)
    page.insert_text((438, y + 31), "STATUS: ACTIVE", fontname="hebo", fontsize=9, color=(0.05, 0.5, 0.3))
    y = section(page, y + 64, "Registration particulars", PURPLE)
    y = rows(page, y, [
        ("Legal name", supplier.legal_name),
        ("Trade name", supplier.trading_name),
        ("Country", supplier.country),
        ("Constitution", "Private Limited Company"),
        ("Permanent Account Number", supplier.pan),
        ("Registration type", "Regular"),
        ("Principal place of business", supplier.address),
        ("Authorized signatory", supplier.signatory),
        ("Jurisdiction", supplier.address.split(",")[-2].strip()),
    ])
    footer(page, supplier.tax_reference)
    save(document, directory, "02_gst_registration_certificate.pdf")


def insurance_pdf(supplier: SupplierPack, directory: Path) -> None:
    document, page = new_document("Certificate of Liability Insurance", "Commercial liability insurance")
    header(page, supplier, "CERTIFICATE OF LIABILITY INSURANCE", supplier.insurance_provider, supplier.insurance_reference, GOLD)
    y = 112
    page.draw_rect((34, y, PAGE_WIDTH - 34, y + 48), fill=(1, 0.975, 0.91), color=(0.92, 0.75, 0.35))
    page.insert_text((48, y + 18), "POLICY STATUS", fontname="helv", fontsize=7.5, color=SLATE)
    page.insert_text((48, y + 37), "ACTIVE", fontname="hebo", fontsize=12, color=(0.05, 0.5, 0.3))
    page.insert_text((180, y + 18), "POLICY PERIOD", fontname="helv", fontsize=7.5, color=SLATE)
    page.insert_text((180, y + 37), f"{supplier.policy_start} - {supplier.policy_expiry}", fontname="hebo", fontsize=10, color=NAVY)
    y = section(page, y + 62, "Insured and policy details", GOLD)
    y = rows(page, y, [
        ("Named insured", supplier.legal_name),
        ("Country", supplier.country),
        ("Insured address", supplier.address),
        ("Insurance provider", supplier.insurance_provider),
        ("Policy number", supplier.policy_number),
        ("Coverage", "Commercial General Liability and Product Liability"),
        ("Business activity", supplier.product_category),
        ("Each occurrence limit", supplier.occurrence_limit),
        ("Policy expiry date", supplier.policy_expiry),
    ])
    footer(page, supplier.insurance_reference)
    save(document, directory, "03_certificate_of_liability_insurance.pdf")


def evaluation_questions(supplier: SupplierPack) -> list[dict]:
    return [
        {
            "id": "legal_name",
            "question": "What is the supplier's full legal name?",
            "expected_terms": [supplier.legal_name],
            "expected_sources": [
                "01_supplier_registration_form.pdf",
                "02_gst_registration_certificate.pdf",
                "03_certificate_of_liability_insurance.pdf",
            ],
            "information_found": True,
        },
        {
            "id": "payment_terms",
            "question": "What are the supplier's standard payment terms?",
            "expected_terms": [supplier.payment_terms],
            "expected_sources": ["01_supplier_registration_form.pdf"],
            "information_found": True,
        },
        {
            "id": "insurance_provider",
            "question": "Which company provides the supplier's liability insurance?",
            "expected_terms": [supplier.insurance_provider],
            "expected_sources": ["03_certificate_of_liability_insurance.pdf"],
            "information_found": True,
        },
        {
            "id": "insurance_expiry",
            "question": "When does the supplier's liability insurance expire?",
            "expected_terms": [supplier.policy_expiry],
            "expected_sources": ["03_certificate_of_liability_insurance.pdf"],
            "information_found": True,
        },
        {
            "id": "business_activity",
            "question": "What products or services does this supplier provide?",
            "expected_terms": [supplier.product_category],
            "expected_sources": [
                "01_supplier_registration_form.pdf",
                "03_certificate_of_liability_insurance.pdf",
            ],
            "information_found": True,
        },
        {
            "id": "absent_bank_balance",
            "question": "What is the supplier's current bank account balance?",
            "expected_terms": ["Information not found in uploaded supplier documents."],
            "expected_sources": [],
            "information_found": False,
        },
    ]


def manifest_entry(supplier: SupplierPack) -> dict:
    return {
        "slug": supplier.slug,
        "create_payload": {
            "name": supplier.legal_name,
            "country": supplier.country,
            "contact_email": supplier.contact_email,
        },
        "documents": {
            "registration": "01_supplier_registration_form.pdf",
            "tax": "02_gst_registration_certificate.pdf",
            "insurance": "03_certificate_of_liability_insurance.pdf",
        },
        "expected_fields": {
            "supplier_name": supplier.legal_name,
            "address": supplier.address,
            "country": supplier.country,
            "tax_identifier": supplier.gstin,
            "contact_name": supplier.contact_name,
            "contact_email": supplier.contact_email,
            "insurance_provider": supplier.insurance_provider,
            "insurance_expiry_date": supplier.policy_expiry,
            "payment_terms": supplier.payment_terms,
        },
        "questions": evaluation_questions(supplier),
    }


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    entries = []
    for supplier in SUPPLIERS:
        directory = OUTPUT_ROOT / supplier.slug
        registration_pdf(supplier, directory)
        tax_pdf(supplier, directory)
        insurance_pdf(supplier, directory)
        entry = manifest_entry(supplier)
        (directory / "ground_truth.json").write_text(
            json.dumps(entry, indent=2), encoding="utf-8"
        )
        entries.append(entry)
    (OUTPUT_ROOT / "evaluation_manifest.json").write_text(
        json.dumps({"version": 1, "suppliers": entries}, indent=2),
        encoding="utf-8",
    )
    print(f"Generated {len(entries)} supplier packs in {OUTPUT_ROOT}")


if __name__ == "__main__":
    main()
