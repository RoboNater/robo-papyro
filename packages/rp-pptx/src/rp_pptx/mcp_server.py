"""MCP server for rp-pptx — **a documented stub, deliberately empty (Phase 2).**

Nothing here is wired up yet, and importing this module must stay free: it is a
placeholder recording the shape Phase 2 fills in, not a partial implementation
to build on. rp-pptx-spec section 12 step 9 asks for exactly this — Phase 2.5
does not depend on Phase 2 in either direction, so the leaf leaves a claim
marker rather than a dependency.

**Why it is empty rather than started.** Suite Phase 2 puts the MCP servers in
their own distribution, `rp-mcp`, rather than in each leaf (parent spec section
9). The reason is the license gate: whatever the MCP SDK drags in stays out of
`rp-pptx`'s base install path by construction. Adding a FastMCP dependency here
to get a head start would undo exactly that, and this package already carries
one allowlist entry (XlsxWriter, via python-pptx) that exists only because an
import graph reaches further than the code does.

**What Phase 2 will do here.** Roughly three lines per tool, because the work is
already done: every function in :mod:`rp_pptx` returns a pydantic model, so a
tool definition is a name, a docstring, and a call. The read surface
(``get_index``, ``get_text``, ``get_tables``, ``get_images``, ``get_notes``,
``get_charts``, ``get_comments``) maps one-to-one. Two things need a decision
that is Phase 2's rather than this phase's: where an MCP client is allowed to
write, and whether ``get_comments`` raising
:class:`~rp_pptx.errors.UnsupportedFeatureError` for modern threaded comments
(section 7) should surface as a tool error or as a structured partial result.
"""

from __future__ import annotations

#: Phase 2 replaces this with the FastMCP app. Named here so the entry point it
#: will be registered under is obvious from this file alone.
app = None

__all__ = ["app"]
