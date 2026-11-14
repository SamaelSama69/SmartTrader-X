"""Brokerage cards: a round trip has to be priced before a ticket looks cheap."""

import pytest

from recommender.costs import compare, minimum_ticket, quote


def test_zerodha_delivery_on_a_lakh_is_mostly_stt():
    trip = quote("zerodha", 100_000, 105_000, product="delivery")
    assert 200 < trip.total < 280
    brokerage = sum(line.amount for line in trip.lines if line.label == "Brokerage")
    assert brokerage == 0
    stt = sum(line.amount for line in trip.lines if line.label == "STT")
    assert stt == pytest.approx(205.0)


def test_groww_and_upstox_cost_more_than_zerodha_on_delivery():
    zerodha = quote("zerodha", 100_000, 105_000)
    groww = quote("groww", 100_000, 105_000)
    upstox = quote("upstox", 100_000, 105_000)
    assert groww.total > zerodha.total
    assert upstox.total > zerodha.total


def test_angel_one_caps_delivery_brokerage_at_twenty_rupees():
    large = quote("angel_one", 1_000_000)
    brokerage = sum(line.amount for line in large.lines if line.label == "Brokerage")
    assert brokerage == pytest.approx(40.0)
    small = quote("angel_one", 2_000)
    small_brok = sum(line.amount for line in small.lines if line.label == "Brokerage")
    assert small_brok == pytest.approx(10.0)


def test_upstox_delivery_is_a_flat_twenty_even_on_a_small_ticket():
    trip = quote("upstox", 1_000)
    brokerage = sum(line.amount for line in trip.lines if line.label == "Brokerage")
    assert brokerage == pytest.approx(40.0)


def test_intraday_does_not_charge_dp():
    trip = quote("zerodha", 50_000, product="intraday")
    assert all(line.label != "DP charge" for line in trip.lines)
    assert trip.side_total("sell") > 0


def test_half_a_percent_has_a_ticket_and_a_tenth_of_a_percent_does_not():
    ticket = minimum_ticket("zerodha", "delivery", 0.005)
    assert ticket is not None
    assert quote("zerodha", ticket).cost_share <= 0.005
    assert quote("zerodha", max(100.0, ticket * 0.5)).cost_share > 0.005
    assert minimum_ticket("zerodha", "delivery", 0.001) is None


def test_every_desk_is_on_the_comparison():
    trips = compare(25_000, product="delivery")
    assert {trip.platform for trip in trips} == {"zerodha", "groww", "upstox", "angel_one", "shoonya"}


def test_unknown_platform_is_rejected():
    with pytest.raises(ValueError):
        quote("no-such-desk", 10_000)
