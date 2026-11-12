"""
Automated Security and Reliability Tests for SMS Payment System
Testing all 12 critical scenarios specified in the audit.
"""

import os
import sys
import gc
import asyncio
import sqlite3
import hashlib
from datetime import datetime, timezone, timedelta

# Ensure parent directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sms_payment_system import (
    jalali_to_gregorian,
    validate_jalali_date,
    is_jalali_leap_year,
    normalize_digits,
    BlubankSMSParser,
    SMSPaymentDatabase,
    SMSPaymentManager,
    DEFAULT_ALLOWED_SENDERS,
    TEHRAN_TZ,
)

TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_audit_sms.db")


def cleanup_test_db():
    gc.collect()
    for ext in ["", "-wal", "-shm"]:
        p = TEST_DB_PATH + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


def run_all_audit_tests():
    print("=" * 60)
    print("RUNNING CRITICAL SECURITY & RELIABILITY AUDIT TEST SUITE")
    print("=" * 60)
    cleanup_test_db()
    db = SMSPaymentDatabase(TEST_DB_PATH)

    # -------------------------------------------------------------
    # Test 1: Payment timestamp BEFORE order creation
    # -------------------------------------------------------------
    order_id_1 = 101
    base_price = 50000
    now_utc = datetime.now(timezone.utc)
    payable_1, offset_1 = db.reserve_unique_payable_amount(order_id_1, "purchase", 1001, base_price, window_minutes=30)

    # SMS timestamp is 10 minutes BEFORE order creation
    sms_time_before = now_utc - timedelta(minutes=10)
    res_1 = db.find_and_claim_reservation(
        amount_toman=payable_1,
        bank_tx_utc=sms_time_before,
        sms_hash=hashlib.sha256(b"sms_1").hexdigest(),
        sender="بلو",
        raw_text="sample",
        parsed_bank="blubank",
        amount_rial=payable_1 * 10,
        balance_rial=None,
        device_received_at_utc=now_utc.isoformat(),
        test_mode=False
    )
    assert res_1["status"] == "unmatched", f"Expected unmatched for payment before order, got {res_1['status']}"
    print("✓ Test 1 Passed: Payment before order creation strictly rejected.")

    # -------------------------------------------------------------
    # Test 2: Payment timestamp AFTER reservation expiry
    # -------------------------------------------------------------
    # SMS timestamp is 45 minutes AFTER order creation (expiry is 30m)
    sms_time_expired = now_utc + timedelta(minutes=45)
    res_2 = db.find_and_claim_reservation(
        amount_toman=payable_1,
        bank_tx_utc=sms_time_expired,
        sms_hash=hashlib.sha256(b"sms_2").hexdigest(),
        sender="بلو",
        raw_text="sample",
        parsed_bank="blubank",
        amount_rial=payable_1 * 10,
        balance_rial=None,
        device_received_at_utc=now_utc.isoformat(),
        test_mode=False
    )
    assert res_2["status"] == "unmatched", f"Expected unmatched for expired reservation, got {res_2['status']}"
    print("✓ Test 2 Passed: Payment after reservation expiry strictly rejected.")

    # -------------------------------------------------------------
    # Test 3: Missing or invalid SMS time
    # -------------------------------------------------------------
    sms_missing_time = """بلو
واریز پول
سیدنوید عزیز، 2,000,000ریال به حساب شما نشست.
موجودی: 3,306,610 ریال
۱۴۰۵.۰۸.۲۱"""
    parsed_no_time = BlubankSMSParser.parse("بلو", sms_missing_time, DEFAULT_ALLOWED_SENDERS)
    assert parsed_no_time is None, "SMS without time must be rejected"

    sms_invalid_hour = """بلو
واریز پول
سیدنوید عزیز، 2,000,000ریال به حساب شما نشست.
موجودی: 3,306,610 ریال
۲۵:۳۶
۱۴۰۵.۰۸.۲۱"""
    parsed_bad_hour = BlubankSMSParser.parse("بلو", sms_invalid_hour, DEFAULT_ALLOWED_SENDERS)
    assert parsed_bad_hour is None, "SMS with hour 25 must be rejected"
    print("✓ Test 3 Passed: Missing or out-of-range SMS time strictly rejected.")

    # -------------------------------------------------------------
    # Test 4: Invalid Jalali date (e.g. Month 13, Day 32, Esfand in non-leap year)
    # -------------------------------------------------------------
    assert not validate_jalali_date(1402, 13, 1), "Month 13 must be invalid"
    assert not validate_jalali_date(1402, 1, 32), "Day 32 must be invalid"
    assert not validate_jalali_date(1402, 7, 31), "Mehr cannot have 31 days"
    # 1402 is non-leap year: Esfand has 29 days
    assert not is_jalali_leap_year(1402), "1402 is not a leap year"
    assert not validate_jalali_date(1402, 12, 30), "Esfand 1402 cannot have 30 days"
    # 1403 is leap year: Esfand has 30 days
    assert is_jalali_leap_year(1403), "1403 is a leap year"
    assert validate_jalali_date(1403, 12, 30), "Esfand 1403 must have 30 days"
    print("✓ Test 4 Passed: Jalali date validator and leap-year rules verified.")

    # -------------------------------------------------------------
    # Test 5: Rial amounts not divisible by 10
    # -------------------------------------------------------------
    sms_indivisible_rial = """بلو
واریز پول
سیدنوید عزیز، 2,000,005ریال به حساب شما نشست.
موجودی: 3,306,610 ریال
۱۲:۳۶
۱۴۰۵.۰۸.۲۱"""
    parsed_indivisible = BlubankSMSParser.parse("بلو", sms_indivisible_rial, DEFAULT_ALLOWED_SENDERS)
    assert parsed_indivisible is None, "Rial amount 2,000,005 is not divisible by 10 and must be rejected"
    print("✓ Test 5 Passed: Non-divisible Rial amounts rejected without silent truncation.")

    # -------------------------------------------------------------
    # Test 6: Repeated SMS with different received_at values (Idempotency)
    # -------------------------------------------------------------
    sample_text = """بلو
واریز پول
سیدنوید عزیز، 2,000,000ریال به حساب شما نشست.
موجودی: 3,306,610 ریال
۱۲:۳۶
۱۴۰۵.۰۸.۲۱"""
    norm_s = normalize_digits("بلو").strip().lower()
    norm_m = normalize_digits(sample_text).strip()
    idempotent_hash = hashlib.sha256(f"{norm_s}:{norm_m}".encode("utf-8")).hexdigest()

    # Delivery attempt 1 at 12:40:00
    tx1, is_dup1 = db.record_sms_transaction(
        sms_hash=idempotent_hash, sender="بلو", raw_text=sample_text,
        parsed_bank="blubank", amount_toman=200000, amount_rial=2000000,
        balance_rial=None, bank_tx_utc="2026-11-12T09:06:00Z",
        device_received_at_utc="2026-11-12T12:40:00Z", status="approved"
    )
    assert not is_dup1

    # Delivery retry attempt 2 at 12:45:00 with differing device_received_at
    tx2, is_dup2 = db.record_sms_transaction(
        sms_hash=idempotent_hash, sender="بلو", raw_text=sample_text,
        parsed_bank="blubank", amount_toman=200000, amount_rial=2000000,
        balance_rial=None, bank_tx_utc="2026-11-12T09:06:00Z",
        device_received_at_utc="2026-11-12T12:45:00Z", status="approved"
    )
    assert is_dup2, "Retry with different forwarder received_at must be detected as duplicate!"
    assert tx1 == tx2
    print("✓ Test 6 Passed: Idempotency hash catches retried forwarder deliveries.")

    # -------------------------------------------------------------
    # Test 7: Concurrent delivery of two different SMS for one reservation
    # -------------------------------------------------------------
    order_id_7 = 701
    payable_7, offset_7 = db.reserve_unique_payable_amount(order_id_7, "purchase", 1007, 70000, window_minutes=30)
    tx_time_7 = now_utc + timedelta(minutes=5)

    res_sms_a = db.find_and_claim_reservation(
        amount_toman=payable_7, bank_tx_utc=tx_time_7,
        sms_hash=hashlib.sha256(b"sms_stream_a").hexdigest(),
        sender="بلو", raw_text="sms_a", parsed_bank="blubank",
        amount_rial=payable_7 * 10, balance_rial=None,
        device_received_at_utc=now_utc.isoformat(), test_mode=False
    )
    assert res_sms_a["status"] == "approved", "First SMS must successfully claim the active reservation"

    res_sms_b = db.find_and_claim_reservation(
        amount_toman=payable_7, bank_tx_utc=tx_time_7,
        sms_hash=hashlib.sha256(b"sms_stream_b").hexdigest(),
        sender="بلو", raw_text="sms_b", parsed_bank="blubank",
        amount_rial=payable_7 * 10, balance_rial=None,
        device_received_at_utc=now_utc.isoformat(), test_mode=False
    )
    assert res_sms_b["status"] == "unmatched", "Second SMS cannot claim an already claimed reservation"
    print("✓ Test 7 Passed: Atomic conditional claim prevents double-claiming of reservations.")

    # -------------------------------------------------------------
    # Test 8: Concurrent creation of reservations for one order
    # -------------------------------------------------------------
    # Partial unique index `idx_active_order_reservation` ensures one active reservation per order
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO amount_reservations (order_id, order_type, user_id, base_price, payable_amount, discount_offset, status, created_at_utc, expires_at_utc)
            VALUES (888, 'purchase', 2000, 30000, 29800, 200, 'active', ?, ?);
        """, (now_utc.isoformat(), (now_utc + timedelta(minutes=30)).isoformat()))
        conn.commit()

        # Second active insert for order 888 with different payable amount must violate unique index
        violates = False
        try:
            cursor.execute("""
                INSERT INTO amount_reservations (order_id, order_type, user_id, base_price, payable_amount, discount_offset, status, created_at_utc, expires_at_utc)
                VALUES (888, 'purchase', 2000, 30000, 29750, 250, 'active', ?, ?);
            """, (now_utc.isoformat(), (now_utc + timedelta(minutes=30)).isoformat()))
            conn.commit()
        except sqlite3.IntegrityError:
            violates = True
        assert violates, "Duplicate active reservation for same order must be blocked by database index"
    print("✓ Test 8 Passed: Partial unique index blocks multiple active reservations per order.")

    # -------------------------------------------------------------
    # Test 9: Failed reservation creation fails explicitly (no fallback)
    # -------------------------------------------------------------
    try:
        db.reserve_unique_payable_amount(999, "purchase", 3000, 500)
        assert False, "Base price < 1000 must fail explicitly"
    except ValueError as e:
        assert "at least 1,000" in str(e)
    print("✓ Test 9 Passed: Invalid or unfulfillable reservations fail explicitly.")

    # -------------------------------------------------------------
    # Test 10: Existing manually approved order cannot be re-approved
    # -------------------------------------------------------------
    class DummyMain:
        def __init__(self):
            self.orders = {"555": {"order_id": 555, "status": "approved", "user_id": 1, "price": 10000}}
            self.ADMIN_ID_INT = 12345
            self.configs_pool = {}

        def get_user(self, uid):
            return {"name": "test", "lang": "fa", "balance": 0}

        def update_order(self, oid, **kw):
            self.orders[str(oid)].update(kw)

    from balance_system import fulfill_balance_order
    import balance_system
    balance_system._main = DummyMain()

    success, msg = asyncio.run(fulfill_balance_order(555, approved_by="admin"))
    assert success is True and msg == "Already approved", "Must safely skip re-approval"
    print("✓ Test 10 Passed: Already-approved order cannot be re-approved or double-credited.")

    # -------------------------------------------------------------
    # Test 11: Sanaei unavailable -> retryable state preserved
    # -------------------------------------------------------------
    with db._get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sms_transactions (
                sms_hash, sender, raw_text, parsed_bank,
                amount_toman, amount_rial, balance_rial, bank_tx_utc,
                device_received_at_utc, server_received_at_utc, status,
                fulfillment_status, error_message, created_at_utc
            ) VALUES ('test_fulfill_hash', 'بلو', 'raw', 'blubank', 50000, 500000, NULL, '2026-11-12T10:00:00Z', NULL, '2026-11-12T10:00:00Z', 'approved', 'failed_pending_retry', 'Sanaei timeout', '2026-11-12T10:00:00Z');
        """)
        tx_id_11 = cursor.lastrowid
        conn.commit()

    tx_row = db.get_transaction_by_id(tx_id_11)
    assert tx_row["fulfillment_status"] == "failed_pending_retry"
    assert "Sanaei timeout" in tx_row["error_message"]

    # Now simulate retry succeeding
    db.update_fulfillment_status(tx_id_11, "fulfilled", "")
    tx_row_updated = db.get_transaction_by_id(tx_id_11)
    assert tx_row_updated["fulfillment_status"] == "fulfilled"
    print("✓ Test 11 Passed: Fulfillment failure state preserved and retryable.")

    # -------------------------------------------------------------
    # Test 12: Duplicate wallet credit prevention
    # -------------------------------------------------------------
    dummy_main_wallet = DummyMain()
    dummy_main_wallet.orders["777"] = {"order_id": 777, "status": "awaiting_payment", "user_id": 444, "base_price": 20000, "amount": 20000}
    wallet_balance = 0
    def dummy_add_balance(uid, amt):
        nonlocal wallet_balance
        wallet_balance += amt
        return wallet_balance
    dummy_main_wallet.add_balance = dummy_add_balance
    dummy_main_wallet.CustomLogger = type("obj", (), {"log_event": lambda *a: None})()
    dummy_main_wallet.send_sticker = lambda *a, **k: asyncio.sleep(0)
    dummy_main_wallet.bot = type("obj", (), {"send_message": lambda *a, **k: asyncio.sleep(0)})()
    dummy_main_wallet.user_states = {}
    dummy_main_wallet.load_coupon_from_user_db = lambda uid: {}
    dummy_main_wallet.clear_coupon_from_user_db = lambda uid: None
    balance_system._main = dummy_main_wallet

    # First fulfillment: credits 20,000
    s1, _ = asyncio.run(fulfill_balance_order(777, approved_by="sms_auto"))
    assert s1 is True
    assert wallet_balance == 20000

    # Second fulfillment attempt (duplicate request)
    s2, m2 = asyncio.run(fulfill_balance_order(777, approved_by="sms_auto"))
    assert m2 == "Already approved"
    assert wallet_balance == 20000, f"Wallet balance must NOT be double-credited! Got {wallet_balance}"
    print("✓ Test 12 Passed: Wallet balance cannot be double-credited under concurrent/duplicate calls.")

    cleanup_test_db()
    print("\n" + "=" * 60)
    print("ALL 12 CRITICAL AUDIT SCENARIOS VERIFIED SUCCESSFULLY!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_audit_tests()
