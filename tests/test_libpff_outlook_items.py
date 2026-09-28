from datetime import datetime, timezone
import tempfile
from pathlib import Path

import pytest

from open_ost2pst.pst.bridge import mailbox_to_messaging
from open_ost2pst.pst.messaging import MessagingBuilder
from open_ost2pst.pst.outlook_items import (
    IPF_APPOINTMENT,
    IPF_CONTACT,
    IPF_TASK,
    LID_APPOINTMENT_END_WHOLE,
    LID_APPOINTMENT_START_WHOLE,
    LID_EMAIL1_EMAIL_ADDRESS,
    LID_PERCENT_COMPLETE,
    LID_TASK_DUE_DATE,
    LID_TASK_STATUS,
    PSETID_ADDRESS,
    PSETID_APPOINTMENT,
    PSETID_TASK,
    PR_GIVEN_NAME,
    PR_MOBILE_TELEPHONE_NUMBER,
    TASK_STATUS_IN_PROGRESS,
)
from open_ost2pst.reader.pff_reader import load_mailbox
from tests._libpff_helpers import get_child_by_name, get_ipm_subtree


pypff = pytest.importorskip("pypff")

PR_MESSAGE_CLASS = 0x001A
PR_CONTAINER_CLASS = 0x3613


def _entry(item, property_id):
    record_set = item.get_record_set(0)
    if hasattr(record_set, "get_entry_by_type"):
        return record_set.get_entry_by_type(property_id)
    for index in range(record_set.get_number_of_entries()):
        entry = record_set.get_entry(index)
        if entry.get_entry_type() == property_id:
            return entry
    return None


def _named(message, guid, lid):
    guid_text = str(guid).lower()
    return next(
        prop
        for prop in message.named_properties
        if (prop.guid or "").lower() == guid_text and prop.name == lid
    )


def _standard(message, property_id):
    return next(
        prop
        for prop in message.standard_properties
        if prop.property_id == property_id
    )


def _folder(mailbox, name):
    return next(folder for folder in mailbox.root.folders if folder.name == name)


def test_libpff_roundtrips_calendar_contact_and_task_objects() -> None:
    builder = MessagingBuilder()
    calendar = builder.add_calendar_folder(builder.root, "Calendar")
    contacts = builder.add_contacts_folder(builder.root, "Contacts")
    tasks = builder.add_tasks_folder(builder.root, "Tasks")

    start = datetime(2026, 10, 3, 9, 30, tzinfo=timezone.utc)
    end = datetime(2026, 10, 3, 11, 0, tzinfo=timezone.utc)
    due = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)

    builder.add_meeting(
        calendar,
        subject="Design meeting",
        body="Discuss architecture",
        start=start,
        end=end,
        location="Paris",
        organizer_alias="alice@example.com",
        reminder_minutes=10,
    )
    builder.add_contact(
        contacts,
        display_name="Bob Example",
        given_name="Bob",
        surname="Example",
        company_name="Example Corp",
        email="bob@example.com",
        business_phone="+33111111111",
        mobile_phone="+33622222222",
    )
    builder.add_task(
        tasks,
        subject="Prepare release",
        body="Finish checklist",
        status=TASK_STATUS_IN_PROGRESS,
        percent_complete=0.5,
        start=start,
        due=due,
        owner="Bob Example",
    )

    source_bytes = builder.build().data

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "outlook-items.pst"
        destination = Path(directory) / "roundtrip.pst"
        source.write_bytes(source_bytes)

        store = pypff.file()
        store.open(str(source))
        try:
            ipm = get_ipm_subtree(store)
            calendar_item = get_child_by_name(ipm, "Calendar")
            contact_item = get_child_by_name(ipm, "Contacts")
            task_item = get_child_by_name(ipm, "Tasks")

            assert _entry(calendar_item, PR_CONTAINER_CLASS).get_data_as_string() == IPF_APPOINTMENT
            assert _entry(contact_item, PR_CONTAINER_CLASS).get_data_as_string() == IPF_CONTACT
            assert _entry(task_item, PR_CONTAINER_CLASS).get_data_as_string() == IPF_TASK

            assert _entry(
                calendar_item.get_sub_message(0),
                PR_MESSAGE_CLASS,
            ).get_data_as_string() == "IPM.Appointment"
            assert _entry(
                contact_item.get_sub_message(0),
                PR_MESSAGE_CLASS,
            ).get_data_as_string() == "IPM.Contact"
            assert _entry(
                task_item.get_sub_message(0),
                PR_MESSAGE_CLASS,
            ).get_data_as_string() == "IPM.Task"
        finally:
            store.close()

        mailbox, report = load_mailbox(source)
        assert report.messages_failed == 0

        calendar_model = _folder(mailbox, "Calendar")
        contacts_model = _folder(mailbox, "Contacts")
        tasks_model = _folder(mailbox, "Tasks")

        assert calendar_model.container_class == IPF_APPOINTMENT
        assert contacts_model.container_class == IPF_CONTACT
        assert tasks_model.container_class == IPF_TASK

        appointment = calendar_model.messages[0]
        assert _named(
            appointment,
            PSETID_APPOINTMENT,
            LID_APPOINTMENT_START_WHOLE,
        ).value == start
        assert _named(
            appointment,
            PSETID_APPOINTMENT,
            LID_APPOINTMENT_END_WHOLE,
        ).value == end

        contact = contacts_model.messages[0]
        assert _standard(contact, PR_GIVEN_NAME).value == "Bob"
        assert _standard(contact, PR_MOBILE_TELEPHONE_NUMBER).value == "+33622222222"
        assert _named(
            contact,
            PSETID_ADDRESS,
            LID_EMAIL1_EMAIL_ADDRESS,
        ).value == "bob@example.com"

        task = tasks_model.messages[0]
        assert _named(task, PSETID_TASK, LID_TASK_STATUS).value == TASK_STATUS_IN_PROGRESS
        assert _named(task, PSETID_TASK, LID_PERCENT_COMPLETE).value == pytest.approx(0.5)
        assert _named(task, PSETID_TASK, LID_TASK_DUE_DATE).value == due

        rebuilt, write_report = mailbox_to_messaging(mailbox)
        assert write_report.messages_written == 3
        destination.write_bytes(rebuilt.build().data)

        mailbox2, report2 = load_mailbox(destination)
        assert report2.messages_failed == 0
        assert _folder(mailbox2, "Calendar").container_class == IPF_APPOINTMENT
        assert _folder(mailbox2, "Contacts").container_class == IPF_CONTACT
        assert _folder(mailbox2, "Tasks").container_class == IPF_TASK

        contact2 = _folder(mailbox2, "Contacts").messages[0]
        assert _standard(contact2, PR_GIVEN_NAME).value == "Bob"
        assert _named(
            contact2,
            PSETID_ADDRESS,
            LID_EMAIL1_EMAIL_ADDRESS,
        ).value == "bob@example.com"

        task2 = _folder(mailbox2, "Tasks").messages[0]
        assert _named(task2, PSETID_TASK, LID_TASK_STATUS).value == TASK_STATUS_IN_PROGRESS
        assert _named(task2, PSETID_TASK, LID_PERCENT_COMPLETE).value == pytest.approx(0.5)
