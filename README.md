# Lightning Radar

> Real-time lightning strike map and storm tracker built with Python + React.

Connects to the [Blitzortung](https://www.blitzortung.org/) open sensor network
to stream live strike data worldwide, clusters strikes into storm cells, and
shows movement vectors and estimated arrival times for approaching storms.

**Status:** early development.

## Prerequisites

- [Miniconda](https://docs.conda.io/en/latest/miniconda.html) / Anaconda
- Internet access (live feed from Blitzortung)

## Quick start

```bash
conda env create -f environment.yml
conda activate lightning-radar
```

## Attribution

Lightning data provided by [Blitzortung.org](https://www.blitzortung.org/) and its contributors.
This is a personal, non-commercial project with no affiliation to the Blitzortung network.

## License

MIT
