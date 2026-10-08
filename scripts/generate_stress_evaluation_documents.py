"""Author the final held-out synthetic stress cohort; never run a model here.

The first ten packs are pinned, untouched v4 evidence. Each new pack uses
supported registration/tax/supplementary liability slots. Paragraphs are real
task evidence and plausible administrative context, rather than random noise.
"""
import hashlib
import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pymupdf
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.generate_evaluation_documents import SUPPLIERS, manifest_entry

ROOT = Path(__file__).resolve().parents[1] / "sample_documents/evaluation_sets"
REG = "01_supplier_registration_form.pdf"
TAX = "02_gst_registration_certificate.pdf"
INS = "03_certificate_of_liability_insurance.pdf"


def write_pdf(path, title, pages, scan_pages=()):
    """Readable multi-page text with lightly skewed/compressed scanned inserts."""
    doc = pymupdf.open()
    for index, (heading, paragraphs) in enumerate(pages, 1):
        page = doc.new_page(width=595, height=842)
        page.insert_text((40, 38), "SYNTHETIC EVALUATION ORIGINAL", fontsize=9)
        page.insert_text((40, 68), title, fontsize=17, fontname="hebo", color=(.14, .39, .92))
        page.insert_text((40, 99), heading, fontsize=13, fontname="hebo")
        y = 125
        for text in paragraphs:
            box = pymupdf.Rect(40, y, 555, y + 125)
            remaining = page.insert_textbox(box, text, fontsize=11, lineheight=1.45)
            if remaining < 0:
                raise ValueError(f"Paragraph does not fit: {path}/{index}")
            y += 125 - remaining + 18
        if y > 775:
            raise ValueError(f"Page overflows: {path}/{index}")
        page.insert_text((40, 812), f"Fictional evidence - not a government or production record. Page {index}", fontsize=8)
        if index in scan_pages:
            raster = page.get_pixmap(matrix=pymupdf.Matrix(220/72, 220/72).prerotate(.65),
                                     colorspace=pymupdf.csGRAY, alpha=False)
            doc.delete_page(index - 1)
            page = doc.new_page(width=595, height=842)
            page.insert_image(pymupdf.Rect(4, 4, 591, 838), stream=raster.tobytes("jpeg", jpg_quality=76))
    doc.save(path, garbage=4, deflate=True, no_new_id=True)
    doc.close()
    if scan_pages:
        transcript = "\n".join(f"[Page {i}]\n{title}\n{heading}\n" + "\n".join(paragraphs)
                               for i, (heading, paragraphs) in enumerate(pages, 1))
        path.with_suffix(".source.txt").write_text(transcript, encoding="utf-8", newline="\n")


def question(qid, kind, text, terms, evidence, *, groups=(), dates=(), amounts=(), rationale=""):
    sources = list(dict.fromkeys(name for name, page in evidence))
    allowed = {name: sorted({page for source, page in evidence if source == name}) for name in sources}
    return {"id":qid, "question_type":kind, "question":text,
            "expected_terms":list(terms), "expected_term_groups":[list(g) for g in groups],
            "expected_dates":list(dates), "expected_amounts":list(amounts),
            "expected_sources":sources, "required_sources":list(sources),
            "allowed_citation_pages":allowed,
            "citation_requirements":[{"filename":name,"pages":[page]} for name,page in evidence],
            "information_found":True, "manual_review_required":True,
            "gold_rationale":rationale or "Every requested fact is stated on the declared source pages; retain scope, role and qualifications. Page rules accept cited chunks from each required evidence page, without assuming the 280-character UI excerpt contains the full answer."}


PHRASE_ALIASES = {
    "accepted invoice":["accepted invoice","invoice acceptance","acceptance of the invoice","invoice is accepted","invoice has been accepted","invoice accepted"],
    "accepted delivery":["accepted delivery","delivery acceptance","acceptance of delivery","delivery is accepted","delivery has been accepted","delivery accepted"],
    "accepted monthly service sheet":["accepted monthly service sheet","acceptance of the monthly service sheet","monthly service sheet acceptance","monthly service sheet is accepted","monthly service sheet has been accepted"],
    "quality acceptance":["quality acceptance","acceptance after quality inspection","accepted after quality inspection","quality approval"],
    "signed service completion":["signed service completion","signed completion record","service completion is signed","signing of service completion","signed completion of service"],
}


def allow_corroboration(case, evidence):
    for name,page in evidence:
        if name not in case["expected_sources"]:
            case["expected_sources"].append(name)
        pages = case["allowed_citation_pages"].setdefault(name, [])
        if page not in pages:
            pages.append(page)


def apply_scoring_revision(case):
    """Revision 2 changes scoring only: never rewrite questions, originals or primary evidence."""
    corroboration = {"transit_limit": [(INS,3)], "before_e2_effective": [(INS,3)], "pickup_depot": [(TAX,2)]}
    if case["id"] in corroboration:
        allow_corroboration(case, corroboration[case["id"]])
        case["gold_rationale"] += " The additional declared page supports the requested distinction or corroborates the answer; primary evidence remains mandatory."
    if case["id"] == "original_aggregate":
        case["allow_scalar_amount"] = True
        case["gold_rationale"] += " A standalone currency-qualified amount may answer this single-value question without repeating annual aggregate; explanatory answers retain the scope labels."
    if case["id"] in {"height_without_permit", "permit_without_watch"}:
        case["expected_terms"] = []
        case["expected_term_groups"] = []
        case["expected_coverage_decision"] = False
        case["gold_rationale"] += " The question asks a coverage decision, not an explanation: an unambiguous denial is sufficient with the required clause citation; affirmative, uncertain and contradictory responses fail."


def missing(qid, text):
    return {"id":qid, "question_type":"safe_not_found", "question":text,
            "expected_terms":["Information not found in uploaded supplier documents."],
            "expected_sources":[], "information_found":False, "manual_review_required":True,
            "gold_rationale":"No original supplies this requested value. Related information does not establish it."}


def core(s):
    reg = [("Registered particulars", [
        f"Supplier Registration Form. Legal name: {s.legal_name}. Trading name: {s.trading_name}. Country: India. CIN: {s.cin}. Incorporation date: {s.incorporation_date}. Issuing registry: Registrar of Companies, India. Registration status: Active.",
        f"Registered office: {s.address}. Business activity: {s.product_category}. This form establishes the entity and the office used for statutory correspondence; operational schedules describe separate delivery and service arrangements.",
        "The administrative contact routes procurement clarifications and maintains the submitted originals. A vendor-master entry is separate from reviewer approval. This supplier form makes no statement that the customer's onboarding review has completed."])]
    tax = [("GST registration particulars", [
        f"GST Registration Certificate. Legal name: {s.legal_name}. Trading name: {s.trading_name}. Country: India. Permanent Account Number (PAN): {s.pan}. GSTIN: {s.gstin}. GST registration status: Registered.",
        f"Principal registered address: {s.address}. The taxpayer identifiers belong to this legal entity. Establishment addresses listed in operational schedules do not create separate taxpayer identities.",
        "This submitted copy records registration particulars only. It does not establish bank account details, customer approval, a credit rating or the result of any external sanctions screening."])]
    ins = [("Liability certificate and schedule", [
        f"Certificate of Liability Insurance. Named insured: {s.legal_name}. Insurance provider: {s.insurance_provider}. Policy number: {s.policy_number}. Policy period: 01 JUL 2026 - 30 JUN 2027. Country: India.",
        f"Declared business activity: {s.product_category}. This liability original is supplementary procurement evidence. Its attached schedules explain applicable operations, limits and conditions; a certificate heading alone does not replace those clauses.",
        "The evidence records the supplier's stated cover; it does not confirm customer onboarding approval or guarantee payment of a claim. The policy schedule and endorsements must be read together when an operation is subject to a particular limit or condition."])]
    return reg, tax, ins


def build_pack(index, slug, name, trading, address, activity, author):
    s = replace(SUPPLIERS[0], slug=slug, legal_name=name + " Private Limited", trading_name=trading,
                address=address, cin=f"U74999KA2020PTC{190000+index}", pan=f"AABCS{6200+index}F",
                gstin=f"29AABCS{6200+index}F1Z8", incorporation_date="12 September 2020",
                contact_email=f"evaluation.{slug}@example.com", product_category=activity,
                policy_number=f"HPGL/2026/ST/{24000+index}")
    entry = manifest_entry(s)
    entry.update(cohort="stress", stress_category=slug.split('_', 1)[1], document_modes={},
                 expected_ocr_pages={}, source_transcript_sha256={})
    reg, tax, ins = core(s)
    scans, cases = author(s, reg, tax, ins)
    controls = [
        question("legal_name_control", "direct_fact", "What legal name does the supplier registration form state?", [s.legal_name], [(REG,1)]),
        question("insurer_control", "direct_fact", "Which insurance provider is named on the liability certificate?", [s.insurance_provider], [(INS,1)]),
    ]
    entry["questions"] = controls + cases
    for case in entry["questions"]:
        for phrase in list(case["expected_terms"]):
            if phrase in PHRASE_ALIASES:
                case["expected_terms"].remove(phrase)
                case.setdefault("expected_term_groups", []).append(PHRASE_ALIASES[phrase])
        if case["id"] == "legal_name_control":
            allow_corroboration(case, [(TAX,1),(INS,1)])
        elif case["id"] == "entity_and_trading":
            allow_corroboration(case, [(TAX,1),(INS,1)])
        elif case["id"] == "registered_office":
            allow_corroboration(case, [(TAX,1)])
        apply_scoring_revision(case)
        if not case["information_found"]:
            reference = "Information not found in uploaded supplier documents."
        elif case["id"] == "legal_name_control":
            reference = f"The registration form states the legal name as {s.legal_name}."
        elif case["id"] == "insurer_control":
            reference = f"The liability certificate names {s.insurance_provider} as the provider."
        elif case["id"] == "entity_and_trading":
            reference = f"Invoice legal name: {s.legal_name}. Trading name: {s.trading_name}. Payment is Net 60 days after quality acceptance."
        else:
            reference = REFERENCE_ANSWERS[case["id"]]
        case["reference_answer"] = reference
    directory = ROOT / slug
    directory.mkdir(exist_ok=True)
    for kind, pages in [("registration",reg),("tax",tax),("insurance",ins)]:
        path = directory / entry["documents"][kind]
        ocr_pages = scans.get(kind, [])
        write_pdf(path, {"registration":"Supplier Registration Form", "tax":"GST Registration Certificate", "insurance":"Certificate of Liability Insurance"}[kind], pages, ocr_pages)
        entry["document_modes"][kind] = "mixed" if ocr_pages else "native"
        entry["expected_ocr_pages"][kind] = ocr_pages
        if ocr_pages:
            entry["source_transcript_sha256"][kind] = hashlib.sha256(path.with_suffix(".source.txt").read_bytes()).hexdigest()
    entry["document_sha256"] = {kind:hashlib.sha256((directory/filename).read_bytes()).hexdigest() for kind,filename in entry["documents"].items()}
    (directory/"ground_truth.json").write_text(json.dumps(entry, indent=2), encoding="utf-8", newline="\n")
    return entry


def logistics(s, reg, tax, ins):
    reg.extend([
        ("Operational locations and dispatch", [
            "Warehouse receiving location: Dock 4, Hoskote Freight Park, Bengaluru, Karnataka 562114. The registered office is not a receiving dock. Dispatch coordinators book a warehouse slot before sending a vehicle.",
            "The service portfolio includes road transit, storage in approved warehouses and subcontracted line-haul carriage. These are separate insured operations, rather than a single interchangeable coverage limit.",
            "Delivery discrepancies are recorded against the consignment and the booked slot. A receiving acknowledgement records quantity and condition at the dock; it does not certify insurance adequacy."]),
        ("Payment administration", [
            "Payment terms: Net 45 days from accepted invoice. Acceptance requires a matched consignment receipt and the supplier's invoice. The dispatch booking date does not start the payment clock.",
            "Document routing: the warehouse team records receipt; procurement handles service exceptions; AP checks invoice completeness. Urgent dispatch instructions do not amend the agreed payment terms.",
            "The supplier has not submitted bank account details or an external rating within this evidence set. These must be collected and reviewed through the customer's normal workflow."])
    ])
    tax.append(("Establishment and invoice notes", ["The warehouse establishment is Dock 4, Hoskote Freight Park, Bengaluru, Karnataka 562114. It is an operating location of the legal entity named on page 1.","Invoices use the registered legal name and tax identifiers. Warehouse receiving instructions belong to the operational schedule, while tax correspondence goes to the registered office."]))
    ins.extend([
        ("Road transit clause", ["Road transit limit: INR 20,00,000 per consignment. This limit applies to goods during the declared road journey and is separate from warehouse storage and subcontractor limits.","Transit deductible: INR 25,000 per claim. A consignment docket and receipt at destination are needed for claim notification. A vehicle carrying several consignments does not turn the per-consignment limit into an annual aggregate.","A claim notification must identify the journey, consignment and observed loss. Delivery delays without physical loss are excluded; no promised delivery-time guarantee is created by this certificate."]),
        ("Warehouse storage clause", ["Warehouse storage limit: INR 50,00,000 per occurrence at an approved warehouse. This is the storage limit; do not apply the road-transit per-consignment limit to stock already received at the warehouse.","Storage deductible: INR 40,000 per claim. Inventory records and a receiving acknowledgement support identification of stored goods. The approved-warehouse condition remains applicable even if a consignment was previously covered in transit.","The certificate does not provide separate site-specific asset valuations. The storage limit is not a statement of stock value or a bank balance."]),
        ("Subcontracted carriage condition", ["Subcontracted carriage sublimit: INR 10,00,000 per consignment. Cover for a subcontracted journey applies only when the carrier is named on the approved-carrier register before dispatch.","A carrier that is not named on the approved-carrier register is outside the stated subcontracted-carriage cover. Booking a warehouse slot does not add a carrier to that register.","No approved-carrier register is supplied here. A subcontractor's identity or current approval cannot be inferred from the certificate, so the customer must obtain that evidence before relying on this condition."])
    ])
    return {}, [
        question("transit_limit", "stress_retrieval", "What is the road-transit limit per consignment? Distinguish it from storage cover.", ["consignment"], [(INS,2)], amounts=[2000000]),
        question("storage_limit", "stress_retrieval", "What cover limit applies to goods already received into an approved warehouse, and on what basis?", ["occurrence"], [(INS,3)], amounts=[5000000]),
        question("subcontract_limit", "stress_retrieval", "What is the subcontracted-carriage sublimit and what register condition must be met before dispatch?", ["consignment"], [(INS,4)], groups=[["approved-carrier register","approved carrier register"],["before dispatch","prior to dispatch"]], amounts=[1000000]),
        question("transit_and_storage", "stress_synthesis", "Compare the road-transit and warehouse-storage limits, labelling which basis belongs to each operation.", ["transit","storage","consignment","occurrence"], [(INS,2),(INS,3)], amounts=[2000000,5000000]),
        question("dock_and_payment", "stress_synthesis", "For AP and dispatch handover, give the warehouse receiving location and payment days with the payment-clock trigger.", ["Dock 4","Hoskote Freight Park","562114","45","accepted invoice"], [(REG,2),(REG,3)]),
        question("unlisted_carrier", "stress_conditional", "A carrier is not named on the approved-carrier register before dispatch. Does the submitted subcontracted-carriage clause cover that journey? Explain the condition.", ["carrier","register"], [(INS,4)], groups=[["not covered","outside","no cover","not apply","does not apply"]]),
        missing("missing_carrier_approval", "Which subcontracted carrier has actually been approved on this supplier's approved-carrier register?"),
        missing("missing_credit_rating", "What external credit rating has been assigned to this supplier?")]


def food(s, reg, tax, ins):
    reg.extend([
        ("Food service and payment schedule", ["Services: chilled meal preparation and delivery to customer sites. Payment terms: Net 30 days after accepted delivery. The receiving team records acceptance after temperature and quantity checks; invoice issue alone does not start this period.","Cold-chain dispatch records accompany each delivery. This schedule describes the contracted service and payment trigger; it is not a laboratory result or a statement of shelf life for every menu item."]),
        ("Records and correspondence", ["Procurement requests the menu, site schedule and receiving instructions separately. Food allergen declarations must be obtained for the relevant menu; this supplier registration form does not list them.","Liability cover is described in the separate insurance certificate and attached amendments. Registration particulars do not decide which insurance endorsement takes precedence."])
    ])
    tax.append(("Taxpayer scope", ["The GST registration covers the legal entity named on page 1. Service invoices distinguish the delivery acceptance record from the invoice issue date.","This certificate does not provide a food-safety inspection score, laboratory findings, menu allergens or the outcome of customer onboarding review."]))
    ins.extend([
        ("Original product-liability schedule", ["Original product-liability schedule issued 01 JUL 2026: annual aggregate limit INR 20,00,000. Product cover originally ends on 30 JUN 2027. These are the original terms, subject to the later signed amendments in this same certificate bundle.","The original schedule covers physical injury caused by supplied meals within the described business activity. It does not create a recall-expense allowance unless an endorsement states one."]),
        ("Renewal endorsement E1", ["Renewal endorsement E1 issued 15 MAY 2027. Effective 01 JUL 2027, it extends product-liability cover through 30 JUN 2028 and replaces the original expiry for that renewal period. It sets the annual aggregate at INR 30,00,000 from its effective date.","Endorsement E1 explicitly supersedes the original schedule for expiry and aggregate during the renewal period. Before 01 JUL 2027, the original aggregate remains in force. Other original conditions remain unchanged."]),
        ("Amendment E2 - effective date and precedence", ["Amendment E2 issued 20 MAY 2027. Effective 01 AUG 2027, it replaces E1's annual aggregate limit with INR 40,00,000. E2 does not change the renewal expiry of 30 JUN 2028.","Between 01 JUL 2027 and 31 JUL 2027, E1's INR 30,00,000 annual aggregate applies. From 01 AUG 2027, E2's INR 40,00,000 annual aggregate applies. These changes have explicit effective dates; choosing the latest issue date without considering the requested date is incorrect."])
    ])
    return {}, [
        question("original_aggregate", "stress_retrieval", "What annual aggregate was stated in the original product-liability schedule, before either amendment becomes effective?", ["annual","aggregate"], [(INS,2)], amounts=[2000000]),
        question("renewal_expiry", "stress_retrieval", "What expiry does endorsement E1 establish for the renewal period?", [], [(INS,3)], dates=["2028-06-30"]),
        question("e2_preserved_expiry", "stress_retrieval", "What annual aggregate does amendment E2 set, and which expiry does it explicitly leave unchanged?", ["annual","aggregate"], [(INS,4)], amounts=[4000000], dates=["2028-06-30"]),
        question("july_vs_august", "stress_synthesis", "Compare the applicable annual product-liability aggregate on 15 July 2027 and on 15 August 2027. Label each date and limit.", [], [(INS,3),(INS,4)], groups=[["July","JUL"],["August","AUG"]], amounts=[3000000,4000000]),
        question("ap_and_renewal", "stress_synthesis", "For the procurement handover, state the payment days and trigger, plus the renewed insurance expiry.", ["30","accepted delivery"], [(REG,2),(INS,3)], dates=["2028-06-30"]),
        question("before_e2_effective", "stress_conditional", "As of 20 July 2027, may AP record E2's higher annual aggregate just because E2 was issued in May? Give the applicable limit and E2's effective date.", [], [(INS,4)], groups=[["not yet","no","not effective","does not apply"]], amounts=[3000000], dates=["2027-08-01"]),
        missing("missing_recall_limit", "What monetary recall-expense limit has been approved for this supplier?"),
        missing("missing_food_score", "What numerical food-safety inspection score did the authority give this supplier?")]


def facilities(s, reg, tax, ins):
    reg.extend([
        ("Scanned service allocation", ["Emergency facilities helpdesk service window: 06:00 to 22:00, Monday to Saturday. The Sunday schedule is separately booked by the customer and no standard Sunday hours are stated here.","Non-emergency housekeeping is staffed 09:00 to 17:00 on business days. These housekeeping hours do not define the emergency helpdesk window.","Escalation uses the customer site ticket number. The arrival of a technician is recorded separately from a telephone acknowledgement, so response acknowledgement must not be described as a guaranteed resolution."]),
        ("Service levels and invoicing", ["Priority-one incident acknowledgement: within 45 minutes of a logged ticket during the contracted service window. The 45-minute target is an acknowledgement target, not an onsite-arrival or resolution deadline.","Standard invoice terms: Net 30 days from accepted monthly service sheet. Attendance logs and a signed service sheet support the invoice; they do not extend the helpdesk operating window."])
    ])
    tax.append(("Scanned establishment record", ["Service establishment: Suite 6, Yelahanka Service Centre, Bengaluru, Karnataka 560064. This operating address is separate from the registered office on page 1.","The establishment uses the taxpayer identity on page 1. Tax registration alone does not establish the customer's Sunday staffing schedule or service acceptance."]))
    ins.extend([
        ("Scanned liability limits", ["Public-liability limit: INR 15,00,000 per occurrence for declared facilities work. The deductible is INR 20,000 per claim; the deductible is not the cover limit.","Care, custody and control of customer property is subject to an INR 3,00,000 sublimit. This property sublimit does not replace the public-liability occurrence limit."]),
        ("Working-at-height condition", ["Work above three metres is covered only when a site permit is issued before the work starts. Work without that permit is excluded from the declared working-at-height extension.","The customer issues site permits under its own controls. No issued permit is contained in these originals, so permit compliance for a particular job is not established by this certificate."])
    ])
    return {"registration":[2],"tax":[2],"insurance":[2]}, [
        question("helpdesk_window", "stress_retrieval", "What hours and weekdays are stated for the emergency facilities helpdesk, rather than housekeeping?", ["Monday","Saturday"], [(REG,2)], groups=[["06:00","6:00","6 am","6am"],["22:00","10 pm","10pm"]]),
        question("acknowledgement_target", "stress_retrieval", "What is the priority-one incident acknowledgement target, and is it an onsite-arrival or resolution deadline?", ["45"], [(REG,3)], groups=[["acknowledgement","acknowledgment"],["not","neither"]]),
        question("public_liability", "stress_retrieval", "Give the public-liability occurrence limit and its deductible, keeping the two roles separate.", ["occurrence","deductible"], [(INS,2)], amounts=[1500000,20000]),
        question("service_and_payment", "stress_synthesis", "Summarise the emergency helpdesk window and the invoice payment days and trigger.", ["Monday","Saturday","30","accepted monthly service sheet"], [(REG,2),(REG,3)], groups=[["06:00","6:00","6 am","6am"],["22:00","10 pm","10pm"]]),
        question("operating_site_and_property", "stress_synthesis", "What is the service-establishment address, and what sublimit applies to customer property in the supplier's care, custody and control?", ["Suite 6","Yelahanka Service Centre","560064"], [(TAX,2),(INS,2)], amounts=[300000]),
        question("height_without_permit", "stress_conditional", "A job is above three metres and no site permit was issued before work. Does the declared working-at-height extension cover it?", ["permit"], [(INS,3)], groups=[["excluded","not covered","does not cover","no cover"]]),
        missing("missing_sunday_hours", "What exact standard Sunday hours has the customer contracted for the emergency helpdesk?"),
        missing("missing_permit_number", "What is the number of the site permit actually issued for the next working-at-height job?")]


def components(s, reg, tax, ins):
    reg.extend([
        ("Location-role schedule", ["Manufacturing plant: Shed 18, Doddaballapur Industrial Area, Bengaluru, Karnataka 561203. Dispatch depot: Bay 9, Nelamangala Freight Yard, Bengaluru, Karnataka 562123. Neither location replaces the registered office on page 1.","Goods for customer pickup are collected from the dispatch depot. Statutory correspondence is addressed to the registered office. Factory audits take place at the manufacturing plant; a delivery route instruction does not change the legal address."]),
        ("Commercial schedule", ["Payment terms: Net 60 days after quality acceptance. Physical unloading is not quality acceptance. Inspection records identify the accepted batch before AP begins this payment period.","The supplier trades as Chitra Components but invoices under the full legal entity named on page 1. A trading name is not a separate payee or a different taxpayer."])
    ])
    tax.append(("Additional place of business", ["Additional place of business: Shed 18, Doddaballapur Industrial Area, Bengaluru, Karnataka 561203. It is the manufacturing plant of the registered legal entity, not its registered office.","Tax invoices identify the same legal entity and GSTIN listed on page 1. Bay 9 at the dispatch yard is used for pickup rather than statutory correspondence."]))
    ins.extend([
        ("Operations and claims correspondence", ["Covered activity: precision machining and assembly of industrial components at the declared plant. Product-liability annual aggregate: INR 25,00,000. Export recall expenses are not listed as covered costs.","Claims correspondence address: Claims Desk 2, Residency Road, Bengaluru, Karnataka 560025. This is the insurer's routing address, not the supplier's registered office, plant or dispatch depot."]),
        ("Territorial condition", ["Declared territory for product-liability cover: India. This schedule excludes product claims arising from supply into the United States or Canada.","Shipping a batch from the Indian dispatch depot does not change the stated territorial exclusion. A separate export endorsement would be needed to establish different territory, but no export endorsement is supplied here."])
    ])
    return {}, [
        question("registered_office", "stress_retrieval", "Which address should be entered as the registered office for statutory correspondence, rather than plant, depot or claims desk?", ["Unit 71","Jigani Business Centre","560105"], [(REG,1)]),
        question("pickup_depot", "stress_retrieval", "Where should a customer collect finished goods? Give the dispatch location, not the manufacturing plant.", ["Bay 9","Nelamangala Freight Yard","562123"], [(REG,2)]),
        question("claims_routing", "stress_retrieval", "Where is insurance claims correspondence routed, and whose routing address is it?", ["Claims Desk 2","Residency Road","560025","insurer"], [(INS,2)]),
        question("entity_and_trading", "stress_synthesis", "For ERP, separate the full invoice legal name from the trading name, and state the payment period and its trigger.", [s.legal_name,s.trading_name,"60","quality acceptance"], [(REG,1),(REG,3)]),
        question("factory_and_cover", "stress_synthesis", "For a plant audit, give the manufacturing location and the declared insured activity at that plant.", ["Shed 18","Doddaballapur Industrial Area","561203","precision machining","assembly"], [(REG,2),(INS,2)]),
        question("canada_claim", "stress_conditional", "A component is supplied into Canada. Does the declared India product-liability territory cover the resulting product claim? Explain the stated exclusion.", ["Canada","India"], [(INS,3)], groups=[["excluded","excludes","not covered","does not cover"]]),
        missing("missing_export_endorsement", "What is the number of an issued export endorsement that extends this supplier's product cover to Canada?"),
        missing("missing_bank_account", "Which beneficiary bank account number should AP use for this supplier?")]


def maintenance(s, reg, tax, ins):
    reg.extend([
        ("Maintenance response levels", ["Critical breakdown telephone acknowledgement: within 30 minutes of a logged ticket during service hours. Planned preventive maintenance is booked with at least five business days' notice.","The acknowledgement target is not a repair-completion guarantee. Repair scheduling depends on access, diagnosis and spare availability. The originals do not state a guaranteed restoration time."]),
        ("Service hours and commercial terms", ["Service hours: 08:00 to 18:00, Monday to Friday. Standard payment terms: Net 30 days after signed service completion. A diagnostic visit without a signed completion record does not start that payment period.","The supplier services industrial pumps and rotating equipment. Planned work records identify the serviced asset; the customer's reviewer decides onboarding readiness separately."])
    ])
    tax.append(("Service establishment", ["Operating workshop: Plot 8, Bidadi Engineering Estate, Bengaluru, Karnataka 562109. The workshop belongs to the legal entity named on page 1.","The taxpayer certificate does not provide a repair success rate, restoration guarantee or approved spare-part catalogue."]))
    ins.extend([
        ("Public liability and deductible", ["Public-liability occurrence limit: INR 35,00,000. Per-claim deductible: INR 50,000. These apply to declared maintenance activities subject to the schedule's stated conditions.","Routine servicing does not expand the occurrence limit. The deductible is borne per claim and must not be reported as the policy limit."]),
        ("Hot-work extension", ["Hot work is covered only when a hot-work permit is issued before work and a fire watch remains present for 60 minutes after completion. Both conditions are mandatory for this extension.","Work with a permit but without the required post-work fire watch is excluded from the hot-work extension. This evidence does not contain an issued hot-work permit for a particular customer job."]),
        ("Electrical-work exclusion", ["Live electrical work is excluded. De-energised work is permitted only after documented isolation and a verified lockout record. A verbal statement that power is off is not the required record.","This schedule gives cover conditions, not authority to perform a customer job. It contains no approved job permit, external compliance approval or guaranteed repair completion time."])
    ])
    return {}, [
        question("acknowledgement_vs_repair", "stress_retrieval", "What telephone acknowledgement target applies to a critical breakdown, and does it guarantee repair completion?", ["30"], [(REG,2)], groups=[["acknowledgement","acknowledgment"],["not","no","does not"]]),
        question("limit_and_deductible", "stress_retrieval", "State the public-liability occurrence limit and per-claim deductible with their roles labelled.", ["occurrence","deductible"], [(INS,2)], amounts=[3500000,50000]),
        question("electrical_condition", "stress_retrieval", "What does the schedule say about live electrical work and the records needed for de-energised work?", ["live","excluded","isolation","lockout"], [(INS,4)]),
        question("hot_work_conditions", "stress_synthesis", "For a maintenance handover, give both mandatory hot-work cover conditions and the policy occurrence limit.", ["permit","fire watch","60"], [(INS,3),(INS,2)], groups=[["before work","prior to work"],["after completion","after work","post-work"]], amounts=[3500000]),
        question("hours_and_ap", "stress_synthesis", "State normal service weekdays and hours, and the payment period and completion-record trigger.", ["Monday","Friday","30","signed service completion"], [(REG,3)], groups=[["08:00","8:00","8 am","8am"],["18:00","6 pm","6pm"]]),
        question("permit_without_watch", "stress_conditional", "Hot work has a permit, but no fire watch remains after completion. Does the submitted hot-work extension cover this situation?", ["fire watch"], [(INS,3)], groups=[["excluded","not covered","does not cover","no cover"]]),
        missing("missing_restoration", "What exact guaranteed repair-completion time applies to a critical breakdown?"),
        missing("missing_repair_success", "What audited repair success percentage has this supplier achieved?")]


REFERENCE_ANSWERS = {
    "transit_limit":"Road transit is limited to INR 20 lakh per consignment; this is the transit limit, separate from storage cover.",
    "storage_limit":"At an approved warehouse, the storage limit is INR 50 lakh per occurrence.",
    "subcontract_limit":"Subcontracted carriage is limited to INR 10 lakh per consignment and requires the carrier to be on the approved-carrier register before dispatch.",
    "transit_and_storage":"Road transit: INR 20 lakh per consignment. Warehouse storage: INR 50 lakh per occurrence.",
    "dock_and_payment":"Receive at Dock 4, Hoskote Freight Park, Bengaluru, Karnataka 562114. AP terms are Net 45 days from accepted invoice.",
    "unlisted_carrier":"No cover applies: a carrier not named on the approved-carrier register before dispatch is outside the subcontracted-carriage clause.",
    "original_aggregate":"The original annual product-liability aggregate is INR 20 lakh.",
    "renewal_expiry":"Endorsement E1 establishes renewal expiry on 30 June 2028.",
    "e2_preserved_expiry":"E2 sets the annual aggregate at INR 40 lakh and leaves the expiry of 30 June 2028 unchanged.",
    "july_vs_august":"On 15 July 2027, the annual aggregate is INR 30 lakh under E1. On 15 August 2027, INR 40 lakh applies under E2.",
    "ap_and_renewal":"Payment is Net 30 days after accepted delivery. The renewed insurance expiry is 30 June 2028.",
    "before_e2_effective":"No. On 20 July 2027, the applicable annual aggregate is INR 30 lakh. E2 is not yet effective; its effective date is 01 August 2027.",
    "helpdesk_window":"The emergency helpdesk operates 06:00 to 22:00, Monday to Saturday; these are not the housekeeping hours.",
    "acknowledgement_target":"The priority-one target is acknowledgement within 45 minutes of a logged ticket during the service window. It is not an onsite-arrival or resolution deadline.",
    "public_liability":"Public liability: INR 15 lakh per occurrence. Deductible: INR 20,000 per claim.",
    "service_and_payment":"Emergency helpdesk: 06:00 to 22:00, Monday to Saturday. Payment: Net 30 days from accepted monthly service sheet.",
    "operating_site_and_property":"The service establishment is Suite 6, Yelahanka Service Centre, Bengaluru, Karnataka 560064. Customer property in care, custody and control has an INR 3 lakh sublimit.",
    "height_without_permit":"It is excluded: work above three metres needs a site permit issued before work starts, and this job lacks that permit.",
    "registered_office":"Use Unit 71, Jigani Business Centre, Bengaluru, Karnataka 560105 as the registered office for statutory correspondence.",
    "pickup_depot":"Collect from the dispatch depot: Bay 9, Nelamangala Freight Yard, Bengaluru, Karnataka 562123.",
    "claims_routing":"Insurance claims correspondence goes to Claims Desk 2, Residency Road, Bengaluru, Karnataka 560025. This is the insurer's routing address.",
    "factory_and_cover":"The manufacturing location is Shed 18, Doddaballapur Industrial Area, Bengaluru, Karnataka 561203. The insured activity is precision machining and assembly of industrial components.",
    "canada_claim":"No. The declared territory is India; product claims arising from supply into Canada are excluded.",
    "acknowledgement_vs_repair":"Telephone acknowledgement for a critical breakdown is within 30 minutes of a logged ticket during service hours. It is not a repair-completion guarantee.",
    "limit_and_deductible":"Public liability limit: INR 35 lakh per occurrence. The deductible is INR 50,000 per claim.",
    "electrical_condition":"Live electrical work is excluded. De-energised work needs documented isolation and a verified lockout record.",
    "hot_work_conditions":"Hot work needs a permit issued before work and a fire watch for 60 minutes after completion. The public-liability occurrence limit is INR 35 lakh.",
    "hours_and_ap":"Service is 08:00 to 18:00, Monday to Friday. Payment is Net 30 days after signed service completion.",
    "permit_without_watch":"It is excluded from the hot-work extension: a permit alone is insufficient without the required fire watch after completion.",
}


def main():
    previous = ROOT / "baseline_manifest_v4.json"
    if not previous.exists():
        current = (ROOT / "evaluation_manifest.json").read_bytes()
        if json.loads(current)["version"] != 4:
            raise ValueError("Pin v4 before generating v5.")
        previous.write_bytes(current)
    pinned = json.loads(previous.read_text())
    entries = list(pinned["suppliers"])
    definitions = [
        (1,"dakshin_logistics","Dakshin Freight Services","Dakshin Freight","Suite 11, Hebbal Business Park, Bengaluru, Karnataka 560024","Road freight and warehouse handling",logistics),
        (2,"amrutha_food","Amrutha Meal Services","Amrutha Kitchens","Unit 14, Electronic City Service Park, Bengaluru, Karnataka 560100","Chilled meal preparation and delivery",food),
        (3,"varsha_facilities","Varsha Facilities Services","Varsha Facilities","Office 23, Hebbal Service Hub, Bengaluru, Karnataka 560024","Facilities helpdesk and housekeeping",facilities),
        (4,"chitra_components","Chitra Industrial Components","Chitra Components","Unit 71, Jigani Business Centre, Bengaluru, Karnataka 560105","Precision machining and assembly of industrial components",components),
        (5,"udaya_maintenance","Udaya Equipment Maintenance","Udaya Maintenance","Office 12, Bidadi Service Park, Bengaluru, Karnataka 562109","Industrial pump and rotating-equipment maintenance",maintenance),
    ]
    entries.extend(build_pack(*definition) for definition in definitions)
    counts = Counter(q["question_type"] for s in entries for q in s["questions"])
    manifest = {"version":5,"scoring_revision":2,
        "description":"Pinned 100-question core plus a separate 50-question multi-page stress cohort. Synthetic evidence authored before live calls; complex stress answers require human audit.",
        "expected_counts":{"suppliers":15,"documents":45,"questions":150,"question_types":dict(sorted(counts.items()))},
        "suppliers":entries}
    (ROOT/"evaluation_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    print("Generated v5: 15 suppliers, 45 PDFs, 150 questions; stress cohort 5/15/50.")


if __name__ == "__main__":
    main()
