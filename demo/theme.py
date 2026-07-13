"""UI theme — dark shell with high-contrast tables/files."""

C_BG = "#0b1220"
C_PANEL = "#111827"
C_BORDER = "#334155"
C_TEXT = "#f1f5f9"
C_MUTED = "#cbd5e1"
C_ACCENT = "#3b82f6"
C_CODE_BG = "#020617"
C_CODE_FG = "#93c5fd"
C_TABLE_BG = "#0f172a"
C_TABLE_TEXT = "#f8fafc"
C_TABLE_HEADER = "#1e293b"

CUSTOM_CSS = f"""
.gradio-container {{
    max-width: 1360px !important;
    font-family: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif !important;
    background: {C_BG} !important;
    color: {C_TEXT} !important;
}}

.header-block {{
    border-bottom: 1px solid {C_BORDER};
    padding-bottom: 1.1rem;
    margin-bottom: 1rem;
}}
.header-block .eyebrow {{
    font-size: 0.72rem;
    letter-spacing: 0.14em;
    font-weight: 600;
    color: {C_ACCENT} !important;
    margin-bottom: 0.4rem;
}}
.header-block h1 {{
    font-size: 1.85rem;
    font-weight: 700;
    margin: 0;
    color: {C_TEXT} !important;
    letter-spacing: -0.02em;
}}
.header-block p {{
    margin: 0.5rem 0 0;
    color: {C_MUTED} !important;
    font-size: 1.02rem;
    max-width: 44rem;
    line-height: 1.5;
}}
.footer-viral {{
    color: {C_MUTED} !important;
    font-size: 0.78rem;
    margin-top: 1.5rem;
}}
.footer-viral a {{
    color: {C_ACCENT} !important;
}}

/* Markdown / prose */
.prose, .markdown, .md, [class*="prose"] {{
    color: {C_TEXT} !important;
}}
.prose h1, .prose h2, .prose h3, .prose h4,
.markdown h1, .markdown h2, .markdown h3, .markdown h4 {{
    color: {C_TEXT} !important;
}}
.prose p, .prose li, .markdown p, .markdown li {{
    color: {C_TEXT} !important;
}}
.prose strong, .markdown strong {{
    color: #ffffff !important;
}}
.prose a, .markdown a {{
    color: {C_ACCENT} !important;
}}
.prose code, .markdown code, code {{
    background: {C_CODE_BG} !important;
    color: {C_CODE_FG} !important;
    border: 1px solid {C_BORDER} !important;
    border-radius: 4px !important;
    padding: 0.1rem 0.35rem !important;
}}
.prose pre, .markdown pre, pre {{
    background: {C_CODE_BG} !important;
    color: {C_TEXT} !important;
    border: 1px solid {C_BORDER} !important;
    border-radius: 8px !important;
}}
.prose pre code, .markdown pre code, pre code {{
    background: transparent !important;
    border: none !important;
    color: {C_TEXT} !important;
}}

/* Guide markdown tables stay dark */
.prose table, .markdown table {{
    border-color: {C_BORDER} !important;
}}
.prose th, .markdown th {{
    background: {C_TABLE_HEADER} !important;
    color: {C_TABLE_TEXT} !important;
}}
.prose td, .markdown td {{
    color: {C_TABLE_TEXT} !important;
    border-color: {C_BORDER} !important;
    background: {C_TABLE_BG} !important;
}}

/* Code / inputs */
.cm-editor, .cm-content, .cm-line {{
    background: {C_CODE_BG} !important;
    color: {C_TEXT} !important;
}}
textarea, input {{
    color: {C_TEXT} !important;
}}

/*
 * CRITICAL: Gradio Dataframe + File often render white cells.
 * Global light text then becomes invisible — force dark surfaces + light text.
 */
.preview-table table,
.preview-table th,
.preview-table td,
.preview-table .table-wrap,
.preview-table [data-testid="dataframe"] table,
.preview-table [data-testid="dataframe"] th,
.preview-table [data-testid="dataframe"] td {{
    background: {C_TABLE_BG} !important;
    color: {C_TABLE_TEXT} !important;
    border-color: {C_BORDER} !important;
}}
.preview-table th {{
    background: {C_TABLE_HEADER} !important;
    font-weight: 600 !important;
}}
.preview-table tr:nth-child(even) td {{
    background: #111827 !important;
}}

.download-box,
.download-box *,
.download-box a,
.download-box span,
.download-box label,
.download-box .file-preview,
.download-box [data-testid="file"] {{
    color: {C_TABLE_TEXT} !important;
}}
.download-box .file,
.download-box .file-preview,
.download-box [data-testid="file"],
.download-box .wrap,
.download-box .or {{
    background: {C_TABLE_BG} !important;
    border: 1px solid {C_BORDER} !important;
    border-radius: 8px !important;
    color: {C_TABLE_TEXT} !important;
}}
.download-box a {{
    color: {C_ACCENT} !important;
}}

/* Fallback for unscoped Gradio dataframe/file widgets */
[data-testid="dataframe"] table,
[data-testid="dataframe"] th,
[data-testid="dataframe"] td {{
    background: {C_TABLE_BG} !important;
    color: {C_TABLE_TEXT} !important;
    border-color: {C_BORDER} !important;
}}
[data-testid="file"] .file-preview,
[data-testid="file"] .file {{
    background: {C_TABLE_BG} !important;
    color: {C_TABLE_TEXT} !important;
    border: 1px solid {C_BORDER} !important;
}}

footer {{ display: none !important; }}
"""


def build_theme():
    import gradio as gr

    return gr.themes.Base(
        primary_hue=gr.themes.colors.blue,
        neutral_hue=gr.themes.colors.slate,
        font=[gr.themes.GoogleFont("IBM Plex Sans"), "ui-sans-serif", "system-ui", "sans-serif"],
        font_mono=[gr.themes.GoogleFont("IBM Plex Mono"), "ui-monospace", "monospace"],
    ).set(
        body_background_fill=C_BG,
        body_background_fill_dark=C_BG,
        background_fill_primary=C_PANEL,
        background_fill_primary_dark=C_PANEL,
        background_fill_secondary="#0f172a",
        background_fill_secondary_dark="#0f172a",
        border_color_primary=C_BORDER,
        border_color_primary_dark=C_BORDER,
        body_text_color=C_TEXT,
        body_text_color_dark=C_TEXT,
        body_text_color_subdued=C_MUTED,
        body_text_color_subdued_dark=C_MUTED,
        block_background_fill=C_PANEL,
        block_background_fill_dark=C_PANEL,
        block_label_text_color=C_MUTED,
        block_label_text_color_dark=C_MUTED,
        block_title_text_color=C_TEXT,
        block_title_text_color_dark=C_TEXT,
        input_background_fill=C_CODE_BG,
        input_background_fill_dark=C_CODE_BG,
        input_border_color=C_BORDER,
        input_border_color_dark=C_BORDER,
        input_placeholder_color=C_MUTED,
        input_placeholder_color_dark=C_MUTED,
        button_primary_background_fill=C_ACCENT,
        button_primary_background_fill_dark=C_ACCENT,
        button_primary_text_color="#ffffff",
        button_primary_text_color_dark="#ffffff",
        button_secondary_text_color=C_TEXT,
        button_secondary_text_color_dark=C_TEXT,
        link_text_color=C_ACCENT,
        link_text_color_dark=C_ACCENT,
        code_background_fill=C_CODE_BG,
        code_background_fill_dark=C_CODE_BG,
        table_even_background_fill=C_TABLE_BG,
        table_even_background_fill_dark=C_TABLE_BG,
        table_odd_background_fill="#111827",
        table_odd_background_fill_dark="#111827",
        table_row_focus=C_TABLE_HEADER,
        table_row_focus_dark=C_TABLE_HEADER,
        table_text_color=C_TABLE_TEXT,
        table_text_color_dark=C_TABLE_TEXT,
        table_radius="8px",
    )


DARK_THEME = None
