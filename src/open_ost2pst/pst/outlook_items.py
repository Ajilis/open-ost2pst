"""High-level Outlook item helpers built on Messaging + Name-to-ID."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .ltp.pc import PropertyType


PSETID_APPOINTMENT = UUID("00062002-0000-0000-c000-000000000046")
PSETID_TASK = UUID("00062003-0000-0000-c000-000000000046")
PSETID_ADDRESS = UUID("00062004-0000-0000-c000-000000000046")
PSETID_COMMON = UUID("00062008-0000-0000-c000-000000000046")

IPF_APPOINTMENT = "IPF.Appointment"
IPF_CONTACT = "IPF.Contact"
IPF_TASK = "IPF.Task"

IPM_APPOINTMENT = "IPM.Appointment"
IPM_CONTACT = "IPM.Contact"
IPM_TASK = "IPM.Task"

# Appointment / meeting named properties.
LID_BUSY_STATUS = 0x8205
LID_LOCATION = 0x8208
LID_APPOINTMENT_START_WHOLE = 0x820D
LID_APPOINTMENT_END_WHOLE = 0x820E
LID_APPOINTMENT_DURATION = 0x8213
LID_APPOINTMENT_SUBTYPE = 0x8215
LID_APPOINTMENT_STATE_FLAGS = 0x8217
LID_RESPONSE_STATUS = 0x8218
LID_F_INVITED = 0x8229
LID_ORGANIZER_ALIAS = 0x8243

# Common reminder/date named properties.
LID_REMINDER_DELTA = 0x8501
LID_REMINDER_TIME = 0x8502
LID_REMINDER_SET = 0x8503
LID_COMMON_START = 0x8516
LID_COMMON_END = 0x8517

# Contact named properties.
LID_FILE_UNDER = 0x8005
LID_EMAIL1_DISPLAY_NAME = 0x8080
LID_EMAIL1_ADDRESS_TYPE = 0x8082
LID_EMAIL1_EMAIL_ADDRESS = 0x8083
LID_EMAIL1_ORIGINAL_DISPLAY_NAME = 0x8084

# Task named properties.
LID_TASK_STATUS = 0x8101
LID_PERCENT_COMPLETE = 0x8102
LID_TASK_START_DATE = 0x8104
LID_TASK_DUE_DATE = 0x8105
LID_TASK_DATE_COMPLETED = 0x810F
LID_TASK_COMPLETE = 0x811C
LID_TASK_OWNER = 0x811F

# Standard contact properties.
PR_DISPLAY_NAME = 0x3001
PR_GIVEN_NAME = 0x3A06
PR_BUSINESS_TELEPHONE_NUMBER = 0x3A08
PR_SURNAME = 0x3A11
PR_COMPANY_NAME = 0x3A16
PR_MOBILE_TELEPHONE_NUMBER = 0x3A1C

APPOINTMENT_STATE_MEETING = 0x00000001

TASK_STATUS_NOT_STARTED = 0
TASK_STATUS_IN_PROGRESS = 1
TASK_STATUS_COMPLETE = 2
TASK_STATUS_WAITING = 3
TASK_STATUS_DEFERRED = 4


def datetime_to_filetime(value: datetime) -> int:
    if value.tzinfo is None:
        utc_value = value.replace(tzinfo=timezone.utc)
    else:
        utc_value = value.astimezone(timezone.utc)

    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    delta = utc_value - epoch
    if delta.total_seconds() < 0:
        raise ValueError("datetime predates Windows FILETIME epoch")
    return (
        delta.days * 86400 * 10_000_000
        + delta.seconds * 10_000_000
        + delta.microseconds * 10
    )


def add_appointment(
    builder: Any,
    folder: Any,
    *,
    subject: str,
    start: datetime,
    end: datetime,
    location: str = "",
    body: str = "",
    all_day: bool = False,
    busy_status: int = 2,
    meeting: bool = False,
    organizer_alias: str | None = None,
    response_status: int | None = None,
    reminder_minutes: int | None = None,
) -> Any:
    if end < start:
        raise ValueError("appointment end must not precede start")
    if busy_status not in (0, 1, 2, 3):
        raise ValueError("busy_status must be 0, 1, 2, or 3")
    if reminder_minutes is not None and reminder_minutes < 0:
        raise ValueError("reminder_minutes must be non-negative")

    duration_minutes = int((end - start).total_seconds() // 60)
    message = builder.add_message(
        folder,
        subject=subject,
        body=body,
        message_class=IPM_APPOINTMENT,
    )

    _named(builder, message, LID_APPOINTMENT_START_WHOLE, start, PropertyType.SYSTIME, PSETID_APPOINTMENT)
    _named(builder, message, LID_APPOINTMENT_END_WHOLE, end, PropertyType.SYSTIME, PSETID_APPOINTMENT)
    _named(builder, message, LID_LOCATION, location, PropertyType.UNICODE, PSETID_APPOINTMENT)
    _named(builder, message, LID_APPOINTMENT_DURATION, duration_minutes, PropertyType.INTEGER32, PSETID_APPOINTMENT)
    _named(builder, message, LID_APPOINTMENT_SUBTYPE, all_day, PropertyType.BOOLEAN, PSETID_APPOINTMENT)
    _named(builder, message, LID_BUSY_STATUS, busy_status, PropertyType.INTEGER32, PSETID_APPOINTMENT)
    _named(
        builder,
        message,
        LID_APPOINTMENT_STATE_FLAGS,
        APPOINTMENT_STATE_MEETING if meeting else 0,
        PropertyType.INTEGER32,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_RESPONSE_STATUS,
        (1 if meeting else 0) if response_status is None else response_status,
        PropertyType.INTEGER32,
        PSETID_APPOINTMENT,
    )
    _named(builder, message, LID_F_INVITED, meeting, PropertyType.BOOLEAN, PSETID_APPOINTMENT)
    _named(builder, message, LID_COMMON_START, start, PropertyType.SYSTIME, PSETID_COMMON)
    _named(builder, message, LID_COMMON_END, end, PropertyType.SYSTIME, PSETID_COMMON)

    if organizer_alias:
        _named(builder, message, LID_ORGANIZER_ALIAS, organizer_alias, PropertyType.UNICODE, PSETID_APPOINTMENT)

    if reminder_minutes is not None:
        _named(builder, message, LID_REMINDER_SET, True, PropertyType.BOOLEAN, PSETID_COMMON)
        _named(builder, message, LID_REMINDER_DELTA, reminder_minutes, PropertyType.INTEGER32, PSETID_COMMON)
        _named(builder, message, LID_REMINDER_TIME, start, PropertyType.SYSTIME, PSETID_COMMON)

    return message


def add_meeting(builder: Any, folder: Any, **kwargs: Any) -> Any:
    kwargs["meeting"] = True
    return add_appointment(builder, folder, **kwargs)


def add_contact(
    builder: Any,
    folder: Any,
    *,
    display_name: str,
    given_name: str = "",
    surname: str = "",
    company_name: str = "",
    email: str = "",
    business_phone: str = "",
    mobile_phone: str = "",
    body: str = "",
    file_under: str | None = None,
) -> Any:
    message = builder.add_message(
        folder,
        subject=display_name,
        body=body,
        message_class=IPM_CONTACT,
    )

    builder.set_property(
        message,
        PR_DISPLAY_NAME,
        display_name,
        property_type=PropertyType.UNICODE,
    )
    if given_name:
        builder.set_property(
            message,
            PR_GIVEN_NAME,
            given_name,
            property_type=PropertyType.UNICODE,
        )
    if surname:
        builder.set_property(
            message,
            PR_SURNAME,
            surname,
            property_type=PropertyType.UNICODE,
        )
    if company_name:
        builder.set_property(
            message,
            PR_COMPANY_NAME,
            company_name,
            property_type=PropertyType.UNICODE,
        )
    if business_phone:
        builder.set_property(
            message,
            PR_BUSINESS_TELEPHONE_NUMBER,
            business_phone,
            property_type=PropertyType.UNICODE,
        )
    if mobile_phone:
        builder.set_property(
            message,
            PR_MOBILE_TELEPHONE_NUMBER,
            mobile_phone,
            property_type=PropertyType.UNICODE,
        )

    _named(
        builder,
        message,
        LID_FILE_UNDER,
        file_under or display_name,
        PropertyType.UNICODE,
        PSETID_ADDRESS,
    )

    if email:
        _named(builder, message, LID_EMAIL1_DISPLAY_NAME, display_name, PropertyType.UNICODE, PSETID_ADDRESS)
        _named(builder, message, LID_EMAIL1_ADDRESS_TYPE, "SMTP", PropertyType.UNICODE, PSETID_ADDRESS)
        _named(builder, message, LID_EMAIL1_EMAIL_ADDRESS, email, PropertyType.UNICODE, PSETID_ADDRESS)
        _named(builder, message, LID_EMAIL1_ORIGINAL_DISPLAY_NAME, email, PropertyType.UNICODE, PSETID_ADDRESS)

    return message


def add_task(
    builder: Any,
    folder: Any,
    *,
    subject: str,
    body: str = "",
    status: int = TASK_STATUS_NOT_STARTED,
    percent_complete: float = 0.0,
    start: datetime | None = None,
    due: datetime | None = None,
    completed: datetime | None = None,
    owner: str | None = None,
    reminder_minutes: int | None = None,
) -> Any:
    if status not in {
        TASK_STATUS_NOT_STARTED,
        TASK_STATUS_IN_PROGRESS,
        TASK_STATUS_COMPLETE,
        TASK_STATUS_WAITING,
        TASK_STATUS_DEFERRED,
    }:
        raise ValueError("invalid task status")
    if not 0.0 <= percent_complete <= 1.0:
        raise ValueError("percent_complete must be between 0.0 and 1.0")
    if start is not None and due is not None and due < start:
        raise ValueError("task due date must not precede start date")
    if reminder_minutes is not None and reminder_minutes < 0:
        raise ValueError("reminder_minutes must be non-negative")

    is_complete = status == TASK_STATUS_COMPLETE or percent_complete >= 1.0
    if is_complete:
        status = TASK_STATUS_COMPLETE
        percent_complete = 1.0

    message = builder.add_message(
        folder,
        subject=subject,
        body=body,
        message_class=IPM_TASK,
    )

    _named(builder, message, LID_TASK_STATUS, status, PropertyType.INTEGER32, PSETID_TASK)
    _named(builder, message, LID_PERCENT_COMPLETE, percent_complete, PropertyType.FLOAT64, PSETID_TASK)
    _named(builder, message, LID_TASK_COMPLETE, is_complete, PropertyType.BOOLEAN, PSETID_TASK)

    if start is not None:
        _named(builder, message, LID_TASK_START_DATE, start, PropertyType.SYSTIME, PSETID_TASK)
        _named(builder, message, LID_COMMON_START, start, PropertyType.SYSTIME, PSETID_COMMON)
    if due is not None:
        _named(builder, message, LID_TASK_DUE_DATE, due, PropertyType.SYSTIME, PSETID_TASK)
        _named(builder, message, LID_COMMON_END, due, PropertyType.SYSTIME, PSETID_COMMON)
    if completed is not None:
        _named(builder, message, LID_TASK_DATE_COMPLETED, completed, PropertyType.SYSTIME, PSETID_TASK)
    if owner:
        _named(builder, message, LID_TASK_OWNER, owner, PropertyType.UNICODE, PSETID_TASK)

    if reminder_minutes is not None:
        reminder_anchor = due or start
        if reminder_anchor is not None:
            _named(builder, message, LID_REMINDER_SET, True, PropertyType.BOOLEAN, PSETID_COMMON)
            _named(builder, message, LID_REMINDER_DELTA, reminder_minutes, PropertyType.INTEGER32, PSETID_COMMON)
            _named(builder, message, LID_REMINDER_TIME, reminder_anchor, PropertyType.SYSTIME, PSETID_COMMON)

    return message


def _named(
    builder: Any,
    message: Any,
    lid: int,
    value: object,
    property_type: PropertyType,
    guid: UUID,
) -> int:
    if property_type == PropertyType.SYSTIME:
        if not isinstance(value, datetime):
            raise TypeError("SYSTIME named properties require datetime values")
        value = datetime_to_filetime(value)

    return builder.set_named_property(
        message,
        lid,
        value,
        property_type=property_type,
        guid=guid,
    )
