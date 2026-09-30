"""Sentinel-1 imaging geometry over terrain: where the radar can see the ground.

In a Himalayan valley a large share of the ground is not imaged usefully:

* **Shadow** — a slope facing away from the sensor, steeper than the radar's
  grazing complement, receives no illumination and returns almost nothing. It
  is as dark as open water, so a water threshold calls it "water".
* **Layover** — a slope facing the sensor, steeper than the incidence angle,
  folds over in range; its return is smeared onto other pixels and says
  nothing about the ground at that pixel.

Both are geometric facts of one scene, so they are masked per scene, BEFORE
any water threshold, and the fraction of the area that survives is reported
next to every result. A gorge that is 60% unimageable is shown as "mostly not
observed", never as dry.

Method (geometric part only)
----------------------------
Vollrath, A., Mullissa, A. & Reiche, J. (2020). "Angular-Based Radiometric
Slope Correction for Sentinel-1 on Google Earth Engine." *Remote Sensing*
12(11), 1867. https://doi.org/10.3390/rs12111867 — building on Small, D.
(2011). "Flattening Gamma: Radiometric Terrain Correction for SAR Imagery."
*IEEE TGRS* 49(8), 3081-3093.

Per scene:

* theta: the ellipsoid incidence angle per pixel — the scene's own `angle`
  band, not a nominal constant;
* phi_i: the azimuth pointing from the ground towards the sensor. The
  incidence angle grows away from the sensor, so the downslope direction
  (terrain aspect) of the `angle` band points at the sensor; its scene mean is
  used (Vollrath et al. 2020, sect. 2.2). This handles ascending and descending
  passes alike, with no assumed heading;
* the terrain slope s and aspect phi_s from the DEM;
* the slope in the range plane:  alpha_r = atan( tan(s) * cos(phi_i - phi_s) ),
  positive for ground tilted towards the sensor.

Then, with the local incidence angle in the range plane  lia = theta - alpha_r:

* layover where  alpha_r >= theta           (lia <= 0 degrees)
* shadow  where  alpha_r <= -(90 - theta)   (lia >= 90 degrees)

These bounds are definitions (the ground turning past normal incidence or past
grazing), not tuned thresholds, so no margin is added. The formulas were checked
against the authors' published module (github.com/ESA-PhiLab/radiometric-slope-
correction, javascript/slope_correction_module.js: `_masking`, `alpha_rRad`,
heading from `ee.Terrain.aspect(image.select('angle'))`). One deliberate
difference: the heading is averaged as a unit vector (circular mean) rather
than arithmetically, so a scene whose heading straddles north is not averaged
to south. The radiometric part of
the paper (brightness normalisation on slopes) is NOT applied here.
"""

from __future__ import annotations

import numpy as np

REFERENCE = (
    "Vollrath, Mullissa & Reiche (2020), Remote Sensing 12(11):1867, "
    "doi:10.3390/rs12111867 (geometric layover/shadow masks only; building on "
    "Small 2011, IEEE TGRS 49(8):3081-3093)"
)


# --- pure geometry (numpy), used by tests and by any local raster ----------------


def range_slope_deg(slope_deg, aspect_deg, towards_sensor_az_deg):
    """Terrain slope in the range plane, degrees; positive = tilted to the sensor."""
    s = np.radians(np.asarray(slope_deg, dtype=float))
    rel = np.radians(np.asarray(towards_sensor_az_deg, dtype=float) - np.asarray(aspect_deg, dtype=float))
    return np.degrees(np.arctan(np.tan(s) * np.cos(rel)))


def local_incidence_deg(incidence_deg, slope_deg, aspect_deg, towards_sensor_az_deg):
    """Local incidence angle in the range plane, degrees."""
    return np.asarray(incidence_deg, dtype=float) - range_slope_deg(
        slope_deg, aspect_deg, towards_sensor_az_deg
    )


def classify(incidence_deg, slope_deg, aspect_deg, towards_sensor_az_deg):
    """(valid, layover, shadow) boolean arrays."""
    lia = local_incidence_deg(incidence_deg, slope_deg, aspect_deg, towards_sensor_az_deg)
    layover = lia <= 0.0
    shadow = lia >= 90.0
    return ~(layover | shadow), layover, shadow


# --- Earth Engine ----------------------------------------------------------------


def towards_sensor_azimuth(image, region, scale_m: float = 1000.0):
    """Scene-mean azimuth from the ground towards the sensor, degrees (ee.Number).

    The aspect of the incidence-angle band; averaged as a unit vector so an
    azimuth near north (359 / 1 degrees) does not average to 180.
    """
    import ee

    aspect = ee.Terrain.aspect(image.select("angle")).multiply(np.pi / 180.0)
    vec = ee.Image.cat(aspect.sin().rename("s"), aspect.cos().rename("c"))
    m = vec.reduceRegion(ee.Reducer.mean(), region, scale_m, maxPixels=1e9, bestEffort=True)
    return ee.Number(m.get("s")).atan2(ee.Number(m.get("c"))).multiply(180.0 / np.pi)


def geometry_bands(image, dem, region):
    """Per-pixel 'valid', 'layover', 'shadow' (0/1) and 'lia' for one scene."""
    import ee

    theta = image.select("angle")
    phi_i = ee.Image.constant(towards_sensor_azimuth(image, region))
    terrain = ee.Terrain.products(dem)
    s = terrain.select("slope").multiply(np.pi / 180.0)
    phi_s = terrain.select("aspect")
    rel = phi_i.subtract(phi_s).multiply(np.pi / 180.0)
    alpha_r = s.tan().multiply(rel.cos()).atan().multiply(180.0 / np.pi)
    lia = theta.subtract(alpha_r).rename("lia")
    layover = lia.lte(0).rename("layover")
    shadow = lia.gte(90).rename("shadow")
    valid = layover.Or(shadow).Not().rename("valid")
    return ee.Image.cat(valid, layover, shadow, lia)


def mask_unimageable(image, dem, region):
    """The scene with layover and shadow pixels masked out."""
    geom = geometry_bands(image, dem, region)
    return image.updateMask(geom.select("valid"))
