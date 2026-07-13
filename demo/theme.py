"""UI theme constants."""

C_BG = "#0f1419"
C_PANEL = "#1a2332"
C_BORDER = "#2d3a4f"
C_TEXT = "#e2e8f0"
C_MUTED = "#94a3b8"
C_ACCENT = "#3b82f6"

CUSTOM_CSS = f"""
.gradio-container {{
    max-width: 1360px !important;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
    background: {C_BG} !important;
}}
.header-block {{
    border-bottom: 1px solid {C_BORDER};
    padding-bottom: 1rem;
    margin-bottom: 0.25rem;
}}
.header-block h1 {{
    font-size: 1.35rem;
    font-weight: 600;
    letter-spacing: -0.02em;
    margin: 0;
    color: {C_TEXT};
}}
.header-block p {{
    margin: 0.3rem 0 0;
    color: {C_MUTED};
    font-size: 0.85rem;
}}
footer {{ display: none !important; }}
"""

DARK_THEME = __import__("gradio", fromlist=["themes"]).themes.Base(
    primary_hue=__import__("gradio", fromlist=["themes"]).themes.colors.blue,
    neutral_hue=__import__("gradio", fromlist=["themes"]).themes.colors.gray,
).set(
    body_background_fill=C_BG,
    body_background_fill_dark=C_BG,
    background_fill_primary=C_PANEL,
    background_fill_primary_dark=C_PANEL,
    background_fill_secondary="#151d28",
    background_fill_secondary_dark="#151d28",
    border_color_primary=C_BORDER,
    border_color_primary_dark=C_BORDER,
    body_text_color=C_TEXT,
    body_text_color_dark=C_TEXT,
    block_background_fill=C_PANEL,
    block_background_fill_dark=C_PANEL,
    block_label_text_color=C_MUTED,
    block_label_text_color_dark=C_MUTED,
    input_background_fill="#151d28",
    input_background_fill_dark="#151d28",
    button_primary_background_fill=C_ACCENT,
    button_primary_background_fill_dark=C_ACCENT,
    button_primary_text_color="#ffffff",
    button_primary_text_color_dark="#ffffff",
)
