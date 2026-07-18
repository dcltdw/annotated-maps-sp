<!-- doc-status: dated -->

# ADR-0003: PostGIS for geometry, stored as GeoJSON/WKB
- Status: accepted
- Date: 2026-06-09
## Context
Regions, point-in-region membership, and spatial selection need real geometry queries; later interop wants standard formats.
## Decision
Enable PostGIS from the foundation; store geometry as PostGIS types serialized via GeoJSON/WKB.
## Consequences
Spatial queries and import/export are first-class; avoids a painful geometry migration on live data.
