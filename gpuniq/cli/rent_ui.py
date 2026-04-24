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

    # ── Public entry point ──────────────────────────────────────────────

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
        self.gpu_model = gpu_model
        self.min_count = min_count
        self.max_price = max_price
        self.verified_only = bool(verified_only)
        if sort_by:
            self.sort_by = sort_by

        seeded = any([gpu_model, min_count, max_price, verified_only, sort_by])
        if not seeded and not skip_wizard:
            self._filter_wizard()

        return self._browse_loop()

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

    # Column widths for everything except GPU model + LOCATION, which flex.
    # Tuples are (key, header, width, align)  — align: '<' left, '>' right.
    _FIXED_COLS: List[Tuple[str, str, int, str]] = [
        ("idx",    "#",      4,  ">"),
        # gpu flex
        ("cnt",    "CNT",    4,  ">"),
        ("vram",   "VRAM",   7,  ">"),
        ("ram",    "RAM",    7,  ">"),
        ("disk",   "DISK",   8,  ">"),
        ("cpu",    "CPU",    4,  ">"),
        ("net",    "NET ↓/↑",    16, ">"),
        # location flex
        ("relia",  "RELIA",  6,  ">"),
        ("price",  "PRICE",  11, ">"),
        ("verif",  "VER",    3,  "<"),
    ]

    def _build_table(self, agents: List[dict], width: int) -> str:
        gap = 1
        fixed_total = sum(c[2] for c in self._FIXED_COLS)
        total_cols = len(self._FIXED_COLS) + 2  # +2 flex cols (gpu, location)
        gaps_total = gap * (total_cols - 1)
        remaining = max(30, width - fixed_total - gaps_total)
        w_gpu = max(12, int(remaining * 0.58))
        w_loc = max(8, remaining - w_gpu)

        lines = [self._header_row(w_gpu, w_loc), rule("─", width)]
        for i, a in enumerate(agents, 1):
            lines.append(self._data_row(i, a, w_gpu, w_loc))
        return "\n".join(lines)

    def _header_row(self, w_gpu: int, w_loc: int) -> str:
        fields = {key: (header, align) for key, header, _, align in self._FIXED_COLS}
        return self._compose_row({
            **{key: fields[key][0] for key in fields},
            "gpu": "GPU",
            "location": "LOCATION",
        }, w_gpu, w_loc)

    def _data_row(self, i: int, a: dict, w_gpu: int, w_loc: int) -> str:
        return self._compose_row({
            "idx":      str(i),
            "gpu":      str(a.get("gpu_model") or "Unknown"),
            "cnt":      str(a.get("gpu_count") or 1),
            "vram":     self._gb(a.get("vram_gb")),
            "ram":      self._gb(a.get("ram_gb")),
            "disk":     self._gb(a.get("storage_gb")),
            "cpu":      str(a.get("cpu_count") or "—"),
            "net":      self._net(a.get("down_mbps"), a.get("up_mbps")),
            "location": str(a.get("location") or "—"),
            "relia":    self._pct(a.get("reliability")),
            "price":    fmt_price(a.get("price_per_hour")),
            "verif":    "✓" if a.get("verified") else "·",
        }, w_gpu, w_loc)

    def _compose_row(self, values: Dict[str, str], w_gpu: int, w_loc: int) -> str:
        parts: List[str] = []
        for key, _header, width, align in self._FIXED_COLS:
            v = values.get(key, "")
            parts.append(f"{truncate(v, width):{align}{width}}")
            if key == "idx":
                parts.append(f"{truncate(values.get('gpu', ''), w_gpu):<{w_gpu}}")
            if key == "net":
                parts.append(f"{truncate(values.get('location', ''), w_loc):<{w_loc}}")
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
