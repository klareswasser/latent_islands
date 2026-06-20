#!/usr/bin/env python3
"""Build river-separated land components across Japan from MLIT N03 and W05."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import make_valid
from shapely.geometry import mapping
from shapely.ops import unary_union
from shapely.prepared import prep
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parent
N03_DIR = ROOT / "data/extracted/N03"
W05_DIR = ROOT / "data/extracted/W05"
OUT_DIR = ROOT / "data/processed"
PROJECTED_CRS = "EPSG:6933"  # WGS 84 / NSIDC EASE-Grid 2.0 Global (equal-area metres)
WEB_CRS = "EPSG:4326"

# W05_003: 1=first-class direct, 2=first-class designated, 3=second-class.
# W05 has centerlines, not river-width polygons. These half-widths are analytical
# parameters, chosen to bridge small digitising gaps without dominating the map.
HALF_WIDTH_M = {"1": 45.0, "2": 30.0, "3": 18.0}
MIN_AREA_KM2 = 0.02
NEIGHBOR_DISTANCE_M = 500.0


def read_inputs() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    admin_paths = sorted(N03_DIR.glob("N03-20250101_[0-9][0-9].shp"))
    admin_parts = [gpd.read_file(path) for path in admin_paths]
    if len(admin_parts) != 47:
        raise RuntimeError(f"Expected 47 N03 shapefiles, found {len(admin_parts)}")
    admin = gpd.GeoDataFrame(pd.concat(admin_parts, ignore_index=True), crs=admin_parts[0].crs)
    admin = admin.to_crs(PROJECTED_CRS)

    stream_parts = []
    for path in sorted(W05_DIR.rglob("*Stream.shp")):
        frame = gpd.read_file(path, on_invalid="ignore")
        frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
        # W05 shapefiles do not include a .prj. The product uses JGD2000 lat/lon.
        frame = frame.set_crs("EPSG:4612", allow_override=True).to_crs(PROJECTED_CRS)
        stream_parts.append(frame)
    if len(stream_parts) != 47:
        raise RuntimeError(f"Expected 47 W05 stream shapefiles, found {len(stream_parts)}")
    streams = gpd.GeoDataFrame(pd.concat(stream_parts, ignore_index=True), crs=PROJECTED_CRS)
    streams = streams[streams["W05_003"].astype(str).isin(HALF_WIDTH_M)].copy()

    return admin, streams


def polygon_parts(geometry) -> list:
    """Return all polygon members from Polygon/MultiPolygon/collections."""
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    if hasattr(geometry, "geoms"):
        result = []
        for child in geometry.geoms:
            result.extend(polygon_parts(child))
        return result
    return []


def greedy_colors(geometries: list, distance: float) -> list[int]:
    """Color near-neighbor polygons; returns stable zero-based color indexes."""
    expanded = [geom.buffer(distance) for geom in geometries]
    tree = STRtree(expanded)
    neighbors = [set() for _ in geometries]
    for i, geom in enumerate(expanded):
        for j in tree.query(geom, predicate="intersects"):
            j = int(j)
            if i != j:
                neighbors[i].add(j)

    colors = [-1] * len(geometries)
    order = sorted(range(len(geometries)), key=lambda i: (-len(neighbors[i]), i))
    for i in order:
        used = {colors[j] for j in neighbors[i] if colors[j] >= 0}
        color = 0
        while color in used:
            color += 1
        colors[i] = color
    return colors


def feature_collection(frame: gpd.GeoDataFrame) -> dict:
    features = []
    property_cols = [c for c in frame.columns if c != "geometry"]
    for _, row in frame.iterrows():
        props = {}
        for col in property_cols:
            value = row[col]
            if isinstance(value, np.generic):
                value = value.item()
            if pd.isna(value):
                value = None
            props[col] = value
        features.append({"type": "Feature", "properties": props, "geometry": mapping(row.geometry)})
    return {"type": "FeatureCollection", "features": features}


def write_geojson(frame: gpd.GeoDataFrame, path: Path) -> None:
    path.write_text(json.dumps(feature_collection(frame), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def build(min_area_km2: float, neighbor_distance_m: float) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    admin, streams = read_inputs()

    print(f"N03 polygons: {len(admin):,}; W05 selected segments: {len(streams):,}")
    japan_land = make_valid(unary_union(admin.geometry))
    original_land_parts = polygon_parts(japan_land)

    buffers = []
    for category, width in HALF_WIDTH_M.items():
        lines = streams.loc[streams["W05_003"].astype(str) == category, "geometry"]
        if not lines.empty:
            buffers.append(unary_union(lines).buffer(width, cap_style="square", join_style="round"))
    water_cut = make_valid(unary_union(buffers)).intersection(japan_land)

    # Process each pre-existing sea-separated landmass independently. Its largest
    # post-cut fragment remains the original mainland/island; only additional
    # fragments created by the rivers are analytical "islands". Thus natural
    # islands themselves never enter the result, while river islands on them can.
    prepared_water = prep(water_cut)
    islands = []
    cut_parent_count = 0
    fragment_count = 0
    for parent in original_land_parts:
        if not prepared_water.intersects(parent):
            continue
        fragments = polygon_parts(make_valid(parent.difference(water_cut)))
        if len(fragments) <= 1:
            continue
        cut_parent_count += 1
        fragment_count += len(fragments)
        base = max(fragments, key=lambda geom: geom.area)
        islands.extend(
            geom for geom in fragments
            if geom is not base and geom.area / 1_000_000 >= min_area_km2
        )
    islands.sort(key=lambda geom: geom.area, reverse=True)
    print(
        f"Natural landmasses: {len(original_land_parts):,}; "
        f"river-cut parents: {cut_parent_count:,}; displayed islands: {len(islands):,}"
    )

    island_frame = gpd.GeoDataFrame({"geometry": islands}, crs=PROJECTED_CRS)
    island_frame["island_id"] = [f"JP-{i:04d}" for i in range(1, len(island_frame) + 1)]
    island_frame["area_km2"] = (island_frame.area / 1_000_000).round(3)
    island_frame["perimeter_km"] = (island_frame.length / 1_000).round(2)

    # Representative points assign a readable place label without expensive overlays.
    reps = island_frame.copy()
    reps.geometry = reps.representative_point()
    place = gpd.sjoin(reps, admin[["N03_001", "N03_004", "geometry"]], predicate="within", how="left")
    place = place[~place.index.duplicated(keep="first")].reindex(island_frame.index)
    island_frame["prefecture"] = place["N03_001"].fillna("").values
    island_frame["municipality"] = place["N03_004"].fillna("").values

    # Attach up to three named river boundaries near each component.
    named = streams[streams["W05_004"].notna() & (streams["W05_004"] != "名称不明")][["W05_004", "geometry"]]
    river_index = named.sindex
    river_names = []
    for geom in islands:
        candidates = list(river_index.query(geom.buffer(65), predicate="intersects"))
        names = sorted(set(named.iloc[candidates]["W05_004"].astype(str)))[:3]
        river_names.append("・".join(names))
    island_frame["rivers"] = river_names
    island_frame["color"] = greedy_colors(islands, neighbor_distance_m)

    # Simplify only the browser payload; preserve topology and keep analysis metrics exact.
    web_islands = island_frame.to_crs(WEB_CRS)
    web_islands.geometry = web_islands.to_crs(PROJECTED_CRS).simplify(20, preserve_topology=True).to_crs(WEB_CRS)
    write_geojson(web_islands, OUT_DIR / "islands.geojson")

    # A lightweight national context is sufficient; sub-km² natural islands are
    # neither analytical results nor useful at the initial national zoom.
    context_parts = [geom for geom in original_land_parts if geom.area >= 500_000]
    context = gpd.GeoDataFrame(
        {"kind": ["mainland"] * len(context_parts), "geometry": context_parts},
        crs=PROJECTED_CRS,
    ).to_crs(WEB_CRS)
    context.geometry = context.to_crs(PROJECTED_CRS).simplify(250, preserve_topology=True).to_crs(WEB_CRS)
    write_geojson(context, OUT_DIR / "context.geojson")

    # Display only rivers near a result. All selected W05 segments remain part of
    # the analysis, but rendering the entire national river network is unnecessary.
    island_zones = gpd.GeoSeries(islands, crs=PROJECTED_CRS).buffer(700)
    river_pairs = named.sindex.query(island_zones, predicate="intersects")
    nearby_river_indexes = np.unique(river_pairs[1]) if river_pairs.size else []
    named_web = named.iloc[nearby_river_indexes].copy()
    named_web.geometry = named_web.geometry.simplify(100, preserve_topology=True)
    named_web = named_web.to_crs(WEB_CRS)
    named_web = named_web.rename(columns={"W05_004": "name"})
    write_geojson(named_web, OUT_DIR / "rivers.geojson")

    summary = {
        "n03_polygons": int(len(admin)),
        "w05_segments": int(len(streams)),
        "natural_landmass_count": int(len(original_land_parts)),
        "river_cut_parent_count": int(cut_parent_count),
        "post_cut_fragment_count": int(fragment_count),
        "island_count": int(len(islands)),
        "island_area_km2": round(float(island_frame.area.sum() / 1_000_000), 2),
        "min_area_km2": min_area_km2,
        "neighbor_distance_m": neighbor_distance_m,
        "half_width_m": HALF_WIDTH_M,
        "largest": island_frame.head(10).drop(columns="geometry").to_dict("records"),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-area-km2", type=float, default=MIN_AREA_KM2)
    parser.add_argument("--neighbor-distance-m", type=float, default=NEIGHBOR_DISTANCE_M)
    args = parser.parse_args()
    build(args.min_area_km2, args.neighbor_distance_m)
