"""Early warning: alert levels, nearest safe ground, bulletins and CAP alerts.

Turns a completed run into the thing a District Disaster Management Authority
acts on. Everything here is derived from the run's rasters and town table; the
thresholds that map hazard and lead time to an alert level are stated in
`bulletin.py` and printed on every bulletin.
"""
