"""The hotel: room types, rates and an in-memory reservation store. Plain Python, no model.

Step 01 of the workshop calls these functions directly. If they're wrong, no amount of voice polish will save the
call, so test them first.

The Clarium Bay Hotel is made up. Availability follows a fixed weekly pattern so the demo behaves the same on any
date: the family suites are taken every Friday and Saturday night, and one deluxe king is taken every Saturday.
"""

import secrets
from dataclasses import dataclass, field
from datetime import date, timedelta

MAX_NIGHTS = 14


@dataclass(frozen=True)
class RoomType:
    id: str
    name: str
    max_guests: int
    nightly_rate: int  # USD
    rooms: int


ROOM_TYPES = {
    "standard_queen": RoomType("standard_queen", "Standard Queen", 2, 149, 4),
    "deluxe_king": RoomType("deluxe_king", "Deluxe King", 2, 199, 3),
    "family_suite": RoomType("family_suite", "Family Suite", 4, 289, 2),
}

FRIDAY, SATURDAY = 4, 5


def _taken_by_pattern(room_type: str, night: date) -> int:
    if room_type == "family_suite" and night.weekday() in (FRIDAY, SATURDAY):
        return ROOM_TYPES["family_suite"].rooms
    if room_type == "deluxe_king" and night.weekday() == SATURDAY:
        return 1
    return 0


@dataclass
class Reservation:
    code: str
    guest_name: str
    phone: str
    room_type: str
    check_in: date
    check_out: date
    guests: int

    @property
    def nights(self) -> int:
        return (self.check_out - self.check_in).days

    @property
    def total(self) -> int:
        return self.nights * ROOM_TYPES[self.room_type].nightly_rate


class BookingError(ValueError):
    """A request the hotel can't accept. The message is safe to read out to the caller."""


@dataclass
class Hotel:
    reservations: dict[str, Reservation] = field(default_factory=dict)
    today: date = field(default_factory=date.today)

    def _check_dates(self, check_in: date, check_out: date) -> None:
        if check_in < self.today:
            raise BookingError("That check-in date is in the past.")
        if check_out <= check_in:
            raise BookingError("Check-out has to be at least one night after check-in.")
        if (check_out - check_in).days > MAX_NIGHTS:
            raise BookingError(f"We can book at most {MAX_NIGHTS} nights at a time.")

    def free_rooms(self, room_type: str, check_in: date, check_out: date) -> int:
        """Rooms of this type free on every night of the stay."""
        rt = ROOM_TYPES[room_type]
        free = rt.rooms
        night = check_in
        while night < check_out:
            booked = sum(
                1 for r in self.reservations.values() if r.room_type == room_type and r.check_in <= night < r.check_out
            )
            free = min(free, rt.rooms - _taken_by_pattern(room_type, night) - booked)
            night += timedelta(days=1)
        return max(free, 0)

    def availability(self, check_in: date, check_out: date, guests: int) -> list[dict]:
        """Room types that fit the party and are free for the whole stay, cheapest first."""
        self._check_dates(check_in, check_out)
        if guests < 1:
            raise BookingError("At least one guest is needed.")
        nights = (check_out - check_in).days
        options = []
        for rt in sorted(ROOM_TYPES.values(), key=lambda r: r.nightly_rate):
            if rt.max_guests >= guests and self.free_rooms(rt.id, check_in, check_out) > 0:
                options.append(
                    {"room_type": rt.id, "name": rt.name, "nightly_rate": rt.nightly_rate, "nights": nights, "total": rt.nightly_rate * nights}
                )
        return options

    def reserve(self, guest_name: str, phone: str, room_type: str, check_in: date, check_out: date, guests: int) -> Reservation:
        if room_type not in ROOM_TYPES:
            raise BookingError(f"We don't have a room type called {room_type}.")
        if not guest_name.strip():
            raise BookingError("I need a name for the reservation.")
        if sum(ch.isdigit() for ch in phone) < 7:
            raise BookingError("I need a phone number with at least seven digits.")
        if ROOM_TYPES[room_type].max_guests < guests:
            raise BookingError(f"A {ROOM_TYPES[room_type].name} sleeps at most {ROOM_TYPES[room_type].max_guests}.")
        self._check_dates(check_in, check_out)
        if self.free_rooms(room_type, check_in, check_out) == 0:
            raise BookingError(f"The {ROOM_TYPES[room_type].name} is no longer free for those dates.")
        # No 0/O or 1/I, so the code is easy to read out and to hear.
        code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(6))
        r = Reservation(code, guest_name.strip(), phone.strip(), room_type, check_in, check_out, guests)
        self.reservations[code] = r
        return r
