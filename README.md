# Strom Börsenpreis

Get current German electricity prices from [Vattenfall Börsenpreise](https://www.vattenfall.de/strom/tarife/oekostrom-dynamik-boersenpreise) and create a diagram with today's and 
tomorrow's prices (if available). Tomorrow's prices are published between noon and 3 PM each day and are not visible in
the web UI of Vattenfall. But the API provides them, so they will appear in this app.

![Sample diagram](static/dual_timeline_plot.png)
*Sample diagram output of the program*

## Usage

This assumes you have [Astral uv](https://github.com/astral-sh/uv) installed.

After cloning the repository (e.g. `git clone --depth 1 https://github.com/velaia/electricity-price-vattenfall.git`),
simply run the following command:
```commandline
uv run main.py
```
This creates a virtual environment with all the required dependencies and gets the latest (predicted) electricity prices
from the Vattenfall homepage. It also updates the `dual_timeline_plot.png` diagram.

## Docker

You can build a Docker image by running
```commandline
doker build -t vattenfall-prices-germany:0.1 .
```

## TODO

* [x] Add functionality to get davis-token (required)
* [x] Add today and tomorrow labels
* [x] Add Dockerfile
* [x] Update usage
* [ ] Idea: Gradio app that can run in HF Spaces?
* [ ] package?