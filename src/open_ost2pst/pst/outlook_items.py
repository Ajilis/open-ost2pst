"""High-level Outlook item helpers built on Messaging + Name-to-ID."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Literal
from uuid import UUID, uuid4
import zlib

from .ltp.pc import PropertyType
from .recurrence import (
    RecurrenceRule,
    build_appointment_recurrence,
    build_recurrence_pattern,
    recurrence_clip_end,
    recurrence_description,
    recurrence_type,
)


PSETID_APPOINTMENT = UUID("00062002-0000-0000-c000-000000000046")
PSETID_TASK = UUID("00062003-0000-0000-c000-000000000046")
PSETID_ADDRESS = UUID("00062004-0000-0000-c000-000000000046")
PSETID_COMMON = UUID("00062008-0000-0000-c000-000000000046")
PSETID_MEETING = UUID("6ed8da90-450b-101b-98da-00aa003f1305")

IPF_APPOINTMENT = "IPF.Appointment"
IPF_CONTACT = "IPF.Contact"
IPF_TASK = "IPF.Task"

IPM_APPOINTMENT = "IPM.Appointment"
IPM_CONTACT = "IPM.Contact"
IPM_TASK = "IPM.Task"
IPM_MEETING_REQUEST = "IPM.Schedule.Meeting.Request"
IPM_MEETING_RESPONSE_ACCEPT = "IPM.Schedule.Meeting.Resp.Pos"
IPM_MEETING_RESPONSE_TENTATIVE = "IPM.Schedule.Meeting.Resp.Tent"
IPM_MEETING_RESPONSE_DECLINE = "IPM.Schedule.Meeting.Resp.Neg"
IPM_MEETING_CANCELED = "IPM.Schedule.Meeting.Canceled"

# Appointment / meeting named properties.
LID_APPOINTMENT_SEQUENCE = 0x8201
LID_BUSY_STATUS = 0x8205
LID_LOCATION = 0x8208
LID_APPOINTMENT_START_WHOLE = 0x820D
LID_APPOINTMENT_END_WHOLE = 0x820E
LID_APPOINTMENT_DURATION = 0x8213
LID_APPOINTMENT_SUBTYPE = 0x8215
LID_APPOINTMENT_RECUR = 0x8216
LID_APPOINTMENT_STATE_FLAGS = 0x8217
LID_RESPONSE_STATUS = 0x8218
LID_RECURRING = 0x8223
LID_INTENDED_BUSY_STATUS = 0x8224
LID_F_INVITED = 0x8229
LID_RECURRENCE_TYPE = 0x8231
LID_RECURRENCE_PATTERN = 0x8232
LID_CLIP_START = 0x8235
LID_CLIP_END = 0x8236
LID_ORGANIZER_ALIAS = 0x8243

# PSETID_Meeting named properties.
LID_GLOBAL_OBJECT_ID = 0x0003
LID_IS_RECURRING = 0x0005
LID_CLEAN_GLOBAL_OBJECT_ID = 0x0023
LID_APPOINTMENT_MESSAGE_CLASS = 0x0024
LID_MEETING_TYPE = 0x0026

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
LID_TASK_RECURRENCE = 0x8116
LID_TASK_COMPLETE = 0x811C
LID_TASK_OWNER = 0x811F
LID_TASK_F_RECURRING = 0x8126

# Standard meeting/contact properties.
PR_SUBJECT_PREFIX = 0x003D
PR_START_DATE = 0x0060
PR_END_DATE = 0x0061
PR_OWNER_APPOINTMENT_ID = 0x0062
PR_RESPONSE_REQUESTED = 0x0063
PR_DISPLAY_NAME = 0x3001
PR_GIVEN_NAME = 0x3A06
PR_BUSINESS_TELEPHONE_NUMBER = 0x3A08
PR_SURNAME = 0x3A11
PR_COMPANY_NAME = 0x3A16
PR_MOBILE_TELEPHONE_NUMBER = 0x3A1C

APPOINTMENT_STATE_MEETING = 0x00000001
APPOINTMENT_STATE_RECEIVED = 0x00000002

MEETING_TYPE_REQUEST = 0x00000001
MEETING_TYPE_FULL = 0x00010000
MEETING_TYPE_INFO = 0x00020000

RESPONSE_STATUS_NONE = 0
RESPONSE_STATUS_ORGANIZED = 1
RESPONSE_STATUS_TENTATIVE = 2
RESPONSE_STATUS_ACCEPTED = 3
RESPONSE_STATUS_DECLINED = 4
RESPONSE_STATUS_NOT_RESPONDED = 5

GLOBAL_OBJECT_ID_PREFIX = bytes.fromhex(
    "040000008200E00074C5B7101A82E008"
)

TASK_STATUS_NOT_STARTED = 0
TASK_STATUS_IN_PROGRESS = 1
TASK_STATUS_COMPLETE = 2
TASK_STATUS_WAITING = 3
TASK_STATUS_DEFERRED = 4


@dataclass(frozen=True, slots=True)
class MeetingIdentity:
    global_object_id: bytes
    clean_global_object_id: bytes
    owner_appointment_id: int


def create_meeting_identity(
    *,
    creation_time: datetime | None = None,
    data: bytes | None = None,
    owner_appointment_id: int | None = None,
) -> MeetingIdentity:
    creation = creation_time or datetime.now(timezone.utc)
    unique_data = bytes(data) if data is not None else uuid4().bytes
    if not unique_data:
        raise ValueError("GlobalObjectId data must not be empty")

    goid = b"".join(
        (
            GLOBAL_OBJECT_ID_PREFIX,
            b"\x00\x00\x00\x00",
            datetime_to_filetime(creation).to_bytes(8, "little"),
            b"\x00" * 8,
            len(unique_data).to_bytes(4, "little"),
            unique_data,
        )
    )
    owner_id = (
        owner_appointment_id
        if owner_appointment_id is not None
        else zlib.crc32(unique_data) & 0x7FFFFFFF
    )
    if not 0 <= owner_id <= 0x7FFFFFFF:
        raise ValueError("owner_appointment_id must fit in signed 31 bits")

    return MeetingIdentity(
        global_object_id=goid,
        clean_global_object_id=goid,
        owner_appointment_id=owner_id,
    )


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
    recurrence: RecurrenceRule | None = None,
    deleted_occurrences: tuple[date | datetime, ...] = (),
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

    if recurrence is not None:
        _apply_appointment_recurrence(
            builder,
            message,
            recurrence,
            start=start,
            end=end,
            deleted_occurrences=deleted_occurrences,
        )

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
    recurrence: RecurrenceRule | None = None,
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

    if recurrence is not None:
        if start is None:
            raise ValueError("recurring tasks require a start date")
        _named(
            builder,
            message,
            LID_TASK_RECURRENCE,
            build_recurrence_pattern(
                recurrence,
                start=start,
                task=True,
            ),
            PropertyType.BINARY,
            PSETID_TASK,
        )
        _named(
            builder,
            message,
            LID_TASK_F_RECURRING,
            True,
            PropertyType.BOOLEAN,
            PSETID_TASK,
        )

    return message



def add_meeting_request(
    builder: Any,
    folder: Any,
    *,
    identity: MeetingIdentity,
    subject: str,
    start: datetime,
    end: datetime,
    location: str = "",
    body: str = "",
    organizer_name: str = "",
    organizer_email: str = "",
    attendees: tuple[tuple[str, str], ...] = (),
    sequence: int = 0,
    meeting_type: int = MEETING_TYPE_REQUEST,
    busy_status: int = 2,
    recurrence: RecurrenceRule | None = None,
) -> Any:
    message = builder.add_message(
        folder,
        subject=subject,
        body=body,
        sender_name=organizer_name,
        sender_email=organizer_email,
        message_class=IPM_MEETING_REQUEST,
    )
    _apply_meeting_transport(
        builder,
        message,
        identity=identity,
        start=start,
        end=end,
        location=location,
        sequence=sequence,
        response_status=RESPONSE_STATUS_NOT_RESPONDED,
        meeting_type=meeting_type,
        busy_status=1,
        intended_busy_status=busy_status,
        response_requested=True,
        recurrence=recurrence,
    )
    for name, email in attendees:
        builder.add_recipient(
            message,
            name=name,
            email=email,
            recipient_type=1,
        )
    return message


def add_meeting_response(
    builder: Any,
    folder: Any,
    *,
    identity: MeetingIdentity,
    response: Literal["accept", "tentative", "decline"],
    subject: str,
    start: datetime,
    end: datetime,
    organizer_name: str = "",
    organizer_email: str = "",
    attendee_name: str = "",
    attendee_email: str = "",
    location: str = "",
    body: str = "",
    sequence: int = 0,
    recurrence: RecurrenceRule | None = None,
) -> Any:
    classes = {
        "accept": (
            IPM_MEETING_RESPONSE_ACCEPT,
            RESPONSE_STATUS_ACCEPTED,
            "Accepted:",
        ),
        "tentative": (
            IPM_MEETING_RESPONSE_TENTATIVE,
            RESPONSE_STATUS_TENTATIVE,
            "Tentative:",
        ),
        "decline": (
            IPM_MEETING_RESPONSE_DECLINE,
            RESPONSE_STATUS_DECLINED,
            "Declined:",
        ),
    }
    try:
        message_class, status, prefix = classes[response]
    except KeyError as exc:
        raise ValueError(
            "response must be accept, tentative, or decline"
        ) from exc

    message = builder.add_message(
        folder,
        subject=subject,
        body=body,
        sender_name=attendee_name,
        sender_email=attendee_email,
        message_class=message_class,
    )
    builder.set_property(
        message,
        PR_SUBJECT_PREFIX,
        prefix,
        property_type=PropertyType.UNICODE,
    )
    _apply_meeting_transport(
        builder,
        message,
        identity=identity,
        start=start,
        end=end,
        location=location,
        sequence=sequence,
        response_status=status,
        meeting_type=0,
        busy_status=2,
        intended_busy_status=2,
        response_requested=False,
        recurrence=recurrence,
    )
    if organizer_email:
        builder.add_recipient(
            message,
            name=organizer_name,
            email=organizer_email,
            recipient_type=1,
        )
    return message


def add_meeting_cancellation(
    builder: Any,
    folder: Any,
    *,
    identity: MeetingIdentity,
    subject: str,
    start: datetime,
    end: datetime,
    location: str = "",
    body: str = "",
    organizer_name: str = "",
    organizer_email: str = "",
    attendees: tuple[tuple[str, str], ...] = (),
    sequence: int = 1,
    recurrence: RecurrenceRule | None = None,
) -> Any:
    message = builder.add_message(
        folder,
        subject=subject,
        body=body,
        sender_name=organizer_name,
        sender_email=organizer_email,
        message_class=IPM_MEETING_CANCELED,
    )
    builder.set_property(
        message,
        PR_SUBJECT_PREFIX,
        "Canceled:",
        property_type=PropertyType.UNICODE,
    )
    _apply_meeting_transport(
        builder,
        message,
        identity=identity,
        start=start,
        end=end,
        location=location,
        sequence=sequence,
        response_status=RESPONSE_STATUS_NONE,
        meeting_type=MEETING_TYPE_FULL,
        busy_status=0,
        intended_busy_status=0,
        response_requested=False,
        recurrence=recurrence,
    )
    for name, email in attendees:
        builder.add_recipient(
            message,
            name=name,
            email=email,
            recipient_type=1,
        )
    return message


def _apply_appointment_recurrence(
    builder: Any,
    message: Any,
    rule: RecurrenceRule,
    *,
    start: datetime,
    end: datetime,
    deleted_occurrences: tuple[date | datetime, ...] = (),
) -> None:
    _named(
        builder,
        message,
        LID_APPOINTMENT_RECUR,
        build_appointment_recurrence(
            rule,
            start=start,
            end=end,
            deleted_dates=deleted_occurrences,
        ),
        PropertyType.BINARY,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_RECURRING,
        True,
        PropertyType.BOOLEAN,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_RECURRENCE_TYPE,
        recurrence_type(rule),
        PropertyType.INTEGER32,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_RECURRENCE_PATTERN,
        recurrence_description(rule),
        PropertyType.UNICODE,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_IS_RECURRING,
        True,
        PropertyType.BOOLEAN,
        PSETID_MEETING,
    )
    clip_start = datetime.combine(
        start.date(),
        time.min,
        tzinfo=timezone.utc,
    )
    _named(
        builder,
        message,
        LID_CLIP_START,
        clip_start,
        PropertyType.SYSTIME,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_CLIP_END,
        recurrence_clip_end(rule, start=start),
        PropertyType.SYSTIME,
        PSETID_APPOINTMENT,
    )


def _apply_meeting_transport(
    builder: Any,
    message: Any,
    *,
    identity: MeetingIdentity,
    start: datetime,
    end: datetime,
    location: str,
    sequence: int,
    response_status: int,
    meeting_type: int,
    busy_status: int,
    intended_busy_status: int,
    response_requested: bool,
    recurrence: RecurrenceRule | None,
) -> None:
    if end < start:
        raise ValueError("meeting end must not precede start")

    builder.set_property(
        message,
        PR_START_DATE,
        datetime_to_filetime(start),
        property_type=PropertyType.SYSTIME,
    )
    builder.set_property(
        message,
        PR_END_DATE,
        datetime_to_filetime(end),
        property_type=PropertyType.SYSTIME,
    )
    builder.set_property(
        message,
        PR_OWNER_APPOINTMENT_ID,
        identity.owner_appointment_id,
        property_type=PropertyType.INTEGER32,
    )
    builder.set_property(
        message,
        PR_RESPONSE_REQUESTED,
        response_requested,
        property_type=PropertyType.BOOLEAN,
    )

    _named(
        builder,
        message,
        LID_GLOBAL_OBJECT_ID,
        identity.global_object_id,
        PropertyType.BINARY,
        PSETID_MEETING,
    )
    _named(
        builder,
        message,
        LID_CLEAN_GLOBAL_OBJECT_ID,
        identity.clean_global_object_id,
        PropertyType.BINARY,
        PSETID_MEETING,
    )
    _named(
        builder,
        message,
        LID_APPOINTMENT_MESSAGE_CLASS,
        IPM_APPOINTMENT,
        PropertyType.UNICODE,
        PSETID_MEETING,
    )
    _named(
        builder,
        message,
        LID_MEETING_TYPE,
        meeting_type,
        PropertyType.INTEGER32,
        PSETID_MEETING,
    )
    _named(
        builder,
        message,
        LID_APPOINTMENT_SEQUENCE,
        sequence,
        PropertyType.INTEGER32,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_APPOINTMENT_START_WHOLE,
        start,
        PropertyType.SYSTIME,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_APPOINTMENT_END_WHOLE,
        end,
        PropertyType.SYSTIME,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_COMMON_START,
        start,
        PropertyType.SYSTIME,
        PSETID_COMMON,
    )
    _named(
        builder,
        message,
        LID_COMMON_END,
        end,
        PropertyType.SYSTIME,
        PSETID_COMMON,
    )
    _named(
        builder,
        message,
        LID_LOCATION,
        location,
        PropertyType.UNICODE,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_BUSY_STATUS,
        busy_status,
        PropertyType.INTEGER32,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_INTENDED_BUSY_STATUS,
        intended_busy_status,
        PropertyType.INTEGER32,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_APPOINTMENT_STATE_FLAGS,
        APPOINTMENT_STATE_MEETING | APPOINTMENT_STATE_RECEIVED,
        PropertyType.INTEGER32,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_RESPONSE_STATUS,
        response_status,
        PropertyType.INTEGER32,
        PSETID_APPOINTMENT,
    )
    _named(
        builder,
        message,
        LID_F_INVITED,
        True,
        PropertyType.BOOLEAN,
        PSETID_APPOINTMENT,
    )

    if recurrence is not None:
        _apply_appointment_recurrence(
            builder,
            message,
            recurrence,
            start=start,
            end=end,
        )


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
