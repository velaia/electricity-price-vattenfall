import matplotlib
matplotlib.use('Agg')  # Non-interactive backend, must be before pyplot/seaborn imports

from mcp.server.fastmcp import FastMCP, Image
from pathlib import Path
import os

PROJECT_DIR = Path(__file__).parent.resolve()
CHART_PATH = PROJECT_DIR / "dual_timeline_plot.png"

mcp = FastMCP("Vattenfall Electricity Prices")


@mcp.tool()
def get_price_chart() -> Image:
    """Return a chart of current German electricity spot prices (ct/kWh).

    Shows today's and tomorrow's (if available) hourly prices as a
    dual-timeline line chart. Data is fetched from the Vattenfall API
    on first call and cached locally afterwards.
    """
    os.chdir(PROJECT_DIR)
    from main import main
    main()
    return Image(path=str(CHART_PATH))


@mcp.tool()
def get_price_data() -> str:
    """Get the raw electricity price data for today (and tomorrow, if available)
    as a text table showing prices per hour in ct/kWh.

    Returns the numeric data without generating a chart.
    """
    os.chdir(PROJECT_DIR)
    from main import get_price_data as _get_price_data
    dates_data = _get_price_data()

    lines = []
    for day, prices in sorted(dates_data.items()):
        lines.append(f"\n{day}")
        lines.append(f"{'Hour':>6}  {'Price (ct/kWh)':>14}")
        lines.append("-" * 22)
        # Keys are HHMM-style: "0","15","30","45","100","115",...,"2345"
        # Group by hour and average the 15-min intervals
        hourly = {}
        for key, price in prices.items():
            hour = int(key) // 100
            hourly.setdefault(hour, []).append(price)
        for hour in sorted(hourly):
            avg = sum(hourly[hour]) / len(hourly[hour])
            lines.append(f"{hour:>4}:00  {avg:>14.2f}")

    return "\n".join(lines)



if __name__ == "__main__":
    import sys
    if "--stdio" in sys.argv:
        mcp.run(transport="stdio")
    else:
        mcp.run(transport="streamable-http")
