"""Interactive marketplace browser used by `gg rent` and `gg replace`.

Design goals
------------
- **Full-width terminal UI** — tables and headers span the whole window.
- **No flags required** — a one-shot filter wizard runs before the first
  browse; flags only act as shortcuts that pre-fill the wizard.
- **Clean methods** — one class, small responsibilities, testable pieces.

Entry point:
    RentFlow(api).run(gpu_model=..., min_count=..., ...) -> picked_agent | None
"""

from __future__ import annotations

import shutil
from typing import Any, Dict, List, Optional, Tuple

from .client_api import ClientAPI


# ─── Constants ───────────────────────────────────────────────────────────────

SORT_OPTIONS: List[Tuple[str, str]] = [
    ("price-low", "Cheapest first"),
    ("price-high", "Most expensive first"),
    ("reliability", "Best reliability"),
    ("vram", "Most VRAM"),
    ("performance", "Best performance"),
]

GPU_PRESETS: List[Tuple[str, str]] = [
    ("", "Any GPU"),
    ("RTX 5090", "RTX 5090"),
    ("RTX 4090", "RTX 4090"),
    ("RTX 4080", "RTX 4080"),
    ("RTX 3090", "RTX 3090"),
    ("A100", "A100"),
    ("H100", "H100"),
    ("L40", "L40"),
    ("L4", "L4"),
]

COUNT_PRESETS: List[Tuple[Optional[int], str]] = [
    (None, "Any"),
    (1, "1 GPU"),
    (2, "2 GPUs"),
    (4, "4 GPUs"),
    (8, "8 GPUs"),
]

PRICE_PRESETS: List[Tuple[Optional[float], str]] = [
    (None, "Any price"),
    (0.30, "Under $0.30 / hr"),
    (0.50, "Under $0.50 / hr"),
    (1.00, "Under $1.00 / hr"),
    (2.00, "Under $2.00 / hr"),
    (5.00, "Under $5.00 / hr"),
]

PAGE_SIZE = 15
MIN_WIDTH = 100


# ─── Small helpers ───────────────────────────────────────────────────────────


def term_width(minimum: int = MIN_WIDTH) -> int:
    return max(minimum, shutil.get_terminal_size((120, 24)).columns)


def truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[: max(0, width - 1)] + "…"


def rule(char: str = "─", width: Optional[int] = None) -> str:
    return char * (width or term_width())


def banner(text: str) -> str:
    width = term_width()
    bar = rule("═", width)
    return f"\n{bar}\n  {text}\n{bar}"


def fmt_price(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"${float(value):.2f}/hr"
    except (TypeError, ValueError):
        return "—"


# ─── Main flow ───────────────────────────────────────────────────────────────


class RentFlow:
    """Interactive browser for GPU offers.

    Usage:
        picked = RentFlow(api).run()           # fully interactive
        picked = RentFlow(api).run(gpu_model='A100')  # prefilled, still interactive
    """

    def __init__(self, api: ClientAPI):
        self.api = api

        self.gpu_model: Optional[str] = None
        self.min_count: Optional[int] = None
        self.max_price: Optional[float] = None
        self.verified_only: bool = False
        self.sort_by: str = "price-low"

        self._page: int = 1

    # ── Public entry points ─────────────────────────────────────────────

    def seed(
        self,
        *,
        gpu_model: Optional[str] = None,
        min_count: Optional[int] = None,
        max_price: Optional[float] = None,
        verified_only: bool = False,
        sort_by: Optional[str] = None,
    ) -> None:
        """Apply initial filters from CLI flags. Does not prompt."""
        self.gpu_model = gpu_model
        self.min_count = min_count
        self.max_price = max_price
        self.verified_only = bool(verified_only)
        if sort_by:
            self.sort_by = sort_by
        self._seeded_from_flags = any(
            [gpu_model, min_count, max_price, verified_only, sort_by]
        )
        self._wizard_done = False

    def run_next(self) -> Optional[Dict[str, Any]]:
        """Let the user pick one agent from the marketplace.
        On first call, may run the filter wizard. Returns picked agent or None."""
        if (
            not getattr(self, "_seeded_from_flags", False)
            and not getattr(self, "_wizard_done", False)
        ):
            self._filter_wizard()
            self._wizard_done = True
        return self._browse_loop()

    def run(
        self,
        *,
        gpu_model: Optional[str] = None,
        min_count: Optional[int] = None,
        max_price: Optional[float] = None,
        verified_only: bool = False,
        sort_by: Optional[str] = None,
        skip_wizard: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Convenience: seed + run_next in one shot. Used by tests and ad-hoc callers."""
        self.seed(
            gpu_model=gpu_model,
            min_count=min_count,
            max_price=max_price,
            verified_only=verified_only,
            sort_by=sort_by,
        )
        if skip_wizard:
            self._wizard_done = True
        return self.run_next()

    # ── Filter wizard ───────────────────────────────────────────────────

    def _filter_wizard(self) -> None:
        print(banner("GPU filters — hit Enter to accept the default on each step"))

        inquirer = self._inquirer()
        if inquirer is None:
            # Fallback: skip the wizard, use defaults
            return

        self.gpu_model = self._wizard_gpu(inquirer)
        self.min_count = self._wizard_count(inquirer)
        self.max_price = self._wizard_price(inquirer)
        self.verified_only = inquirer.confirm(
            message="Only verified providers?", default=False
        ).execute()
        self.sort_by = self._ask_sort(inquirer)

    def _wizard_gpu(self, inquirer) -> Optional[str]:
        choices = [{"name": label, "value": val} for val, label in GPU_PRESETS]
        choices.append({"name": "Other (type model name…)", "value": "__other__"})
        picked = inquirer.select(
            message="GPU model:",
            choices=self._pad_choices(choices),
            default="",
        ).execute()
        if picked == "__other__":
            text = inquirer.text(message="GPU model (e.g. 'RTX 6000'):").execute()
            return (text or "").strip() or None
        return picked or None

    def _wizard_count(self, inquirer) -> Optional[int]:
        choices = [{"name": label, "value": val} for val, label in COUNT_PRESETS]
        return inquirer.select(
            message="Minimum GPU count:",
            choices=self._pad_choices(choices),
            default=None,
        ).execute()

    def _wizard_price(self, inquirer) -> Optional[float]:
        choices = [{"name": label, "value": val} for val, label in PRICE_PRESETS]
        choices.append({"name": "Custom…", "value": "__custom__"})
        picked = inquirer.select(
            message="Max price per hour:",
            choices=self._pad_choices(choices),
            default=None,
        ).execute()
        if picked == "__custom__":
            text = inquirer.text(message="Max USD per hour:").execute()
            try:
                return float((text or "").strip()) if text else None
            except ValueError:
                return None
        return picked

    def _ask_sort(self, inquirer) -> str:
        choices = [{"name": label, "value": val} for val, label in SORT_OPTIONS]
        return inquirer.select(
            message="Sort by:",
            choices=self._pad_choices(choices),
            default=self.sort_by,
        ).execute()

    # ── Browse loop ─────────────────────────────────────────────────────

    def _browse_loop(self) -> Optional[Dict[str, Any]]:
        while True:
            data = self.api.list_marketplace(
                page=self._page,
                page_size=PAGE_SIZE,
                gpu_model=[self.gpu_model] if self.gpu_model else None,
                min_gpu_count=self.min_count,
                max_price_per_hour=self.max_price,
                verified_only=self.verified_only or None,
                sort_by=self.sort_by,
            )
            if data is None:
                return None

            agents = list(data.get("agents") or [])
            total = int(data.get("total_count") or len(agents))
            pages = max(1, -(-total // PAGE_SIZE)) if total else 1
            self._page = min(self._page, pages)

            self._render_page(agents, total, pages)

            if not agents:
                if not self._confirm_retry():
                    return None
                continue

            action = self._prompt_action(len(agents), pages)
            if action is None:
                return None
            if action == "next":
                self._page = min(self._page + 1, pages)
            elif action == "prev":
                self._page = max(self._page - 1, 1)
            elif action == "filter":
                self._filter_wizard()
                self._page = 1
            elif action == "sort":
                inquirer = self._inquirer()
                if inquirer:
                    self.sort_by = self._ask_sort(inquirer)
                    self._page = 1
            elif isinstance(action, int):
                return agents[action - 1]

    # ── Rendering ───────────────────────────────────────────────────────

    def _render_page(self, agents: List[dict], total: int, pages: int) -> None:
        width = term_width()
        print(banner(f"Marketplace  ·  page {self._page}/{pages}  ·  {total} offers"))
        print(f"  {self._filter_summary()}")
        print()
        if agents:
            print(self._build_table(agents, width))
        else:
            print("  No GPUs match the current filters.\n")
        print(rule("─", width))

    def _filter_summary(self) -> str:
        parts = [f"GPU: {self.gpu_model or 'any'}"]
        if self.min_count:
            parts.append(f"count ≥ {self.min_count}")
        if self.max_price:
            parts.append(f"max ${self.max_price:.2f}/hr")
        if self.verified_only:
            parts.append("verified only")
        parts.append(f"sort: {self.sort_by}")
        return "  ·  ".join(parts)

    # Column catalog. Priority 0 = always shown; higher priorities get dropped
    # first on narrow terminals. `width=None` means flex (share remaining space
    # with other flex columns). `align`: '<' left, '>' right.
    # The order here defines the left-to-right display order.
    _COLS: List[Tuple[str, str, Optional[int], str, int]] = [
        ("idx",      "#",        4,    ">", 0),
        ("gpu",      "GPU",      None, "<", 0),   # flex
        ("cnt",      "CNT",      4,    ">", 1),
        ("vram",     "VRAM",     7,    ">", 1),
        ("ram",      "RAM",      7,    ">", 3),
        ("disk",     "DISK",     8,    ">", 4),
        ("cpu",      "CPU",      4,    ">", 6),
        ("cpu_model","CPU MODEL", 18,  "<", 8),
        ("net",      "NET ↓/↑",  16,   ">", 5),
        ("location", "LOCATION", None, "<", 2),   # flex
        ("relia",    "RELIA",    6,    ">", 2),
        ("avail",    "AVAIL",    6,    ">", 7),
        ("hosting",  "HOSTING",  10,   "<", 9),
        ("price",    "PRICE",    11,   ">", 0),
        ("verif",    "VER",      3,    "<", 1),
    ]

    _MIN_FLEX = 10  # minimum per flex column

    # ── Column selection (adaptive) ─────────────────────────────────────

    def _choose_columns(self, width: int) -> List[Tuple[str, str, int, str]]:
        """Pick the widest set of columns that fits. Returns columns in display
        order, with flex widths resolved to concrete integers."""
        priorities = sorted({c[4] for c in self._COLS})
        chosen: List[Tuple[str, str, Optional[int], str, int]] = []

        def cost(cols) -> int:
            fixed = sum((w or 0) for _, _, w, _, _ in cols)
            flex_n = sum(1 for _, _, w, _, _ in cols if w is None)
            gaps = max(0, len(cols) - 1)
            return fixed + flex_n * self._MIN_FLEX + gaps

        for pri in priorities:
            candidate = chosen + [c for c in self._COLS if c[4] == pri and c not in chosen]
            if cost(candidate) <= width:
                chosen = candidate
            else:
                break

        # Keep display order
        order = {c[0]: i for i, c in enumerate(self._COLS)}
        chosen.sort(key=lambda c: order[c[0]])

        # Resolve flex widths — split leftover evenly, then give GPU a bigger share.
        fixed_total = sum((w or 0) for _, _, w, _, _ in chosen)
        flex_cols = [c for c in chosen if c[2] is None]
        gaps = max(0, len(chosen) - 1)
        flex_budget = max(self._MIN_FLEX * len(flex_cols), width - fixed_total - gaps)

        flex_widths: Dict[str, int] = {}
        if len(flex_cols) == 1:
            flex_widths[flex_cols[0][0]] = flex_budget
        elif len(flex_cols) == 2:
            # GPU gets 60%, LOCATION 40% — GPU labels are longer on average.
            gpu_w = max(self._MIN_FLEX, int(flex_budget * 0.60))
            loc_w = max(self._MIN_FLEX, flex_budget - gpu_w)
            flex_widths["gpu"] = gpu_w
            flex_widths["location"] = loc_w
        else:
            for c in flex_cols:
                flex_widths[c[0]] = max(self._MIN_FLEX, flex_budget // max(1, len(flex_cols)))

        return [
            (key, header, flex_widths.get(key, w or 0), align)
            for (key, header, w, align, _pri) in chosen
        ]

    # ── Rendering ───────────────────────────────────────────────────────

    def _build_table(self, agents: List[dict], width: int) -> str:
        cols = self._choose_columns(width)
        lines = [self._render_row(cols, self._header_values(cols))]
        lines.append(rule("─", width))
        for i, a in enumerate(agents, 1):
            lines.append(self._render_row(cols, self._data_values(i, a)))
        return "\n".join(lines)

    @staticmethod
    def _header_values(cols: List[Tuple[str, str, int, str]]) -> Dict[str, str]:
        return {key: header for key, header, _, _ in cols}

    def _data_values(self, i: int, a: dict) -> Dict[str, str]:
        return {
            "idx":       str(i),
            "gpu":       str(a.get("gpu_model") or "Unknown"),
            "cnt":       str(a.get("gpu_count") or 1),
            "vram":      self._gb(a.get("vram_gb")),
            "ram":       self._gb(a.get("ram_gb")),
            "disk":      self._gb(a.get("storage_gb")),
            "cpu":       str(a.get("cpu_count") or "—"),
            "cpu_model": str(a.get("cpu_model") or "—"),
            "net":       self._net(a.get("down_mbps"), a.get("up_mbps")),
            "location":  str(a.get("location") or "—"),
            "relia":     self._pct(a.get("reliability")),
            "avail":     self._pct(a.get("availability")),
            "hosting":   str(a.get("hosting_type") or "—"),
            "price":     fmt_price(a.get("price_per_hour")),
            "verif":     "✓" if a.get("verified") else "·",
        }

    @staticmethod
    def _render_row(
        cols: List[Tuple[str, str, int, str]],
        values: Dict[str, str],
    ) -> str:
        parts: List[str] = []
        for key, _header, w, align in cols:
            v = values.get(key, "")
            parts.append(f"{truncate(v, w):{align}{w}}")
        return " ".join(parts)

    # ── Cell formatters ─────────────────────────────────────────────────

    @staticmethod
    def _gb(value: Any) -> str:
        try:
            n = int(value or 0)
        except (TypeError, ValueError):
            return "—"
        return f"{n} GB" if n else "—"

    @staticmethod
    def _net(down: Any, up: Any) -> str:
        def _n(x):
            try:
                return int(x or 0)
            except (TypeError, ValueError):
                return 0
        d, u = _n(down), _n(up)
        if not d and not u:
            return "—"
        return f"{d}/{u} Mbps"

    @staticmethod
    def _pct(value: Any) -> str:
        try:
            n = float(value or 0)
        except (TypeError, ValueError):
            return "—"
        if n <= 0:
            return "—"
        if n <= 1:  # 0–1 scale
            n *= 100
        return f"{n:.1f}%"

    # ── Action prompt ───────────────────────────────────────────────────

    def _prompt_action(self, n: int, pages: int):
        """Returns: int (pick), 'next', 'prev', 'filter', 'sort', or None (cancel)."""
        print("  " + self._action_hint(n, pages))
        raw = input("  > ").strip().lower()

        if raw in ("", "q", "quit", "exit", "x"):
            return None
        if raw in ("n", "next"):
            if self._page >= pages:
                print("  Already at last page.")
                return self._prompt_action(n, pages)
            return "next"
        if raw in ("p", "prev", "previous"):
            if self._page <= 1:
                print("  Already at first page.")
                return self._prompt_action(n, pages)
            return "prev"
        if raw in ("f", "filter", "filters"):
            return "filter"
        if raw in ("s", "sort"):
            return "sort"

        try:
            idx = int(raw)
        except ValueError:
            print("  Unrecognized input. Try again.")
            return self._prompt_action(n, pages)

        if 1 <= idx <= n:
            return idx
        print(f"  Pick a number between 1 and {n}.")
        return self._prompt_action(n, pages)

    def _action_hint(self, n: int, pages: int) -> str:
        parts = [f"[1–{n}] pick"]
        if self._page < pages:
            parts.append("[n] next")
        if self._page > 1:
            parts.append("[p] prev")
        parts.append("[f] filters")
        parts.append("[s] sort")
        parts.append("[q] quit")
        return "   ".join(parts)

    def _confirm_retry(self) -> bool:
        print()
        ans = input("  [f] change filters   [q] quit  > ").strip().lower()
        if ans in ("f", "filter", "filters"):
            self._filter_wizard()
            self._page = 1
            return True
        return False

    # ── InquirerPy adapter ──────────────────────────────────────────────

    @staticmethod
    def _inquirer():
        try:
            from InquirerPy import inquirer
            return inquirer
        except ImportError:
            return None

    @staticmethod
    def _pad_choices(choices: List[dict]) -> List[dict]:
        """Pad choice labels to terminal width so the select widget feels wide."""
        width = term_width()
        target = max(40, width - 10)
        padded = []
        for c in choices:
            name = str(c.get("name", ""))
            if len(name) < target:
                name = name + " " * (target - len(name))
            padded.append({**c, "name": name})
        return padded
