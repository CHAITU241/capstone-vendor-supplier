"""Generate a complete negative-case supplier pack for VendorLens."""

from pathlib import Path
from shutil import copy2

import pymupdf

from generate_negative_case_document import generate as generate_expired_insurance


ROOT = Path(__file__).resolve().parents[1]
PACK_DIR = ROOT / "sample_documents" / "negative_cases" / "blueharbor_offshore_services"
PAGE_WIDTH, PAGE_HEIGHT = pymupdf.paper_size("a4")

NAVY = (0.035, 0.12, 0.20)
BLUE = (0.08, 0.35, 0.55)
TEAL = (0.08, 0.54, 0.49)
VIOLET = (0.38, 0.23, 0.65)
SLATE = (0.29, 0.35, 0.43)
LIGHT = (0.96, 0.975, 0.99)
WHITE = (1, 1, 1)
BLACK = (0.06, 0.08, 0.11)

COMPANY = "BlueHarbor Offshore Services Private Limited"
TRADING_NAME = "BlueHarbor Offshore Services"
ADDRESS = "Jetty 4, New Mangalore Port, Panambur, Mangaluru, Karnataka 575010"
PAN = "AACCB1234N"
GSTIN = "29AACCB1234N1Z7"
CIN = "U63030KA2017PTC221706"


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


def header(page: pymupdf.Page, title: str, subtitle: str, reference: str, accent=BLUE) -> None:
    page.draw_rect((0, 0, PAGE_WIDTH, 94), fill=NAVY, color=NAVY)
    page.draw_rect((0, 90, PAGE_WIDTH, 94), fill=accent, color=accent)
    page.draw_rect((34, 24, 74, 64), fill=accent, color=accent, radius=0.12)
    page.insert_text((45, 54), "BH", fontname="hebo", fontsize=16, color=WHITE)
    page.insert_text((86, 39), "BLUEHARBOR", fontname="hebo", fontsize=14, color=WHITE)
    page.insert_text((86, 57), "OFFSHORE SERVICES", fontname="helv", fontsize=7.5, color=(0.78, 0.84, 0.92))
    page.insert_text((290, 39), title, fontname="hebo", fontsize=11.5, color=WHITE)
    page.insert_text((290, 57), subtitle, fontname="helv", fontsize=7.5, color=(0.8, 0.86, 0.94))
    page.insert_text((454, 77), reference, fontname="helv", fontsize=7.5, color=WHITE)


def section(page: pymupdf.Page, y: float, title: str, accent=BLUE) -> float:
    page.draw_rect((34, y, PAGE_WIDTH - 34, y + 24), fill=LIGHT, color=(0.86, 0.9, 0.95))
    page.draw_rect((34, y, 39, y + 24), fill=accent, color=accent)
    page.insert_text((49, y + 16), title.upper(), fontname="hebo", fontsize=8.5, color=NAVY)
    return y + 31


def rows(page: pymupdf.Page, y: float, values: list[tuple[str, str]], row_height: float = 27) -> float:
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
    page.insert_text((470, 819), "Page 1 of 1", fontname="helv", fontsize=7, color=SLATE)


def registration_pdf() -> Path:
    document, page = new_document("Corporate Registration Extract", "Corporate registration and operating particulars")
    header(page, "CORPORATE REGISTRATION EXTRACT", "Karnataka Companies Registry", "KCR/REG/2026/1842", TEAL)
    y = 112
    y = section(page, y, "Organization profile", TEAL)
    y = rows(
        page,
        y,
        [
            ("Legal name", COMPANY),
            ("Trading name", TRADING_NAME),
            ("Entity type", "Private Limited Company"),
            ("Incorporation / CIN", f"14 February 2017 / {CIN}"),
            ("PAN / GSTIN", f"{PAN} / {GSTIN}"),
            ("Registered address", ADDRESS),
        ],
        row_height=27,
    )
    y += 12
    y = section(page, y, "Primary contact and operating profile", BLUE)
    y = rows(
        page,
        y,
        [
            ("Primary contact", "Ira Menon, Head - Commercial Operations"),
            ("Email / phone", "ira.menon@blueharboroffshore.in / +91 90006 78124"),
            ("Business activity", "Offshore vessel support, port services and marine cargo handling"),
            ("Service regions", "Karnataka, Kerala, Goa and west-coast port operations"),
        ],
        row_height=30,
    )
    y += 12
    y = section(page, y, "Registry standing", VIOLET)
    page.insert_textbox(
        (42, y + 4, PAGE_WIDTH - 42, y + 49),
        "The company is registered and active with the Karnataka Companies Registry. This extract confirms corporate identity only; operating permissions, insurance validity and port-access approvals must be verified separately.",
        fontname="helv",
        fontsize=8.2,
        color=BLACK,
        lineheight=1.25,
    )
    footer(page, "KCR/REG/2026/1842")
    output = PACK_DIR / "01_corporate_registration_extract.pdf"
    document.save(output, garbage=4, deflate=True)
    document.close()
    return output


def tax_pdf() -> Path:
    document, page = new_document("GST Registration Certificate", "Goods and Services Tax registration")
    header(page, "GST REGISTRATION CERTIFICATE", "Form GST REG-06 | Registration Copy", "GST/KA/2026/7741", VIOLET)
    y = 112
    page.draw_rect((34, y, PAGE_WIDTH - 34, y + 48), fill=(0.95, 0.93, 1), color=(0.78, 0.68, 0.95), radius=0.08)
    page.insert_text((48, y + 18), "GOODS AND SERVICES TAX IDENTIFICATION NUMBER", fontname="helv", fontsize=7.5, color=SLATE)
    page.insert_text((48, y + 38), GSTIN, fontname="hebo", fontsize=14, color=VIOLET)
    page.insert_text((430, y + 31), "STATUS: ACTIVE", fontname="hebo", fontsize=9, color=(0.05, 0.55, 0.34))
    y += 62
    y = section(page, y, "Registration particulars", VIOLET)
    y = rows(
        page,
        y,
        [
            ("Legal name", COMPANY),
            ("Trade name", TRADING_NAME),
            ("Constitution", "Private Limited Company"),
            ("PAN", PAN),
            ("Date of liability", "01 April 2017"),
            ("Registration type", "Regular"),
            ("Principal place of business", ADDRESS),
        ],
        row_height=27,
    )
    y += 12
    y = section(page, y, "Business classification", BLUE)
    y = rows(
        page,
        y,
        [
            ("Primary services / SAC", "Port support services (996751), cargo handling (996719)"),
            ("Authorized signatory", "Kabir Rao, Director"),
            ("Jurisdiction", "Karnataka State / Mangaluru South Range"),
            ("Certificate generated", "06 August 2026 at 09:20 IST"),
        ],
        row_height=29,
    )
    footer(page, "GST/KA/2026/7741")
    output = PACK_DIR / "02_gst_registration_certificate.pdf"
    document.save(output, garbage=4, deflate=True)
    document.close()
    return output


def generate_pack() -> list[Path]:
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    registration = registration_pdf()
    tax = tax_pdf()
    generated_insurance = generate_expired_insurance()
    insurance = PACK_DIR / "03_expired_marine_liability_certificate.pdf"
    copy2(generated_insurance, insurance)
    return [registration, tax, insurance]


if __name__ == "__main__":
    for path in generate_pack():
        print(f"Generated {path}")
