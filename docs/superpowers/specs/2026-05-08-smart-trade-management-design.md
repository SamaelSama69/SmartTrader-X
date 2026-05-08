# Design Specification: Smart Trade Management & Order Ticket

**Date:** 2026-05-08
**Topic:** Portfolio Profile, Intraday/Swing categorization, Manual Overrides, and Capital Constraints

## 1. Overview
Currently, the SmartTrader autobot forces an End-of-Day (EOD) square-off at 3:15 PM for all positions, inadvertently closing out Swing strategies (like Indian Momentum) prematurely. 

This design implements a "Smart Trading Terminal" model. It introduces explicit categorization of trades (`INTRADAY` vs `SWING`), provides the user with a full Manual Order Ticket in the dashboard, and adds an intelligent 3:00 PM Pre-Close Evaluation where the bot dynamically adjusts trade modes based on performance.

## 2. Architecture & Data Model
The persistence layer (`memory/paper_trades.db`) must be updated to track trade intent and origin.

*   **New Columns:**
    *   `trade_mode` (TEXT): Explicitly set to either `'INTRADAY'` or `'SWING'`.
    *   `is_manual` (BOOLEAN): `True` if executed via the Manual Order Ticket, `False` if executed autonomously by the bot.
*   **Live Broker Integration (Shoonya):** 
    *   Map `INTRADAY` to Shoonya's `I` (MIS) product type.
    *   Map `SWING` to Shoonya's `C` (CNC/Delivery) product type.

## 3. UI Component: The Manual Order Ticket
Transform the dashboard from a purely analytical tool into an interactive trading terminal.

*   **Location:** Inside the "Portfolio Hub" or a new "Trading Desk" tab.
*   **Form Inputs:**
    *   **Ticker Symbol** (e.g., RELIANCE.NS)
    *   **Action:** BUY, SELL, SHORT
    *   **Mode:** INTRADAY, SWING
    *   **Quantity:** Integer input, OR a "Total Capital (₹)" calculator that auto-fills quantity.
*   **Execution:** Clicking the execute button will instantly write the trade to `paper_trades.db` with `is_manual=True`. The background bot loop will ignore the execution logic for this trade but will display it in the portfolio.

## 4. Bot Intelligence: The 3:00 PM Pre-Close Evaluation
Replace the hardcoded 3:15 PM blind square-off with an intelligent pre-close routine.

*   **Trigger Time:** 3:00 PM IST.
*   **Scope:** Evaluates all open positions where `is_manual = False`. (Manual trades strictly obey the mode chosen by the user).
*   **Dynamic Upgrades (Intraday -> Swing):**
    *   If an `INTRADAY` trade exhibits extreme strength (e.g., P&L > 3%, massive volume, or hitting the upper circuit), the bot automatically upgrades its `trade_mode` to `SWING` to capture overnight gap-up momentum.
*   **Dynamic Downgrades (Swing -> Intraday):**
    *   If a `SWING` trade is underperforming severely, or if the global `IndianMarketRegime` indicates a severe bearish/crash shift that day, the bot downgrades the `trade_mode` to `INTRADAY` and queues it for the 3:15 PM square-off to prevent overnight gap-down risk.

## 5. Capital-Aware Sizing & Minimum Entry
Position sizing must remain robust even for small accounts.

*   **Current Issue:** The Risk Manager (Kelly Criterion) might calculate an optimal position size of ₹5,000. If a stock costs ₹10,000, the calculated shares = 0, preventing the trade.
*   **Resolution (Minimum Entry):** If the calculated `shares` is < 1, but the `confidence` score is sufficiently high (above the strategy threshold), the bot will override the calculation and purchase exactly **1 share**. This ensures participation in high-conviction setups despite strict risk math, accepting slight over-leverage on small capital accounts.

## 6. Implementation Plan / Sequence
1.  **Database Migration:** Alter the SQLite schema in `PaperTradeManager`.
2.  **Risk Manager Update:** Implement the "Minimum Entry" (1 share) logic.
3.  **UI Development:** Build the Streamlit `Manual Order Ticket` component in `dashboard_v2.py`.
4.  **Bot Logic Update:** Rewrite `manage_open_positions` in `auto_bot.py` to use the new 3:00 PM Pre-Close Evaluation and respect `trade_mode`.