# Isogonic Lines & MagVar

QGIS plugin for **magnetic variation (declination)** and **isogonic lines**. Fully offline.

Use it for aeronautical charts (Annex 4 style labels), nautical charts and compass roses, topographic map declination diagrams, surveying and drone work, hiking, orienteering and land navigation, or geomagnetic studies.

## Features
- **Layer tab:** pick a point, line or polygon layer and a date. A new layer is written with `decl_deg` (decimal degrees, east positive), `decl_label` (nearest degree, e.g. `5°E`, as Annex 4 charts show it), `ann_change` (degrees per year) and `decl_date`. The source layer is never modified. Lines can use the centroid, first or last vertex.
- **Click tool tab:** click anywhere on the map and a result card shows the declination (large, with a true-scale compass), annual change (°/year), inclination, total field, the declination trend over 10 years and the position in degrees, minutes and seconds (0.001") plus decimal degrees. **Live mode** makes the card follow the cursor; a click pins it, and Esc or the close button returns to the plugin window. A button copies the values.
- **Isogonic lines tab:** choose an extent, date, interval (any value from 0.01° to 10°, for example 0.25°, 2.5° or 1°) and grid spacing (automatic by default). If no line at your interval crosses a small extent, the plugin retries with a finer interval and says so. Labels show decimals when the interval needs them (2.5°E, 0.25°W). The plugin draws lines of equal declination, labelled `5°E` / `3°W`. The zero line (agonic line) has its own style.

## Models and "my lines do not fit"
Choose the model: WMM2025, **WMMHR2025 (high resolution, adds the crustal field, degrees up to 133; NOAA/NGA recommend it where the extra detail matters)**, WMM2020, WMM2015v2, WMM2010 (NOAA) or IGRF-14 (IAGA, any date 1900-2030), or leave it on automatic. Isogonic lines supplied by a client or an old chart often come from another model or year, so they do not match today's WMM2025 (a 5-year difference is already 0.3-0.8° in West Africa). The **Compare with my lines** tab takes the client's line layer and the field with each line's declination (numbers like -2.5 or text like 2°30'W), tests every model and date, and shows which one reproduces the lines (RMS and offset, per line). One click applies the best match. Layers made by the plugin carry a `decl_model` field.

## Model
World Magnetic Model **WMM2025** (NOAA/NCEI, public domain), valid 2025.0 to 2030.0; older WMM editions and IGRF-14 coefficients are bundled (IGRF: International Association of Geomagnetism and Aeronomy, linear interpolation between 5-year epochs). WMM2025 and WMMHR2025 give exactly the same values as NOAA's official Python packages (differences 0.00000°). WMMHR is slower (about 1.7 s per 10,000 points) so isogonic grids are limited to 1 million cells with it. Automatic keeps the standard WMM. All models were checked against independent software (pygeomag, ppigrf: differences below 0.001°). The WMM2025 implementation is checked against all 12 official NOAA WMM2025 test values (field components within 0.05 nT, declination and inclination within the rounding of the published values; annual change matches the published rates). Dates outside 2025-2030 give a warning and are extrapolated.

## Limits
- WMM is a global model: typical declination error is about 0.5°, larger near the magnetic poles. Declination is not defined at the geographic poles (latitude is limited to ±89.99°).
- For official use, verify values against the authority's data (for aviation, the AIP).
- Not affiliated with ICAO or NOAA.

## Install
Plugins → Manage and Install Plugins → search "Isogonic Lines & MagVar", or install from ZIP.

License: GPL-2.0-or-later. Author: Riadh Elmokh.
