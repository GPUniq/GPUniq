"""Two-dimensional GPU picker.

The user navigates a grid of GPU models laid out by generation.  Columns
are ordered right-to-left from oldest-consumer to newest-datacenter so
power scales naturally with the arrow keys.

    Datacenter   50XX        40XX              30XX        20XX            1660
    ──────────   ────────    ────────────      ─────────   ──────────      ─────────
    H100 SXM     RTX 5090    RTX 4090          RTX 3090 Ti RTX 2080 Ti     GTX 1660 Ti
    H100 PCIe    RTX 5080    RTX 4080 SUPER    RTX 3090    RTX 2080 SUPER  GTX 1660 SUPER
    …

Keys
----
    ↑ ↓        move up/down within the column
    ← →        move left/right between columns
    Enter      pick the highlighted cell
    Esc / q    cancel

Returns the selected GPU model string (e.g. ``"RTX 4090"``) or ``None`` on
cancel / unsupported environment (missing ``prompt_toolkit``).
"""

from __future__ import annotations

from typing import List, Optional, Tuple


# Columns ordered so datacenter/newest is on the LEFT, oldest/cheapest on the RIGHT.
# Data-center column is much taller than consumer columns — that is OK; empty
# cells in shorter columns are rendered blank and skipped by the cursor.
GPU_COLUMNS: List[Tuple[str, List[str]]] = [
    ("Datacenter", [
        "H200",
        "H100 SXM",
        "H100 PCIe",
        "H100 NVL",
        "A100 80GB SXM",
        "A100 80GB PCIe",
        "A100 40GB",
        "L40S",
        "L40",
        "L4",
        "A40",
        "A30",
        "A10",
        "A6000",
        "A5000",
        "A4000",
    ]),
    ("50XX", [
        "RTX 5090",
        "RTX 5080",
    ]),
    ("40XX", [
        "RTX 4090",
        "RTX 4080 SUPER",
        "RTX 4080",
        "RTX 4070 Ti SUPER",
        "RTX 4070 Ti",
        "RTX 4070 SUPER",
        "RTX 4070",
        "RTX 4060 Ti",
        "RTX 4060",
    ]),
    ("30XX", [
        "RTX 3090 Ti",
        "RTX 3090",
        "RTX 3080 Ti",
        "RTX 3080",
        "RTX 3070 Ti",
        "RTX 3070",
        "RTX 3060 Ti",
        "RTX 3060",
        "RTX 3050",
    ]),
    ("20XX", [
        "RTX 2080 Ti",
        "RTX 2080 SUPER",
        "RTX 2080",
        "RTX 2070 SUPER",
        "RTX 2070",
        "RTX 2060 SUPER",
        "RTX 2060",
    ]),
    ("1660", [
        "GTX 1660 Ti",
        "GTX 1660 SUPER",
        "GTX 1660",
    ]),
]

# Extra options rendered under the grid as a single horizontal row.
META_OPTIONS: List[Tuple[str, Optional[str]]] = [
    ("Any GPU", None),
    ("Other…",  "__custom__"),
]

CELL_WIDTH = 18


def _default_position(default_model: Optional[str]) -> Tuple[int, int]:
    """Map a GPU model string to a (col, row) cursor position. Falls back to 50XX/5090."""
    if default_model:
        norm = default_model.strip().lower()
        for ci, (_name, items) in enumerate(GPU_COLUMNS):
            for ri, item in enumerate(items):
                if item.lower() == norm or norm in item.lower() or item.lower() in norm:
                    return ci, ri
    # RTX 5090 by default
    return 1, 0


def pick_gpu_matrix(default: Optional[str] = None) -> Optional[str]:
    """Run the 2D picker. Returns the selected GPU model or None."""
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
    except ImportError:
        return None

    col, row = _default_position(default)
    state = {"col": col, "row": row}
    # 0..N-1 = rows inside GPU_COLUMNS; N = the META_OPTIONS row.
    max_data_rows = max(len(items) for _, items in GPU_COLUMNS)
    meta_row_index = max_data_rows
    result: List[Optional[str]] = [None]
    done: List[bool] = [False]

    # ── Cursor movement helpers ─────────────────────────────────────────

    def current_cell_value() -> Optional[str]:
        c, r = state["col"], state["row"]
        if r == meta_row_index:
            if c < len(META_OPTIONS):
                return META_OPTIONS[c][1] or "__any__"
            return None
        items = GPU_COLUMNS[c][1]
        if r < len(items):
            return items[r]
        return None

    def clamp_row_in_column():
        c = state["col"]
        if state["row"] == meta_row_index:
            if c >= len(META_OPTIONS):
                state["col"] = len(META_OPTIONS) - 1
            return
        length = len(GPU_COLUMNS[c][1])
        if length == 0:
            state["row"] = meta_row_index
        elif state["row"] >= length:
            state["row"] = length - 1

    # ── Render ──────────────────────────────────────────────────────────

    def render():
        out = []
        cc, cr = state["col"], state["row"]

        # Title
        out.append(("bold", "\n  Select a GPU model  "))
        out.append(("fg:#888888", "(←/→ columns · ↑/↓ rows · Enter pick · Esc cancel)\n\n"))

        # Header
        out.append(("", "  "))
        for ci, (name, _) in enumerate(GPU_COLUMNS):
            style = "bold underline fg:#00AAFF" if ci == cc else "bold underline"
            out.append((style, f" {name:<{CELL_WIDTH}}"))
        out.append(("", "\n"))

        # Data rows
        for ri in range(max_data_rows):
            out.append(("", "  "))
            for ci, (_, items) in enumerate(GPU_COLUMNS):
                cell = items[ri] if ri < len(items) else ""
                text = f" {cell:<{CELL_WIDTH}}"
                if ri == cr and ci == cc and cell:
                    out.append(("reverse bold", text))
                elif cell:
                    out.append(("", text))
                else:
                    out.append(("fg:#444444", text))
            out.append(("", "\n"))

        # Separator + meta row
        out.append(("", "\n  "))
        out.append(("fg:#666666", "─" * (len(GPU_COLUMNS) * (CELL_WIDTH + 1) - 2)))
        out.append(("", "\n  "))
        for ci, (label, _) in enumerate(META_OPTIONS):
            text = f" {label:<{CELL_WIDTH}}"
            if cr == meta_row_index and ci == cc:
                out.append(("reverse bold", text))
            else:
                out.append(("", text))
        out.append(("", "\n"))

        return out

    # ── Key bindings ────────────────────────────────────────────────────

    kb = KeyBindings()

    @kb.add("up")
    def _up(event):
        if state["row"] == meta_row_index:
            # Jump to the last filled row of the current column
            c = state["col"]
            col_len = len(GPU_COLUMNS[c][1]) if c < len(GPU_COLUMNS) else 0
            state["row"] = col_len - 1 if col_len else meta_row_index
        elif state["row"] > 0:
            state["row"] -= 1

    @kb.add("down")
    def _down(event):
        c = state["col"]
        col_len = len(GPU_COLUMNS[c][1]) if c < len(GPU_COLUMNS) else 0
        if state["row"] < col_len - 1:
            state["row"] += 1
        else:
            # Drop into the meta row (Any GPU / Other…)
            state["row"] = meta_row_index
            if c >= len(META_OPTIONS):
                state["col"] = len(META_OPTIONS) - 1

    @kb.add("left")
    def _left(event):
        if state["row"] == meta_row_index:
            if state["col"] > 0:
                state["col"] -= 1
        else:
            if state["col"] > 0:
                state["col"] -= 1
                clamp_row_in_column()

    @kb.add("right")
    def _right(event):
        if state["row"] == meta_row_index:
            if state["col"] < len(META_OPTIONS) - 1:
                state["col"] += 1
        else:
            if state["col"] < len(GPU_COLUMNS) - 1:
                state["col"] += 1
                clamp_row_in_column()

    @kb.add("enter")
    def _enter(event):
        result[0] = current_cell_value()
        done[0] = True
        event.app.exit()

    @kb.add("escape")
    @kb.add("q")
    @kb.add("c-c")
    def _cancel(event):
        event.app.exit()

    control = FormattedTextControl(render, focusable=True, show_cursor=False)
    body = Window(content=control, always_hide_cursor=True)
    layout = Layout(HSplit([body]))

    app = Application(layout=layout, key_bindings=kb, full_screen=True)
    app.run()

    if not done[0]:
        return None
    picked = result[0]
    if picked in ("__any__", None):
        return ""  # "" = no filter, distinct from None (cancel)
    return picked