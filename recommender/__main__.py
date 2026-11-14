"""Build a recommendation book from the command line.

    python -m recommender --demo
    python -m recommender --capital 250000 --risk growth --horizon investment
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from recommender.data import demo_frames, fetch_closes, sector_map
from recommender.engine import recommend
from recommender.models import InvestorProfile


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an NSE trade and investment book.")
    parser.add_argument("--capital", type=float, default=500_000)
    parser.add_argument("--risk", choices=["conservative", "balanced", "growth"], default="balanced")
    parser.add_argument("--horizon", choices=["trading", "investment", "both"], default="both")
    parser.add_argument("--max-names", type=int, default=6)
    parser.add_argument("--demo", action="store_true", help="Use built-in prices instead of Yahoo Finance.")
    parser.add_argument("--out", default="output/indian/recommendations.json")
    args = parser.parse_args()

    profile = InvestorProfile(
        capital=args.capital,
        risk=args.risk,
        horizon=args.horizon,
        max_names=args.max_names,
    )
    if args.demo:
        frames = demo_frames()
    else:
        frames = fetch_closes()
        if not frames:
            raise SystemExit("No prices returned. Run with --demo to use the built-in book.")

    book = recommend(frames, profile, sectors=sector_map(list(frames)))
    payload = book.to_dict()
    destination = Path(args.out)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Regime: {book.regime}")
    print(f"Cash: INR {book.cash_amount:,.0f} ({book.cash_weight:.0%})")
    print()
    for item in book.recommendations:
        if item.action != "buy":
            print(f"AVOID  {item.ticker:<16} {item.reasons[0]}")
            continue
        print(
            f"BUY    {item.ticker:<16} {item.sleeve:<6} "
            f"INR {item.amount:>10,.0f}  {item.shares:>5} sh  "
            f"stop {item.stop}"
        )
    print()
    print(f"Wrote {destination}")


if __name__ == "__main__":
    main()
