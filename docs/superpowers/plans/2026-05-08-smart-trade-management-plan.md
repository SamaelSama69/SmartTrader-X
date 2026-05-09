# Implementation Plan: Smart Trade Management & Order Ticket

**Reference:** `docs/superpowers/specs/2026-05-08-smart-trade-management-design.md`

## Phase 1: Database & Core Logic Updates
- [ ] **Step 1.1: Update `PaperTradeManager` SQLite Schema**
  - File: `utils/paper_trade_manager.py`
  - Action: Update `CREATE_SQL` to include `trade_mode TEXT DEFAULT 'SWING'` and `is_manual BOOLEAN DEFAULT 0`.
  - Action: Add migration `ALTER TABLE` statements to apply these columns to existing databases.
  - Action: Update `open_trade` to accept and insert `trade_mode` and `is_manual`.
  - Verification: Run `python -c "from utils.paper_trade_manager import PaperTradeManager; mgr = PaperTradeManager(); print('DB Initialized')"` to ensure no SQL errors occur.

- [ ] **Step 1.2: Update ShoonyaBroker Live Integration**
  - File: `utils/shoonya_broker.py`
  - Action: Modify `place_order` signature to accept `trade_mode` and map `INTRADAY` -> `I` and `SWING` -> `C`. 

- [ ] **Step 1.3: Update RiskManager "Minimum Entry" Logic**
  - File: `utils/risk_manager.py`
  - Action: In `size_position_kelly` and `size_position_dynamic`, add logic: if calculated `shares < 1` but `confidence >= 0.65`, force `shares = 1`. 

## Phase 2: Bot Intelligence - The 3:00 PM Pre-Close Evaluation
- [ ] **Step 2.1: Refactor `manage_open_positions` in `auto_bot.py`**
  - File: `auto_bot.py`
  - Action: Remove the hardcoded 3:15 PM blind square-off.
  - Action: Introduce a 3:00 PM evaluation block. It skips trades where `is_manual == True`.
  - Action: If a trade is `INTRADAY` and P&L > 3% or momentum is extremely high, print log and change `trade_mode` to `SWING` (via a new DB update method).
  - Action: If a trade is `SWING` and failing or market regime is bearish, change `trade_mode` to `INTRADAY`.
  - Action: At 3:15 PM, force-close ONLY trades marked as `trade_mode='INTRADAY'`.

- [ ] **Step 2.2: Add Update Method to DB**
  - File: `utils/paper_trade_manager.py`
  - Action: Add `update_trade_mode(self, trade_id, new_mode)` method.

## Phase 3: The Manual Order Ticket UI
- [ ] **Step 3.1: Build UI Component**
  - File: `dashboard_v2.py`
  - Action: Inside `render_portfolio_hub` or a new tab, add an `st.expander` or dedicated section titled "📝 Manual Order Ticket".
  - Action: Include input fields: `st.text_input` (Ticker), `st.selectbox` (Buy/Sell), `st.radio` (Intraday/Swing), `st.number_input` (Quantity).
  - Action: Add a "Calculated Investment Amount" display that auto-updates based on current price * quantity.
  - Action: Add an `st.button` ("Execute Trade") that calls `paper_mgr.open_trade` with `is_manual=True` and the selected `trade_mode`.

- [ ] **Step 3.2: Display Modes in Active Positions Table**
  - File: `dashboard_v2.py`
  - Action: Update the "Active Positions" dataframe in `render_portfolio_hub` to fetch and display the `trade_mode` and `is_manual` columns.

## Phase 4: Final Verification
- [ ] **Step 4.1: Run Full Test Suite**
  - Run `pytest` to ensure core systems haven't broken.
- [ ] **Step 4.2: UI and Flow Testing**
  - Manually start the dashboard, place a manual INTRADAY order using the Ticket, and verify it appears in the Portfolio with the correct tags.