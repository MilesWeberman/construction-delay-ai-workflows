"""EmailReceived handler: extract, validate, then emit facts or ask a person to review."""

from collections.abc import Callable

from delay_ai.events import (
    DELIVERY_CONFIRMED,
    DELIVERY_DATE_CHANGED,
    EMAIL_IGNORED,
    MATERIAL_ORDERED,
    NEEDS_REVIEW,
    Emit,
    Event,
    EventStore,
)
from delay_ai.extraction import EmailExtraction, ExtractedItem, RuleFacts, apply_rules
from delay_ai.materials import build_materials
from delay_ai.models import Email, Material

Extractor = Callable[[Email, RuleFacts, list[Material]], EmailExtraction]

MIN_CONFIDENCE = 0.7


def domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower()


def make_email_handler(store: EventStore, extract: Extractor) -> Callable[[Event], list[Emit]]:
    def handle(event: Event) -> list[Emit]:
        email = Email.model_validate(event.payload)
        materials = {m.po_number: m for m in build_materials(store.all())}
        from_sender = [
            m for m in materials.values() if domain(m.supplier_email) == domain(email.sender)
        ]
        facts = apply_rules(email)
        extraction = extract(email, facts, from_sender)
        return decide(email, facts, extraction, materials, from_sender)

    return handle


def decide(
    email: Email,
    facts: RuleFacts,
    extraction: EmailExtraction,
    materials: dict[str, Material],
    from_sender: list[Material],
) -> list[Emit]:
    source = {"source_email": email.message_id}
    if extraction.kind == "not_relevant":
        return [Emit(EMAIL_IGNORED, source)]

    problems = []
    if extraction.confidence < MIN_CONFIDENCE:
        problems.append(f"Low confidence ({extraction.confidence:.0%})")
    if extraction.kind == "possible_delay":
        problems.append("Possible delay with no firm date")
    if not extraction.items:
        problems.append("No orders or deliveries found")

    is_order = extraction.kind == "order_confirmation"
    emits = []
    for item in extraction.items:
        po_number, matched_by = match_po(item, facts, from_sender)
        item_problems = check_item(item, po_number, is_order, email, facts, materials)
        problems += item_problems
        if item_problems:
            continue
        date_source = "written_in_email" if item.delivery_date in facts.dates else "inferred_by_llm"
        if is_order:
            material = Material(
                po_number=po_number,
                description=item.description,
                supplier=extraction.supplier or domain(email.sender),
                supplier_email=email.sender,
                quantity=item.quantity,
                unit=item.unit,
                planned_delivery=item.delivery_date,
            )
            payload = {"material": material.model_dump(mode="json"), "date_source": date_source}
            emits.append(Emit(MATERIAL_ORDERED, {**payload, **source}))
            continue
        old = materials[po_number].planned_delivery
        payload = {"po_number": po_number, "matched_by": matched_by, **source}
        if item.delivery_date == old:
            emits.append(Emit(DELIVERY_CONFIRMED, payload))
        else:
            change = {
                "old_delivery": str(old),
                "new_delivery": str(item.delivery_date),
                "reason": extraction.reason,
                "date_source": date_source,
            }
            emits.append(Emit(DELIVERY_DATE_CHANGED, {**payload, **change}))

    if problems:
        review = {"problems": problems, "extraction": extraction.model_dump(mode="json")}
        return [Emit(NEEDS_REVIEW, {**review, **source})]
    return emits


def match_po(
    item: ExtractedItem, facts: RuleFacts, from_sender: list[Material]
) -> tuple[str | None, str]:
    """Which PO an item refers to, and how we know."""
    if item.po_number and item.po_number in facts.po_numbers:
        return item.po_number, "po_in_email"
    if not item.po_number and len(from_sender) == 1:
        return from_sender[0].po_number, "only_order_from_sender"
    return item.po_number, "llm"


def check_item(
    item: ExtractedItem,
    po_number: str | None,
    is_order: bool,
    email: Email,
    facts: RuleFacts,
    materials: dict[str, Material],
) -> list[str]:
    if po_number is None:
        return [f"Could not tell which order '{item.description}' refers to"]
    problems = []
    if is_order and po_number not in facts.po_numbers:
        problems.append(f"{po_number} is not written in the email")
    if is_order and po_number in materials:
        problems.append(f"{po_number} is already recorded")
    if not is_order and po_number not in materials:
        problems.append(f"{po_number} is not a known order")
    elif not is_order and domain(materials[po_number].supplier_email) != domain(email.sender):
        problems.append(f"{po_number} belongs to a different supplier")
    if item.delivery_date is None:
        problems.append(f"No delivery date for {po_number}")
    elif item.delivery_date < email.sent_at.date():
        problems.append(f"Delivery date {item.delivery_date} for {po_number} is in the past")
    elif facts.dates and item.delivery_date not in facts.dates:
        problems.append(f"Date {item.delivery_date} for {po_number} is not written in the email")
    return problems
