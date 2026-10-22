"""Step 01: the tools, without a model. These run anywhere, with no keys."""

from datetime import date, timedelta

import pytest

from hotel_agent import knowledge
from hotel_agent.hotel import BookingError, Hotel

MONDAY = date(2026, 11, 2)
TUESDAY, FRIDAY = MONDAY + timedelta(1), MONDAY + timedelta(4)


def test_cheapest_room_first_and_only_rooms_that_fit():
    options = Hotel(today=MONDAY).availability(TUESDAY, TUESDAY + timedelta(2), 2)
    assert [o["room_type"] for o in options] == ["standard_queen", "deluxe_king", "family_suite"]
    assert options[0]["total"] == 298
    assert [o["room_type"] for o in Hotel(today=MONDAY).availability(TUESDAY, TUESDAY + timedelta(1), 4)] == ["family_suite"]


def test_family_suites_are_taken_on_weekend_nights():
    assert Hotel(today=MONDAY).availability(FRIDAY, FRIDAY + timedelta(2), 4) == []


def test_a_booking_takes_a_room():
    hotel = Hotel(today=MONDAY)
    for _ in range(2):
        hotel.reserve("Ana Lima", "555 010 0199", "family_suite", TUESDAY, TUESDAY + timedelta(1), 3)
    assert hotel.free_rooms("family_suite", TUESDAY, TUESDAY + timedelta(1)) == 0
    with pytest.raises(BookingError, match="no longer free"):
        hotel.reserve("Ben Ito", "555 010 0142", "family_suite", TUESDAY, TUESDAY + timedelta(1), 3)


@pytest.mark.parametrize(
    "check_in, check_out, guests, message",
    [
        (MONDAY - timedelta(1), MONDAY + timedelta(1), 2, "in the past"),
        (TUESDAY, TUESDAY, 2, "at least one night"),
        (TUESDAY, TUESDAY + timedelta(15), 2, "at most 14 nights"),
        (TUESDAY, TUESDAY + timedelta(1), 0, "At least one guest"),
    ],
)
def test_bad_requests_get_a_reason_the_agent_can_read_out(check_in, check_out, guests, message):
    with pytest.raises(BookingError, match=message):
        Hotel(today=MONDAY).availability(check_in, check_out, guests)


@pytest.mark.parametrize("spoken, stored", [("555 010 0199", "5550100199"), ("+1 (555) 010-0199", "+15550100199"), ("5550100 199", "5550100199")])
def test_phone_numbers_are_stored_as_digits(spoken, stored):
    r = Hotel(today=MONDAY).reserve("Ana Lima", spoken, "standard_queen", TUESDAY, TUESDAY + timedelta(1), 1)
    assert r.phone == stored


def test_a_phone_number_too_short_is_asked_again():
    with pytest.raises(BookingError, match="say it again"):
        Hotel(today=MONDAY).reserve("Ana Lima", "555 01", "standard_queen", TUESDAY, TUESDAY + timedelta(1), 1)


def test_confirmation_codes_avoid_letters_that_sound_alike():
    code = Hotel(today=MONDAY).reserve("Ana Lima", "555 010 0199", "standard_queen", TUESDAY, TUESDAY + timedelta(1), 1).code
    assert len(code) == 6 and not set(code) & set("0O1I")


@pytest.mark.parametrize(
    "question, section",
    [
        ("What time is check-out?", "Check-in and check-out"),
        ("Can I cancel for free?", "Cancellation"),
        ("Can I bring my dog?", "Pets"),
        ("When is breakfast served on Sunday?", "Breakfast"),
    ],
)
def test_policy_lookup_finds_the_right_section(question, section):
    assert knowledge.search(question, knowledge.load(), k=1)[0].title == section


def test_policy_lookup_admits_what_the_file_does_not_cover():
    assert knowledge.search("Do you have parking?", knowledge.load()) == []
