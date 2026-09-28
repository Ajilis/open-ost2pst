from datetime import datetime, timezone
import tempfile
from pathlib import Path

import pytest

from open_ost2pst.pst.bridge import datetime_to_filetime, mailbox_to_messaging
from open_ost2pst.pst.ltp.pc import PropertyType
from open_ost2pst.pst.messaging import MessagingBuilder
from open_ost2pst.reader.pff_reader import load_mailbox


pypff = pytest.importorskip("pypff")

PSETID_APPOINTMENT = "00062002-0000-0000-c000-000000000046"
PSETID_TASK = "00062003-0000-0000-c000-000000000046"
PSETID_ADDRESS = "00062004-0000-0000-c000-000000000046"

PIDLID_LOCATION = 0x8208
PIDLID_APPOINTMENT_START_WHOLE = 0x820D
PIDLID_HOME_ADDRESS = 0x801A
PIDLID_TASK_ASSIGNER = 0x8121


def _find_message(mailbox, folder_name, subject):
    folder = next(
        item for item in mailbox.root.folders
        if item.name == folder_name
    )
    return next(
        message for message in folder.messages
        if message.subject == subject
    )


def _named(message, guid, name):
    guid = guid.lower() if guid is not None else None
    return next(
        prop for prop in message.named_properties
        if (prop.guid.lower() if prop.guid is not None else None) == guid
        and prop.name == name
    )


def test_named_properties_roundtrip_calendar_contact_and_task() -> None:
    builder = MessagingBuilder(root_name="Top of Personal Folders")

    calendar = builder.add_folder(builder.root, "Calendar")
    appointment = builder.add_message(
        calendar,
        subject="Project meeting",
        message_class="IPM.Appointment",
    )
    builder.set_named_property(
        appointment,
        PIDLID_LOCATION,
        "Room 42",
        property_type=PropertyType.UNICODE,
        guid=PSETID_APPOINTMENT,
    )
    start = datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc)
    builder.set_named_property(
        appointment,
        PIDLID_APPOINTMENT_START_WHOLE,
        datetime_to_filetime(start),
        property_type=PropertyType.SYSTIME,
        guid=PSETID_APPOINTMENT,
    )

    contacts = builder.add_folder(builder.root, "Contacts")
    contact = builder.add_message(
        contacts,
        subject="Alice Example",
        message_class="IPM.Contact",
    )
    builder.set_named_property(
        contact,
        PIDLID_HOME_ADDRESS,
        "1 Example Street",
        property_type=PropertyType.UNICODE,
        guid=PSETID_ADDRESS,
    )

    tasks = builder.add_folder(builder.root, "Tasks")
    task = builder.add_message(
        tasks,
        subject="Prepare release",
        message_class="IPM.Task",
    )
    builder.set_named_property(
        task,
        PIDLID_TASK_ASSIGNER,
        "Project Manager",
        property_type=PropertyType.UNICODE,
        guid=PSETID_TASK,
    )

    source_data = builder.build().data

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source.pst"
        destination = root / "destination.pst"
        source.write_bytes(source_data)

        source_mailbox, source_report = load_mailbox(source)
        assert source_report.messages_failed == 0

        loaded_appointment = _find_message(
            source_mailbox,
            "Calendar",
            "Project meeting",
        )
        assert loaded_appointment.message_class == "IPM.Appointment"
        assert _named(
            loaded_appointment,
            PSETID_APPOINTMENT,
            PIDLID_LOCATION,
        ).value == "Room 42"

        start_prop = _named(
            loaded_appointment,
            PSETID_APPOINTMENT,
            PIDLID_APPOINTMENT_START_WHOLE,
        )
        assert start_prop.property_type == int(PropertyType.SYSTIME)
        assert isinstance(start_prop.value, datetime)
        assert start_prop.value.replace(tzinfo=timezone.utc) == start

        loaded_contact = _find_message(
            source_mailbox,
            "Contacts",
            "Alice Example",
        )
        assert loaded_contact.message_class == "IPM.Contact"
        assert _named(
            loaded_contact,
            PSETID_ADDRESS,
            PIDLID_HOME_ADDRESS,
        ).value == "1 Example Street"

        loaded_task = _find_message(
            source_mailbox,
            "Tasks",
            "Prepare release",
        )
        assert loaded_task.message_class == "IPM.Task"
        assert _named(
            loaded_task,
            PSETID_TASK,
            PIDLID_TASK_ASSIGNER,
        ).value == "Project Manager"

        destination_builder, write_report = mailbox_to_messaging(
            source_mailbox
        )
        assert write_report.messages_written == 3
        destination.write_bytes(destination_builder.build().data)

        destination_mailbox, destination_report = load_mailbox(destination)
        assert destination_report.messages_failed == 0

        roundtrip_appointment = _find_message(
            destination_mailbox,
            "Calendar",
            "Project meeting",
        )
        assert _named(
            roundtrip_appointment,
            PSETID_APPOINTMENT,
            PIDLID_LOCATION,
        ).value == "Room 42"
        roundtrip_start = _named(
            roundtrip_appointment,
            PSETID_APPOINTMENT,
            PIDLID_APPOINTMENT_START_WHOLE,
        )
        assert isinstance(roundtrip_start.value, datetime)
        assert roundtrip_start.value.replace(tzinfo=timezone.utc) == start

        roundtrip_contact = _find_message(
            destination_mailbox,
            "Contacts",
            "Alice Example",
        )
        assert _named(
            roundtrip_contact,
            PSETID_ADDRESS,
            PIDLID_HOME_ADDRESS,
        ).value == "1 Example Street"

        roundtrip_task = _find_message(
            destination_mailbox,
            "Tasks",
            "Prepare release",
        )
        assert _named(
            roundtrip_task,
            PSETID_TASK,
            PIDLID_TASK_ASSIGNER,
        ).value == "Project Manager"
