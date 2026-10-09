---
name: vibe-textual-ui
description: Textual widget and TCSS conventions for the Textual screens Mistral Vibe still has, the `vibe-acp --setup` onboarding. Use when building or styling onboarding widgets, writing TCSS rules, or working with theme variables there.
metadata:
  display-name: Vibe Textual UI
  short-description: Widget and TCSS conventions for Vibe onboarding
  default-prompt: Use $vibe-textual-ui to follow Vibe Textual UI conventions when building or styling onboarding widgets.
---

# Vibe Textual UI

Conventions for the Textual widgets Vibe still ships: the onboarding screens in `vibe/setup/onboarding/` (run by `vibe-acp --setup`) and the helper widgets they use under `vibe/cli/textual_ui/`. Apply when modifying those widgets or writing TCSS.

The Python Textual TUI has been removed; the interactive terminal UI is the Rust TUI (`vibe/cli-rust/`, see the `vibe-rust-tui` skill). Do not add Textual screens outside onboarding.

## TCSS

- When a rule sets `color: $text-muted;`, pair it with a nested `&:ansi { text-style: dim; }` so the muted intent survives under ANSI themes.
- Never use `ansi_*` colors (e.g. `ansi_red`, `ansi_bright_blue`). Use Textual theme variables like `$primary`, `$foreground`, `$surface`, `$error`, etc. — see https://textual.textualize.io/guide/design/. ANSI themes are derived from these variables automatically.
- Keep truncation and overflow behavior declarative in TCSS. Do not add resize handlers or explicit widget-width calculations solely to force an ellipsis; accept clipping or overflow when Textual cannot express the layout reliably.
