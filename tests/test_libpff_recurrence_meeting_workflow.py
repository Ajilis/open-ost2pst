from datetime import datetime, timezone
import tempfile
from pathlib import Path

import pytest

from open_ost2pst.pst.bridge import mailbox_to_messaging
from open_ost2pst.pst.messaging import MessagingBuilder
from open_ost2pst.pst.outlook_items import (
    IPM_APPOINTMENT,
    IPM_MEETING_CANCELED,
    IPM_MEETING_REQUEST,
    IPM_MEETING_RESPONSE_ACCEPT,
    IPM_MEETING_RESPONSE_DECLINE,
    IPM_MEETING_RESPONSE_TENTATIVE,
    LID_APPOINTMENT_RECUR,
    LID_CLEAN_GLOBAL_OBJECT_ID,
    LID_GLOBAL_OBJECT_ID,
    LID_MEETING_TYPE,
    LID_RESPONSE_STATUS,
    LID_TASK_F_RECURRING,
    LID_TASK_RECURRENCE,
    MEETING_TYPE_FULL,
    MEETING_TYPE_REQUEST,
    PSETID_APPOINTMENT,
    PSETID_MEETING,
    PSETID_TASK,
    RESPONSE_STATUS_ACCEPTED,
    RESPONSE_STATUS_DECLINED,
    RESPONSE_STATUS_TENTATIVE,
    create_meeting_identity,
)
from open_ost2pst.pst.recurrence import (
    RecurrenceRule,
    build_appointment_recurrence,
    build_recurrence_pattern,
)
from open_ost2pst.reader.pff_reader import load_mailbox
from tests._libpff_helpers import get_child_by_name, get_ipm_subtree


pypff = pytest.importorskip("pypff")

PR_MESSAGE_CLASS = 0x001A


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


def _folder(mailbox, name):
    return next(
        folder for folder in mailbox.root.folders
        if folder.name == name
    )


def _message(folder, subject):
    return next(
        item for item in folder.messages
        if item.subject == subject
    )


def test_libpff_roundtrips_recurrence_and_meeting_workflow() -> None:
    builder = MessagingBuilder()
    calendar = builder.add_calendar_folder(builder.root, "Calendar")
    tasks = builder.add_tasks_folder(builder.root, "Tasks")
    sent = builder.add_folder(builder.root, "Sent Items")
    inbox = builder.add_folder(builder.root, "Inbox")

    start = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)

    appointment_rule = RecurrenceRule(
        "weekly",
        interval=1,
        weekdays=(0, 2),
        count=6,
    )
    task_rule = RecurrenceRule(
        "monthly",
        interval=1,
        day_of_month=5,
        count=4,
    )

    builder.add_meeting(
        calendar,
        subject="Recurring design sync",
        start=start,
        end=end,
        location="Paris",
        organizer_alias="alice@example.com",
        recurrence=appointment_rule,
    )
    builder.add_task(
        tasks,
        subject="Monthly release checklist",
        start=start,
        due=end,
        recurrence=task_rule,
    )

    identity = create_meeting_identity(
        creation_time=datetime(
            2026, 9, 28, 12, 0, tzinfo=timezone.utc
        ),
        data=bytes.fromhex(
            "00112233445566778899aabbccddeeff"
        ),
        owner_appointment_id=4242,
    )

    builder.add_meeting_request(
        sent,
        identity=identity,
        subject="Workflow meeting",
        start=start,
        end=end,
        location="Room A",
        organizer_name="Alice",
        organizer_email="alice@example.com",
        attendees=(("Bob", "bob@example.com"),),
        recurrence=appointment_rule,
    )
    builder.add_meeting_response(
        inbox,
        identity=identity,
        response="accept",
        subject="Workflow meeting",
        start=start,
        end=end,
        organizer_name="Alice",
        organizer_email="alice@example.com",
        attendee_name="Bob",
        attendee_email="bob@example.com",
        recurrence=appointment_rule,
    )
    builder.add_meeting_response(
        inbox,
        identity=identity,
        response="tentative",
        subject="Workflow meeting tentative",
        start=start,
        end=end,
        organizer_name="Alice",
        organizer_email="alice@example.com",
        attendee_name="Carol",
        attendee_email="carol@example.com",
    )
    builder.add_meeting_response(
        inbox,
        identity=identity,
        response="decline",
        subject="Workflow meeting decline",
        start=start,
        end=end,
        organizer_name="Alice",
        organizer_email="alice@example.com",
        attendee_name="Dan",
        attendee_email="dan@example.com",
    )
    builder.add_meeting_cancellation(
        sent,
        identity=identity,
        subject="Workflow meeting canceled",
        start=start,
        end=end,
        location="Room A",
        organizer_name="Alice",
        organizer_email="alice@example.com",
        attendees=(("Bob", "bob@example.com"),),
        recurrence=appointment_rule,
    )

    source_bytes = builder.build().data

    with tempfile.TemporaryDirectory() as directory:
        source = Path(directory) / "recurrence-workflow.pst"
        destination = Path(directory) / "roundtrip.pst"
        source.write_bytes(source_bytes)

        store = pypff.file()
        store.open(str(source))
        try:
            ipm = get_ipm_subtree(store)
            calendar_item = get_child_by_name(
                ipm, "Calendar"
            ).get_sub_message(0)
            assert _entry(
                calendar_item,
                PR_MESSAGE_CLASS,
            ).get_data_as_string() == IPM_APPOINTMENT

            sent_folder = get_child_by_name(ipm, "Sent Items")
            request = sent_folder.get_sub_message(0)
            cancellation = sent_folder.get_sub_message(1)
            assert _entry(
                request,
                PR_MESSAGE_CLASS,
            ).get_data_as_string() == IPM_MEETING_REQUEST
            assert _entry(
                cancellation,
                PR_MESSAGE_CLASS,
            ).get_data_as_string() == IPM_MEETING_CANCELED

            inbox_folder = get_child_by_name(ipm, "Inbox")
            classes = {
                _entry(
                    inbox_folder.get_sub_message(index),
                    PR_MESSAGE_CLASS,
                ).get_data_as_string()
                for index in range(
                    inbox_folder.get_number_of_sub_messages()
                )
            }
            assert classes == {
                IPM_MEETING_RESPONSE_ACCEPT,
                IPM_MEETING_RESPONSE_TENTATIVE,
                IPM_MEETING_RESPONSE_DECLINE,
            }
        finally:
            store.close()

        mailbox, report = load_mailbox(source)
        assert report.messages_failed == 0

        appointment = _folder(mailbox, "Calendar").messages[0]
        recurrence = _named(
            appointment,
            PSETID_APPOINTMENT,
            LID_APPOINTMENT_RECUR,
        )
        assert recurrence.value == build_appointment_recurrence(
            appointment_rule,
            start=start,
            end=end,
        )

        task = _folder(mailbox, "Tasks").messages[0]
        assert _named(
            task,
            PSETID_TASK,
            LID_TASK_F_RECURRING,
        ).value is True
        assert _named(
            task,
            PSETID_TASK,
            LID_TASK_RECURRENCE,
        ).value == build_recurrence_pattern(
            task_rule,
            start=start,
            task=True,
        )

        sent_model = _folder(mailbox, "Sent Items")
        request_model = _message(
            sent_model,
            "Workflow meeting",
        )
        cancel_model = _message(
            sent_model,
            "Workflow meeting canceled",
        )

        for item in (request_model, cancel_model):
            assert _named(
                item,
                PSETID_MEETING,
                LID_GLOBAL_OBJECT_ID,
            ).value == identity.global_object_id
            assert _named(
                item,
                PSETID_MEETING,
                LID_CLEAN_GLOBAL_OBJECT_ID,
            ).value == identity.clean_global_object_id

        assert _named(
            request_model,
            PSETID_MEETING,
            LID_MEETING_TYPE,
        ).value == MEETING_TYPE_REQUEST
        assert _named(
            cancel_model,
            PSETID_MEETING,
            LID_MEETING_TYPE,
        ).value == MEETING_TYPE_FULL

        inbox_model = _folder(mailbox, "Inbox")
        statuses = {
            item.message_class: _named(
                item,
                PSETID_APPOINTMENT,
                LID_RESPONSE_STATUS,
            ).value
            for item in inbox_model.messages
        }
        assert statuses[IPM_MEETING_RESPONSE_ACCEPT] == (
            RESPONSE_STATUS_ACCEPTED
        )
        assert statuses[IPM_MEETING_RESPONSE_TENTATIVE] == (
            RESPONSE_STATUS_TENTATIVE
        )
        assert statuses[IPM_MEETING_RESPONSE_DECLINE] == (
            RESPONSE_STATUS_DECLINED
        )

        rebuilt, write_report = mailbox_to_messaging(mailbox)
        assert write_report.messages_written == 7
        destination.write_bytes(rebuilt.build().data)

        mailbox2, report2 = load_mailbox(destination)
        assert report2.messages_failed == 0

        appointment2 = _folder(mailbox2, "Calendar").messages[0]
        assert _named(
            appointment2,
            PSETID_APPOINTMENT,
            LID_APPOINTMENT_RECUR,
        ).value == recurrence.value

        request2 = _message(
            _folder(mailbox2, "Sent Items"),
            "Workflow meeting",
        )
        assert _named(
            request2,
            PSETID_MEETING,
            LID_GLOBAL_OBJECT_ID,
        ).value == identity.global_object_id
