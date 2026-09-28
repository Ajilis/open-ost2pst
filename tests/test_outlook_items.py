from datetime import datetime, timezone

import pytest

from open_ost2pst.pst.messaging import MessagingBuilder
from open_ost2pst.pst.outlook_items import (
    APPOINTMENT_STATE_MEETING,
    IPF_APPOINTMENT,
    IPF_CONTACT,
    IPF_TASK,
    IPM_APPOINTMENT,
    IPM_CONTACT,
    IPM_TASK,
    LID_APPOINTMENT_STATE_FLAGS,
    LID_EMAIL1_EMAIL_ADDRESS,
    LID_PERCENT_COMPLETE,
    LID_TASK_COMPLETE,
    LID_TASK_STATUS,
    PSETID_ADDRESS,
    PSETID_APPOINTMENT,
    PSETID_TASK,
    TASK_STATUS_COMPLETE,
)


def _named_id(builder, guid, lid):
    return next(
        prop.property_id
        for prop in builder.nameid.properties
        if prop.guid == guid and prop.name == lid
    )


def test_high_level_outlook_item_builders() -> None:
    builder = MessagingBuilder()
    calendar = builder.add_calendar_folder(builder.root)
    contacts = builder.add_contacts_folder(builder.root)
    tasks = builder.add_tasks_folder(builder.root)

    start = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 1, 10, 30, tzinfo=timezone.utc)

    meeting = builder.add_meeting(
        calendar,
        subject="Architecture review",
        start=start,
        end=end,
        location="Room A",
        organizer_alias="organizer@example.com",
        reminder_minutes=15,
    )
    contact = builder.add_contact(
        contacts,
        display_name="Alice Example",
        given_name="Alice",
        surname="Example",
        email="alice@example.com",
        mobile_phone="+33123456789",
    )
    task = builder.add_task(
        tasks,
        subject="Ship release",
        status=TASK_STATUS_COMPLETE,
        percent_complete=0.4,
        start=start,
        due=end,
        completed=end,
        owner="Alice Example",
    )

    assert calendar.container_class == IPF_APPOINTMENT
    assert contacts.container_class == IPF_CONTACT
    assert tasks.container_class == IPF_TASK

    assert meeting.message_class == IPM_APPOINTMENT
    assert contact.message_class == IPM_CONTACT
    assert task.message_class == IPM_TASK

    meeting_state = _named_id(
        builder,
        PSETID_APPOINTMENT,
        LID_APPOINTMENT_STATE_FLAGS,
    )
    assert meeting.named_properties[meeting_state][1] == APPOINTMENT_STATE_MEETING

    email_prop = _named_id(
        builder,
        PSETID_ADDRESS,
        LID_EMAIL1_EMAIL_ADDRESS,
    )
    assert contact.named_properties[email_prop][1] == "alice@example.com"

    status_prop = _named_id(builder, PSETID_TASK, LID_TASK_STATUS)
    percent_prop = _named_id(builder, PSETID_TASK, LID_PERCENT_COMPLETE)
    complete_prop = _named_id(builder, PSETID_TASK, LID_TASK_COMPLETE)

    assert task.named_properties[status_prop][1] == TASK_STATUS_COMPLETE
    assert task.named_properties[percent_prop][1] == pytest.approx(1.0)
    assert task.named_properties[complete_prop][1] is True


def test_outlook_item_validation() -> None:
    builder = MessagingBuilder()
    calendar = builder.add_calendar_folder(builder.root)
    tasks = builder.add_tasks_folder(builder.root)
    start = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="end"):
        builder.add_appointment(
            calendar,
            subject="Bad appointment",
            start=start,
            end=datetime(2026, 10, 2, 11, 0, tzinfo=timezone.utc),
        )

    with pytest.raises(ValueError, match="percent_complete"):
        builder.add_task(
            tasks,
            subject="Bad task",
            percent_complete=1.2,
        )
