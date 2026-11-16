import asyncio
import hashlib
import hmac
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from fastapi.testclient import TestClient

import main


class PaymentWebhookTests(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.data_dir.cleanup)
        self.original_values = {
            "PAYMENTS_DB": main.PAYMENTS_DB,
            "API_KEYS_DB": main.API_KEYS_DB,
            "OXAPAY_MERCHANT_KEY": main.OXAPAY_MERCHANT_KEY,
            "NOWPAYMENTS_API_KEY": main.NOWPAYMENTS_API_KEY,
            "NOWPAYMENTS_IPN_SECRET": main.NOWPAYMENTS_IPN_SECRET,
            "PAYMENTS_PUBLIC_BASE_URL": main.PAYMENTS_PUBLIC_BASE_URL,
        }
        self.addCleanup(self.restore_globals)
        main.PAYMENTS_DB = Path(self.data_dir.name) / "payments.db"
        main.API_KEYS_DB = Path(self.data_dir.name) / "api_keys.db"
        main.OXAPAY_MERCHANT_KEY = "test-oxapay-secret"
        main.NOWPAYMENTS_IPN_SECRET = "test-nowpayments-secret"
        main.PAYMENTS_PUBLIC_BASE_URL = "https://payments.example.test"
        main._init_payments_db()
        main._init_keys_db()
        self.client = TestClient(main.app)

    def restore_globals(self):
        for name, value in self.original_values.items():
            setattr(main, name, value)

    def create_order(self, gateway="oxapay", order_id="tp-pro-test-order", track_id="provider-track"):
        with sqlite3.connect(main.PAYMENTS_DB) as conn:
            conn.execute(
                "INSERT INTO payments "
                "(track_id, order_id, email, tier, amount, status, created_at, gateway) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                (
                    track_id,
                    order_id,
                    "buyer@example.test",
                    "pro",
                    9.99,
                    "2026-01-01T00:00:00+00:00",
                    gateway,
                ),
            )
        return order_id, track_id

    def signed_oxapay_request(self, payload, provider_confirmed=True):
        body = json.dumps(payload, separators=(",", ":")).encode()
        signature = hmac.new(
            main.OXAPAY_MERCHANT_KEY.encode(), body, hashlib.sha512
        ).hexdigest()
        with patch(
            "main._confirm_oxapay_paid_invoice",
            new=AsyncMock(return_value=provider_confirmed),
        ):
            return self.client.post(
                "/payments/webhook/oxapay",
                content=body,
                headers={"HMAC": signature, "Content-Type": "application/json"},
            )

    def test_oxapay_status_lookup_requires_paid_matching_usd_amount(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": 200,
            "data": {
                "track_id": "track-1",
                "order_id": "order-1",
                "status": "paid",
                "currency": "USD",
                "amount": 9.99,
            },
        }
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.get = AsyncMock(return_value=response)

        with patch("main.httpx.AsyncClient", return_value=client):
            confirmed = asyncio.run(
                main._confirm_oxapay_paid_invoice("track-1", "order-1", 9.99)
            )
            underpaid = asyncio.run(
                main._confirm_oxapay_paid_invoice("track-1", "order-1", 10.00)
            )

        self.assertTrue(confirmed)
        self.assertFalse(underpaid)

    def test_create_payment_requests_live_oxapay_invoice_and_persists_order(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "status": 200,
            "data": {
                "track_id": "oxapay-track-1",
                "payment_url": "https://pay.oxapay.example/invoice/1",
            },
        }
        client = MagicMock()
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        client.post = AsyncMock(return_value=response)

        with patch("main.httpx.AsyncClient", return_value=client):
            result = self.client.post(
                "/payments/create",
                json={"email": "new@example.test", "tier": "pro"},
            )

        self.assertEqual(result.status_code, 200)
        data = result.json()
        self.assertEqual(data["gateway"], "oxapay")
        self.assertEqual(data["payment_url"], "https://pay.oxapay.example/invoice/1")
        request_payload = client.post.await_args.kwargs["json"]
        self.assertEqual(request_payload["currency"], "USD")
        self.assertFalse(request_payload["sandbox"])
        self.assertEqual(
            request_payload["callback_url"],
            "https://payments.example.test/payments/webhook/oxapay",
        )
        with sqlite3.connect(main.PAYMENTS_DB) as conn:
            row = conn.execute(
                "SELECT gateway, status, amount FROM payments WHERE order_id = ?",
                (data["order_id"],),
            ).fetchone()
        self.assertEqual(row, ("oxapay", "pending", 9.99))

    def test_create_payment_rejects_non_https_callback_origin(self):
        main.PAYMENTS_PUBLIC_BASE_URL = "http://payments.example.test"
        with self.assertRaises(main.HTTPException) as error:
            main._payment_public_base_url()
        self.assertEqual(error.exception.status_code, 503)

    def test_oxapay_paid_callback_activates_once(self):
        order_id, track_id = self.create_order()
        payload = {
            "type": "invoice",
            "status": "Paid",
            "order_id": order_id,
            "track_id": track_id,
            "value": 9.99,
        }

        first = self.signed_oxapay_request(payload)
        second = self.signed_oxapay_request(payload)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.text, "ok")
        self.assertEqual(second.status_code, 200)
        with sqlite3.connect(main.PAYMENTS_DB) as conn:
            status = conn.execute(
                "SELECT status FROM payments WHERE order_id = ?", (order_id,)
            ).fetchone()[0]
        with sqlite3.connect(main.API_KEYS_DB) as conn:
            tier, paid_until = conn.execute(
                "SELECT tier, paid_until FROM api_keys WHERE email = ?",
                ("buyer@example.test",),
            ).fetchone()
        self.assertEqual(status, "paid")
        self.assertEqual(tier, "pro")
        self.assertIsNotNone(paid_until)
        first_expiry = paid_until
        self.assertEqual(
            main.grant_paid_access("buyer@example.test", "pro", order_id)["paid_until"],
            first_expiry,
        )
        with sqlite3.connect(main.API_KEYS_DB) as conn:
            self.assertEqual(
                conn.execute(
                    "SELECT paid_until FROM api_keys WHERE email = ?",
                    ("buyer@example.test",),
                ).fetchone()[0],
                first_expiry,
            )

    def test_oxapay_rejects_bad_signature_track_and_underpayment(self):
        order_id, track_id = self.create_order()
        payload = {
            "type": "invoice",
            "status": "Paid",
            "order_id": order_id,
            "track_id": track_id,
            "value": 9.99,
        }
        body = json.dumps(payload, separators=(",", ":")).encode()

        bad_signature = self.client.post(
            "/payments/webhook/oxapay",
            content=body,
            headers={"HMAC": "bad", "Content-Type": "application/json"},
        )
        self.assertEqual(bad_signature.status_code, 401)

        payload["track_id"] = "wrong-track"
        wrong_track = self.signed_oxapay_request(payload)
        self.assertEqual(wrong_track.status_code, 400)

        payload["track_id"] = track_id
        underpaid = self.signed_oxapay_request(payload, provider_confirmed=False)
        self.assertEqual(underpaid.status_code, 409)

    def test_nowpayments_signed_final_callback_activates_order(self):
        order_id, track_id = self.create_order("nowpayments", "tp-pro-now", "invoice-42")
        payload = {
            "payment_status": "finished",
            "order_id": order_id,
            "invoice_id": track_id,
            "price_amount": 9.99,
            "price_currency": "usd",
        }
        signature_payload = json.dumps(
            main._sorted_json(payload), separators=(",", ":"), ensure_ascii=False
        ).encode()
        signature = hmac.new(
            main.NOWPAYMENTS_IPN_SECRET.encode(), signature_payload, hashlib.sha512
        ).hexdigest()

        response = self.client.post(
            "/payments/webhook/nowpayments",
            json=payload,
            headers={"x-nowpayments-sig": signature},
        )

        self.assertEqual(response.status_code, 200)
        with sqlite3.connect(main.PAYMENTS_DB) as conn:
            status = conn.execute(
                "SELECT status FROM payments WHERE order_id = ?", (order_id,)
            ).fetchone()[0]
        self.assertEqual(status, "paid")

    def test_paid_order_claim_returns_key_but_email_lookup_does_not(self):
        order_id, track_id = self.create_order(
            order_id="tp-pro-0123456789abcdef0123456789abcdef"
        )
        pending_claim = self.client.post(
            "/payments/claim", json={"order_id": order_id}
        )
        self.assertEqual(pending_claim.status_code, 202)

        payload = {
            "type": "invoice",
            "status": "Paid",
            "order_id": order_id,
            "track_id": track_id,
            "value": 9.99,
        }
        self.assertEqual(self.signed_oxapay_request(payload).status_code, 200)

        claim = self.client.post(
            "/payments/claim", json={"order_id": order_id}
        )
        self.assertEqual(claim.status_code, 200)
        self.assertTrue(claim.json()["api_key"].startswith("tp_"))
        self.assertEqual(claim.headers["cache-control"], "no-store")
        self.assertTrue(claim.json()["paid_until"])
        self.assertEqual(
            self.client.get(
                "/api-keys/usage", params={"email": "buyer@example.test"}
            ).status_code,
            400,
        )

    def test_paid_access_renews_and_expired_keys_downgrade(self):
        first = main.grant_paid_access(
            "renew@example.test", "pro", "tp-pro-first"
        )
        second = main.grant_paid_access(
            "renew@example.test", "enterprise", "tp-enterprise-second"
        )
        first_expiry = datetime.fromisoformat(first["paid_until"])
        second_expiry = datetime.fromisoformat(second["paid_until"])
        self.assertEqual(second_expiry - first_expiry, timedelta(days=30))

        with sqlite3.connect(main.API_KEYS_DB) as conn:
            conn.execute(
                "UPDATE api_keys SET paid_until = ? WHERE email = ?",
                ("2000-01-01T00:00:00+00:00", "renew@example.test"),
            )
            api_key = conn.execute(
                "SELECT api_key FROM api_keys WHERE email = ?",
                ("renew@example.test",),
            ).fetchone()[0]
        key_info = main.check_api_key(api_key)
        self.assertEqual(key_info["tier"], "free")
        self.assertEqual(key_info["daily_limit"], 100)

    def test_pending_callback_does_not_activate_and_direct_verification_is_disabled(self):
        order_id, track_id = self.create_order()
        response = self.signed_oxapay_request(
            {
                "type": "invoice",
                "status": "Paying",
                "order_id": order_id,
                "track_id": track_id,
                "value": 9.99,
            }
        )
        self.assertEqual(response.status_code, 200)
        direct = self.client.post("/payments/verify-tx", json={"order_id": order_id, "tx_hash": "x" * 64})
        self.assertEqual(direct.status_code, 503)

    def test_checkout_fails_closed_without_provider_and_checks_existing_key(self):
        main.OXAPAY_MERCHANT_KEY = ""
        main.NOWPAYMENTS_API_KEY = ""
        main.NOWPAYMENTS_IPN_SECRET = ""
        unavailable = self.client.post(
            "/payments/create",
            json={"email": "new@example.test", "tier": "pro"},
        )
        self.assertEqual(unavailable.status_code, 503)

        with sqlite3.connect(main.API_KEYS_DB) as conn:
            conn.execute(
                "INSERT INTO api_keys (email, api_key, tier, daily_limit, created_at) "
                "VALUES (?, ?, 'free', 100, ?)",
                ("existing@example.test", "tp_existing_secret", "2026-01-01T00:00:00+00:00"),
            )
        with self.assertRaises(main.HTTPException) as error:
            main._validate_checkout_owner("existing@example.test", "")
        self.assertEqual(error.exception.status_code, 403)
        main._validate_checkout_owner("existing@example.test", "tp_existing_secret")


if __name__ == "__main__":
    unittest.main()
