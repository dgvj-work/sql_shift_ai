"""Interactive lineage graph visualization."""

from __future__ import annotations

import networkx as nx
import plotly.graph_objects as go

from sqlshift.models import Dialect, MigrationObject

C_PANEL = "#1a2332"
C_TEXT = "#e2e8f0"
C_MUTED = "#94a3b8"
C_BORDER = "#2d3a4f"


def lineage_to_plotly(
    graph: nx.DiGraph,
    objects: list[MigrationObject] | None = None,
) -> go.Figure:
    """Render dependency graph as interactive Plotly network."""
    if graph.number_of_nodes() == 0:
        return _empty_graph("No lineage data — run a repository scan first.")

    # Use spring layout for positioning
    try:
        pos = nx.spring_layout(graph, k=1.8, iterations=50, seed=42)
    except nx.NetworkXError:
        return _empty_graph("Could not layout lineage graph.")

    obj_names = {o.name for o in (objects or [])}

    edge_x, edge_y = [], []
    for u, v in graph.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        mode="lines",
        line=dict(width=1.2, color="#475569"),
        hoverinfo="none",
        showlegend=False,
    )

    node_x, node_y, node_text, node_color, node_size = [], [], [], [], []
    for node in graph.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)
        node_text.append(node)
        obj_type = graph.nodes[node].get("object_type", "table")
        if node in obj_names:
            node_color.append("#3b82f6")
            node_size.append(14)
        elif obj_type in ("stored_procedure", "sql_script", "view"):
            node_color.append("#8b5cf6")
            node_size.append(12)
        else:
            node_color.append("#64748b")
            node_size.append(10)

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers+text",
        text=node_text,
        textposition="top center",
        textfont=dict(size=9, color=C_TEXT),
        marker=dict(
            size=node_size,
            color=node_color,
            line=dict(width=1, color=C_BORDER),
        ),
        hovertemplate="%{text}<extra></extra>",
        showlegend=False,
    )

    fig = go.Figure(data=[edge_trace, node_trace])
    fig.update_layout(
        title=dict(text="Dependency lineage", font=dict(size=13, color=C_MUTED)),
        showlegend=False,
        hovermode="closest",
        height=420,
        paper_bgcolor=C_PANEL,
        plot_bgcolor=C_PANEL,
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        margin=dict(t=40, b=20, l=20, r=20),
        font=dict(family="Inter, system-ui, sans-serif", color=C_TEXT),
    )
    return fig


def _empty_graph(message: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        height=420,
        paper_bgcolor=C_PANEL,
        plot_bgcolor=C_PANEL,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text=message,
                xref="paper",
                yref="paper",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=13, color=C_MUTED),
            )
        ],
    )
    return fig
