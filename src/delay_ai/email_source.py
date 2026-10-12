"""Where emails come from. The pilot reads .eml files; Gmail and Outlook come later."""

from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Protocol

from delay_ai.models import Email


class EmailSource(Protocol):
    def fetch(self) -> list[Email]:
        """Return all available emails, oldest first."""
        ...


class FolderEmailSource:
    """Reads every .eml file in a folder."""

    def __init__(self, folder: Path):
        self.folder = folder

    def fetch(self) -> list[Email]:
        emails = [parse_eml(path.read_bytes()) for path in self.folder.glob("*.eml")]
        return sorted(emails, key=lambda e: e.sent_at)


def parse_eml(raw: bytes) -> Email:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    body = msg.get_body(preferencelist=("plain",))
    return Email(
        message_id=msg["Message-ID"].strip("<>"),
        sender=parseaddr(msg["From"])[1],
        subject=msg["Subject"],
        sent_at=parsedate_to_datetime(msg["Date"]),
        body=body.get_content().strip() if body else "",
    )
