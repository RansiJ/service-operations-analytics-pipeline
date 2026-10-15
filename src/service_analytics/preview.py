"""Static analytical preview; this is not a Power BI report."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter


def create_preview(con, path, report):
    metrics = report["metrics"]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(2, 2, figsize=(15, 10), facecolor="#f6f8fc")
    fig.suptitle("NYC 311 | Service Operations", fontsize=24, fontweight="bold", x=0.06, ha="left")
    median = metrics["median_resolution_hours"]
    median_text = f"{median:.2f}h" if median is not None else "N/A"
    fig.text(0.06, 0.905,
             f"{metrics['total_requests']:,} requests   |   {metrics['open_requests']:,} open   |   "
             f"{metrics['closed_requests']:,} closed   |   {median_text} median resolution", fontsize=14)
    fig.text(0.06, 0.87,
             f"Created: {report['window_start']} to {report['window_end_exclusive']} (end exclusive)   |   "
             f"Observed (UTC): {report['observed_at'][:10]}   |   {metrics['flagged_requests']:,} quality-flagged", color="#526078")
    daily = con.execute("SELECT created_day, total_requests FROM daily_metrics ORDER BY created_day").fetchall()
    if daily:
        axes[0, 0].plot(range(len(daily)), [r[1] for r in daily], color="#205bc7", marker="o")
        axes[0, 0].set_xticks(range(len(daily)), [str(r[0])[5:] for r in daily])
    axes[0, 0].set_title("Daily request volume", loc="left", fontweight="bold")
    axes[0, 0].tick_params(axis="x", rotation=40)
    for ax, table, label, color in (
        (axes[0, 1], "category_metrics", "category", "#0e8b83"),
        (axes[1, 0], "agency_metrics", "agency", "#205bc7"),
    ):
        rows = con.execute(f"SELECT {label}, total_requests FROM {table} ORDER BY total_requests DESC, {label} LIMIT 7").fetchall()[::-1]
        ax.barh([r[0][:33] for r in rows], [r[1] for r in rows], color=color)
        ax.set_title(f"Top {label.title()} demand", loc="left", fontweight="bold")
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x, _: f"{x:,.0f}"))
    hours = [r[0] for r in con.execute("SELECT resolution_hours FROM requests WHERE resolution_hours IS NOT NULL").fetchall()]
    if hours:
        axes[1, 1].hist(hours, bins=35, color="#7455bd")
    axes[1, 1].set_title("Resolution time | eligible closed requests", loc="left", fontweight="bold")
    axes[1, 1].set_xlabel("Hours (full range, including zero)")
    axes[1, 1].set_ylabel("Requests")
    fig.text(0.06, 0.025, "Source: NYC Open Data 311. Creation cohort; open count is not citywide backlog. No SLA or causal claim.\n"
             "Closure times reflect observed closed cases; unresolved cases are excluded from duration statistics.", fontsize=9, color="#526078")
    fig.subplots_adjust(left=0.18, right=0.97, top=0.81, bottom=0.13, hspace=0.45, wspace=0.55)
    fig.savefig(path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
