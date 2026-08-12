import matplotlib
matplotlib.use('Agg')  # Non-interactive backend, must be before pyplot/seaborn imports

from pathlib import Path
import os

from mcp.server import MCPServer
from mcp.server.mcpserver import Image
from mcp.types import CallToolResult, TextContent

PROJECT_DIR = Path(__file__).parent.resolve()
CHART_PATH = PROJECT_DIR / "dual_timeline_plot.png"
CHART_PATH_FUTURISTIC = PROJECT_DIR / "dual_timeline_plot_futuristic.png"

mcp = MCPServer("Vattenfall Electricity Prices")


@mcp.tool()
def get_price_chart(futuristic: bool = False) -> Image:
    """Return a chart of current German electricity spot prices (ct/kWh).

    Shows today's and tomorrow's (if available) hourly prices as a
    dual-timeline line chart. Data is fetched from the Vattenfall API
    on first call and cached locally afterwards.

    Args:
        futuristic: When True, render the synthwave/retro-future variant
            instead of the classic chart.

    The Image return is serialized to ImageContent; the SDK stamps the
    result with `resultType: "complete"` (2026-07-28).
    """
    os.chdir(PROJECT_DIR)
    from main import main
    # Pass argv explicitly so main()'s argparse ignores the process args
    # (e.g. --stdio) that this stdio server was launched with.
    main(argv=["-f"] if futuristic else [])
    return Image(path=str(CHART_PATH_FUTURISTIC if futuristic else CHART_PATH))


@mcp.tool()
def get_price_data() -> CallToolResult:
    """Get the raw electricity price data for today (and tomorrow, if available)
    as a text table showing prices per hour in ct/kWh.

    Returns a 2026-07-28 result carrying `resultType: "complete"`: the
    human-readable hourly table in `content` and the same numbers as JSON
    in `structuredContent` for clients that want typed data.
    """
    os.chdir(PROJECT_DIR)
    from main import get_price_data as _get_price_data
    dates_data = _get_price_data()

    # Keys are HHMM-style: "0","15","30","45","100","115",...,"2345"
    # Group by hour and average the 15-min intervals. The same hourly
    # breakdown feeds both the human table and the structured payload.
    structured = {}
    lines = []
    for day, prices in sorted(dates_data.items()):
        hourly = {}
        for key, price in prices.items():
            hour = int(key) // 100
            hourly.setdefault(hour, []).append(price)
        hourly_avg = {hour: sum(v) / len(v) for hour, v in sorted(hourly.items())}

        structured[day] = {f"{hour:02d}:00": round(avg, 2) for hour, avg in hourly_avg.items()}

        lines.append(f"\n{day}")
        lines.append(f"{'Hour':>6}  {'Price (ct/kWh)':>14}")
        lines.append("-" * 22)
        for hour, avg in hourly_avg.items():
            lines.append(f"{hour:>4}:00  {avg:>14.2f}")

    return CallToolResult(
        result_type="complete",
        content=[TextContent(type="text", text="\n".join(lines))],
        structured_content=structured,
    )



if __name__ == "__main__":
    import sys
    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")
