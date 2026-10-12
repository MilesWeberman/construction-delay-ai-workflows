from delay_ai.email_source import FolderEmailSource


def test_folder_source_reads_all_emails_oldest_first(sample_dir):
    emails = FolderEmailSource(sample_dir / "emails").fetch()
    assert len(emails) == 12
    assert [e.sent_at for e in emails] == sorted(e.sent_at for e in emails)


def test_folder_source_parses_fields(sample_dir):
    first = FolderEmailSource(sample_dir / "emails").fetch()[0]
    assert first.message_id == "order-northgate-001@northgate-supplies.example"
    assert first.sender == "orders@northgate-supplies.example"
    assert first.subject == "Order acknowledgements - Riverside Court, Leeds"
    assert "PO-24101" in first.body
