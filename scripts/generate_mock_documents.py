"""Generate the VendorLens supplier training document pack."""

from pathlib import Path
from textwrap import wrap

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "sample_documents"
PAGE_WIDTH, PAGE_HEIGHT = pymupdf.paper_size("a4")

NAVY = (0.055, 0.12, 0.23)
BLUE = (0.145, 0.388, 0.922)
TEAL = (0.078, 0.722, 0.651)
VIOLET = (0.486, 0.227, 0.929)
GOLD = (0.85, 0.55, 0.08)
RED = (0.78, 0.12, 0.16)
SLATE = (0.28, 0.35, 0.44)
LIGHT = (0.96, 0.975, 0.99)
WHITE = (1, 1, 1)
BLACK = (0.06, 0.08, 0.11)

COMPANY = "Asteron Industrial Components Private Limited"
TRADING_NAME = "Asteron Components"
ADDRESS = "Unit 14B, Orion Industrial Estate, Phase II, Chakan, Pune, Maharashtra 410501"
PAN = "AAECA0000A"
GSTIN = "27AAECA0000A1Z5"
CIN = "U28999MH2024PTC000117"


def new_document(title: str, subject: str) -> tuple[pymupdf.Document, pymupdf.Page]:
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": title,
            "author": "VendorLens Document Generator",
            "subject": subject,
            "keywords": "supplier onboarding, training dataset",
            "creator": "VendorLens AI",
            "producer": "PyMuPDF",
        }
    )
    page = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    return document, page


def save_document(document: pymupdf.Document, filename: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    document.save(OUTPUT_DIR / filename, garbage=4, deflate=True)
    document.close()


def draw_brand_header(
    page: pymupdf.Page,
    title: str,
    subtitle: str,
    reference: str,
    accent: tuple[float, float, float] = BLUE,
) -> None:
    page.draw_rect((0, 0, PAGE_WIDTH, 94), fill=NAVY, color=NAVY)
    page.draw_rect((0, 90, PAGE_WIDTH, 94), fill=accent, color=accent)
    page.draw_rect((34, 24, 74, 64), fill=accent, color=accent, radius=0.15)
    page.insert_text((46, 52), "A", fontname="hebo", fontsize=23, color=WHITE)
    page.insert_text((86, 39), "ASTERON", fontname="hebo", fontsize=18, color=WHITE)
    page.insert_text(
        (86, 57), "INDUSTRIAL COMPONENTS", fontname="helv", fontsize=7.5, color=(0.78, 0.84, 0.92)
    )
    page.insert_text((286, 37), title, fontname="hebo", fontsize=14, color=WHITE)
    page.insert_text((286, 56), subtitle, fontname="helv", fontsize=8, color=(0.8, 0.86, 0.94))
    page.insert_text((460, 78), reference, fontname="helv", fontsize=7.5, color=WHITE)


def draw_footer(page: pymupdf.Page, document_id: str, line_y: float = 802) -> None:
    text_y = line_y + 17
    page.draw_line((34, line_y), (PAGE_WIDTH - 34, line_y), color=(0.82, 0.85, 0.89), width=0.7)
    page.insert_text((34, text_y), f"Document ID: {document_id}", fontname="helv", fontsize=7, color=SLATE)
    page.insert_text((206, text_y), "TRAINING SAMPLE - NOT VALID FOR OFFICIAL USE", fontname="hebo", fontsize=6.5, color=SLATE)
    page.insert_text((470, text_y), "Page 1 of 1", fontname="helv", fontsize=7, color=SLATE)


def section_heading(page: pymupdf.Page, y: float, title: str, accent: tuple[float, float, float] = BLUE) -> float:
    page.draw_rect((34, y, PAGE_WIDTH - 34, y + 24), fill=LIGHT, color=(0.86, 0.9, 0.95), radius=0.08)
    page.draw_rect((34, y, 39, y + 24), fill=accent, color=accent)
    page.insert_text((49, y + 16), title.upper(), fontname="hebo", fontsize=8.5, color=NAVY)
    return y + 31


def key_value_rows(
    page: pymupdf.Page,
    y: float,
    rows: list[tuple[str, str]],
    row_height: float = 25,
    label_width: float = 160,
) -> float:
    left, right = 34, PAGE_WIDTH - 34
    for index, (label, value) in enumerate(rows):
        top = y + index * row_height
        fill = WHITE if index % 2 == 0 else (0.98, 0.985, 0.995)
        page.draw_rect((left, top, right, top + row_height), fill=fill, color=(0.84, 0.87, 0.91), width=0.5)
        page.draw_line(
            (left + label_width, top),
            (left + label_width, top + row_height),
            color=(0.84, 0.87, 0.91),
            width=0.5,
        )
        page.insert_text((left + 9, top + 16), label, fontname="hebo", fontsize=7.5, color=SLATE)
        page.insert_textbox(
            (left + label_width + 9, top + 6, right - 8, top + row_height - 3),
            value,
            fontname="helv",
            fontsize=8,
            color=BLACK,
            lineheight=1.1,
        )
    return y + len(rows) * row_height


def paragraph(page: pymupdf.Page, y: float, text: str, size: float = 8.5, color=BLACK, line_height: float = 1.3) -> float:
    lines = wrap(text, width=105)
    height = max(20, len(lines) * size * line_height + 5)
    page.insert_textbox(
        (40, y, PAGE_WIDTH - 40, y + height),
        "\n".join(lines),
        fontname="helv",
        fontsize=size,
        color=color,
        lineheight=line_height,
    )
    return y + height


def signature_block(page: pymupdf.Page, y: float, name: str, role: str, stamp_text: str, accent=BLUE) -> None:
    page.draw_line((52, y + 34), (220, y + 34), color=SLATE, width=0.8)
    page.insert_text((52, y + 49), name, fontname="hebo", fontsize=8, color=NAVY)
    page.insert_text((52, y + 63), role, fontname="helv", fontsize=7.5, color=SLATE)
    page.draw_circle((455, y + 31), 39, color=accent, width=1.5)
    page.draw_circle((455, y + 31), 32, color=accent, width=0.7)
    page.insert_textbox(
        (423, y + 12, 487, y + 51), stamp_text, fontname="hebo", fontsize=7, color=accent, align=1
    )


def create_supplier_registration() -> None:
    document, page = new_document("Supplier Registration Form", "Supplier master-data form")
    draw_brand_header(page, "SUPPLIER REGISTRATION FORM", "Finance & Procurement Onboarding", "VLI/REG/2026/00017")
    y = 112
    y = section_heading(page, y, "Organization profile")
    y = key_value_rows(
        page,
        y,
        [
            ("Legal name", COMPANY),
            ("Trading name", TRADING_NAME),
            ("Entity type", "Private Limited Company"),
            ("Incorporation / CIN", f"17 May 2024 / {CIN}"),
            ("PAN / GSTIN", f"{PAN} / {GSTIN}"),
            ("Registered address", ADDRESS),
        ],
        row_height=26,
    )
    y += 12
    y = section_heading(page, y, "Primary contact and supply profile", TEAL)
    y = key_value_rows(
        page,
        y,
        [
            ("Primary contact", "Priya Nair, Manager - Finance & Compliance"),
            ("Email / phone", "priya.nair@example.com / +91 90000 12345"),
            ("Product category", "CNC-machined components and stainless-steel assemblies"),
            ("Service regions", "Maharashtra, Gujarat, Karnataka and pan-India project supply"),
            ("Employees / turnover", "86 employees / INR 18.7 crore (FY 2025-26, unaudited)"),
        ],
        row_height=27,
    )
    y += 12
    y = section_heading(page, y, "Supplier declaration", VIOLET)
    y = paragraph(
        page,
        y + 2,
        "We declare that the information provided is complete and accurate for this onboarding. "
        "The organization is not blacklisted, agrees to applicable anti-bribery and supplier conduct requirements, "
        "and will notify the buyer of material changes to tax, banking or insurance information.",
        size=8,
    )
    signature_block(page, y + 4, "Arjun Mehta", "Director and Authorized Signatory", "ASTERON\nCOMPANY SEAL", VIOLET)
    draw_footer(page, "VLI-REG-00017")
    save_document(document, "01_supplier_registration_form.pdf")


def create_gst_certificate() -> None:
    document, page = new_document("GST Registration Certificate", "Tax registration certificate")
    draw_brand_header(page, "GST REGISTRATION CERTIFICATE", "Form GST REG-06 | Registration Copy", "GST/27/2026/117", VIOLET)
    y = 112
    page.draw_rect((34, y, PAGE_WIDTH - 34, y + 48), fill=(0.96, 0.94, 1), color=(0.78, 0.68, 0.95), radius=0.08)
    page.insert_text((48, y + 18), "Goods and Services Tax Identification Number", fontname="helv", fontsize=8, color=SLATE)
    page.insert_text((48, y + 38), GSTIN, fontname="hebo", fontsize=15, color=VIOLET)
    page.insert_text((430, y + 31), "STATUS: ACTIVE", fontname="hebo", fontsize=9, color=(0.05, 0.55, 0.34))
    y += 62
    y = section_heading(page, y, "Registration particulars", VIOLET)
    y = key_value_rows(
        page,
        y,
        [
            ("Legal name", COMPANY),
            ("Trade name", TRADING_NAME),
            ("Constitution", "Private Limited Company"),
            ("PAN", PAN),
            ("Date of liability", "01 June 2024"),
            ("Registration type", "Regular"),
            ("Validity", "From 01 June 2024 until cancelled"),
            ("Principal place of business", ADDRESS),
        ],
        row_height=26,
    )
    y += 12
    y = section_heading(page, y, "Goods and authorized signatory", TEAL)
    y = key_value_rows(
        page,
        y,
        [
            ("Primary goods / HSN", "Machined metal articles (7326), transmission parts (8483), fasteners (7318)"),
            ("Authorized signatory", "Arjun Mehta, Director"),
            ("Jurisdiction", "Maharashtra State / Pune North Range"),
            ("Certificate generated", "04 August 2026 at 10:30 IST"),
        ],
        row_height=29,
    )
    signature_block(page, y + 18, "System Generated", "Tax Registration Service", "ACTIVE\nGST REG.", VIOLET)
    draw_footer(page, "VLI-GST-00017")
    save_document(document, "02_gst_registration_certificate.pdf")


def create_insurance_certificate() -> None:
    document, page = new_document("Certificate of Liability Insurance", "Insurance coverage certificate")
    draw_brand_header(page, "CERTIFICATE OF LIABILITY INSURANCE", "Summit Shield General Insurance Company Limited", "COI/2026/04871", GOLD)
    y = 112
    page.draw_rect((34, y, PAGE_WIDTH - 34, y + 44), fill=(1, 0.975, 0.91), color=(0.92, 0.75, 0.35), radius=0.08)
    page.insert_text((47, y + 18), "CERTIFICATE STATUS", fontname="helv", fontsize=7.5, color=SLATE)
    page.insert_text((47, y + 35), "ACTIVE", fontname="hebo", fontsize=13, color=(0.08, 0.52, 0.3))
    page.insert_text((180, y + 18), "POLICY PERIOD", fontname="helv", fontsize=7.5, color=SLATE)
    page.insert_text((180, y + 35), "01 APR 2026 - 31 MAR 2027", fontname="hebo", fontsize=10, color=NAVY)
    page.insert_text((415, y + 18), "CURRENCY", fontname="helv", fontsize=7.5, color=SLATE)
    page.insert_text((415, y + 35), "INR", fontname="hebo", fontsize=11, color=NAVY)
    y += 58
    y = section_heading(page, y, "Insured and policy details", GOLD)
    y = key_value_rows(
        page,
        y,
        [
            ("Named insured", COMPANY),
            ("Insured address", ADDRESS),
            ("Insurer", "Summit Shield General Insurance Company Limited"),
            ("Policy number", "SSG/GL/2026/004871"),
            ("Coverage", "Commercial General Liability and Product Liability"),
            ("Business activity", "Manufacture and supply of machined industrial components"),
        ],
        row_height=27,
    )
    y += 12
    y = section_heading(page, y, "Limits of insurance", VIOLET)
    y = key_value_rows(
        page,
        y,
        [
            ("Each occurrence", "INR 2,00,00,000"),
            ("Products aggregate", "INR 4,00,00,000"),
            ("General aggregate", "INR 4,00,00,000"),
            ("Deductible", "INR 1,00,000 per occurrence"),
        ],
        row_height=27,
    )
    y += 12
    y = section_heading(page, y, "Certificate statement", TEAL)
    y = paragraph(
        page,
        y + 2,
        "This certificate summarizes the policy shown above and does not amend, extend or alter its terms. "
        "Coverage remains subject to the policy conditions, exclusions and payment of premium.",
        size=8,
    )
    signature_block(page, y + 5, "Maya Deshpande", "Authorized Insurance Representative", "SUMMIT SHIELD\nAUTHORIZED", GOLD)
    draw_footer(page, "SSG-COI-04871")
    save_document(document, "03_certificate_of_liability_insurance.pdf")


def main() -> None:
    create_supplier_registration()
    create_gst_certificate()
    create_insurance_certificate()
    print(f"Generated three supplier training PDFs in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
