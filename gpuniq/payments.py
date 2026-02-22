"""Payments — deposits, history, spending."""

from typing import Any, Dict


class Payments:
    """Payment operations: deposit funds, view history and spending."""

    def __init__(self, client):
        self._c = client

    def deposit(self, amount: int, *, payment_system: str = "yookassa") -> Dict[str, Any]:
        """Create a deposit (top-up) request.

        Args:
            amount: Amount in rubles (must be > 0).
            payment_system: "yookassa" or "stripe".

        Returns:
            Dict with confirmation_url and payment_id.
        """
        return self._c.post("/payments/deposit", json={
            "amount": amount,
            "payment_system": payment_system,
        })

    def history(self) -> Any:
        """Get payment (deposit) history."""
        return self._c.get("/payments/history")

    def spending_history(self) -> Any:
        """Get spending history grouped by task."""
        return self._c.get("/payments/spending-history")

    # ── Stripe ───────────────────────────────────────────────────────

    def create_stripe_intent(self, amount: int) -> Dict[str, Any]:
        """Create a Stripe payment intent.

        Args:
            amount: Amount in rubles.
        """
        return self._c.post("/payments/stripe/create-payment-intent", json={
            "amount": amount,
            "payment_system": "stripe",
        })

    def check_stripe_payment(self, payment_id: str) -> Dict[str, Any]:
        """Check status of a Stripe payment."""
        return self._c.post(f"/payments/stripe/check-payment/{payment_id}")

    def stripe_public_key(self) -> Any:
        """Get Stripe publishable key."""
        return self._c.get("/payments/stripe/public-key")
