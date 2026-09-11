"""Generate a negative-case insurance document for a VendorLens demo."""

from pathlib import Path

import pymupdf


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "sample_documents" / "negative_cases"
PAGE_WIDTH, PAGE_HEIGHT = pymupdf.paper_size("a4")

NAVY = (0.035, 0.12, 0.20)
BLUE = (0.08, 0.35, 0.55)
RED = (0.72, 0.13, 0.16)
GOLD = (0.82, 0.52, 0.08)
SLATE = (0.29, 0.35, 0.43)
LIGHT = (0.96, 0.975, 0.99)
WHITE = (1, 1, 1)
BLACK = (0.06, 0.08, 0.11)


def new_document() -> tuple[pymupdf.Document, pymupdf.Page]:
    document = pymupdf.open()
    document.set_metadata(
        {
            "title": "Certificate of Marine Liability Insurance",
            "subject": "Marine services insurance certificate",
            "creator": "Business Document Services",
            "producer": "PyMuPDF",
        }
    )
    return document, document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)


def header(page: pymupdf.Page) -> None:
    page.draw_rect((0, 0, PAGE_WIDTH, 94), fill=NAVY, color=NAVY)
    page.draw_rect((0, 90, PAGE_WIDTH, 94), fill=BLUE, color=BLUE)
    page.draw_rect((34, 24, 74, 64), fill=BLUE, color=BLUE, radius=0.12)
    page.insert_text((45, 54), "BH", fontname="hebo", fontsize=16, color=WHITE)
    page.insert_text((86, 39), "BLUEHARBOR", fontname="hebo", fontsize=14, color=WHITE)
    page.insert_text((86, 57), "OFFSHORE SERVICES", fontname="helv", fontsize=7.5, color=(0.78, 0.84, 0.92))
    page.insert_text((300, 39), "CERTIFICATE OF MARINE LIABILITY INSURANCE", fontname="hebo", fontsize=10.5, color=WHITE)
    page.insert_text((454, 77), "COI/MAR/2025/61184", fontname="helv", fontsize=7.5, color=WHITE)


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


def footer(page: pymupdf.Page) -> None:
    page.draw_line((34, 802), (PAGE_WIDTH - 34, 802), color=(0.82, 0.85, 0.89), width=0.7)
    page.insert_text((34, 819), "Reference: COI/MAR/2025/61184", fontname="helv", fontsize=7, color=SLATE)
    page.insert_text((470, 819), "Page 1 of 1", fontname="helv", fontsize=7, color=SLATE)


def generate() -> Path:
    document, page = new_document()
    header(page)
    y = 112
    page.draw_rect((34, y, PAGE_WIDTH - 34, y + 48), fill=(1, 0.94, 0.94), color=(0.9, 0.58, 0.6), radius=0.08)
    page.insert_text((47, y + 18), "CERTIFICATE STATUS", fontname="helv", fontsize=7.5, color=SLATE)
    page.insert_text((47, y + 37), "EXPIRED - NOT IN FORCE", fontname="hebo", fontsize=12, color=RED)
    page.insert_text((326, y + 18), "POLICY PERIOD", fontname="helv", fontsize=7.5, color=SLATE)
    page.insert_text((326, y + 37), "01 JAN 2025 - 31 DEC 2025", fontname="hebo", fontsize=9.5, color=RED)
    y += 62
    y = section(page, y, "Insured and policy details", BLUE)
    y = rows(
        page,
        y,
        [
            ("Named insured", "BlueHarbor Offshore Services Private Limited"),
            ("Insured address", "Jetty 4, New Mangalore Port, Panambur, Mangaluru, Karnataka 575010"),
            ("Country", "India"),
            ("Insurer", "Northstar Maritime Underwriters Limited"),
            ("Policy number", "NMU/MAR/GL/2025/61184"),
            ("Coverage", "Marine liability, port operations and cargo-handling liability"),
        ],
        row_height=28,
    )
    y += 12
    y = section(page, y, "Coverage and renewal status", GOLD)
    y = rows(
        page,
        y,
        [
            ("Each occurrence", "INR 1,50,00,000"),
            ("Deductible", "INR 5,00,000 per occurrence"),
            ("Renewal status", "Renewal premium unpaid; policy lapsed on 31 December 2025"),
            ("Coverage position", "No coverage is available for incidents occurring after the expiry date"),
        ],
        row_height=31,
    )
    y += 12
    y = section(page, y, "Certificate statement", RED)
    page.insert_textbox(
        (42, y + 3, PAGE_WIDTH - 42, y + 53),
        "This certificate is issued for verification of historical policy details. The policy shown above has expired and is not currently valid. A renewed certificate must be provided before supplier onboarding or any port, cargo, or marine service engagement.",
        fontname="helv",
        fontsize=8.2,
        color=BLACK,
        lineheight=1.25,
    )
    y += 68
    page.draw_line((52, y + 34), (220, y + 34), color=SLATE, width=0.8)
    page.insert_text((52, y + 49), "Leena Varghese", fontname="hebo", fontsize=8, color=NAVY)
    page.insert_text((52, y + 63), "Marine Underwriting Officer", fontname="helv", fontsize=7.5, color=SLATE)
    page.draw_circle((455, y + 31), 39, color=RED, width=1.5)
    page.draw_circle((455, y + 31), 32, color=RED, width=0.7)
    page.insert_textbox((422, y + 12, 488, y + 51), "EXPIRED\nPOLICY", fontname="hebo", fontsize=7, color=RED, align=1)
    footer(page)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / "04_expired_marine_liability_certificate.pdf"
    document.save(output, garbage=4, deflate=True)
    document.close()
    return output


if __name__ == "__main__":
    print(f"Generated {generate()}")
