import { useEffect, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import MapLayersPanel from "./MapLayersPanel";
import MapSearchFilters from "./MapSearchFilters";

const CALGARY_CENTER = [-114.0719, 51.0447];
const DEFAULT_ZOOM = 11;

/**
 * Empty FeatureCollection placeholder.
 * Future 311 requests should be Point features shaped like:
 * {
 *   type: "Feature",
 *   geometry: { type: "Point", coordinates: [longitude, latitude] },
 *   properties: {
 *     id: "",
 *     serviceType: "",
 *     priorityScore: 0,
 *     community: "",
 *     status: ""
 *   }
 * }
 *
 * Future crew routes should be LineString features with a crewId
 * (and optional crewColor) in properties for per-crew styling.
 */
const EMPTY_FEATURE_COLLECTION = {
  type: "FeatureCollection",
  features: [],
};

const INITIAL_LAYERS = {
  requests: false,
  routes: false,
  highPriority: false,
  communities: false,
};

/** Map layer ids controlled by the Layers panel */
const LAYER_VISIBILITY = {
  requests: ["requests-circle"],
  routes: ["routes-line"],
  highPriority: ["requests-high-priority"],
  communities: ["communities-fill", "communities-outline"],
};

function visibility(isVisible) {
  return isVisible ? "visible" : "none";
}

function addOperationalSourcesAndLayers(map) {
  const sources = {
    requests: EMPTY_FEATURE_COLLECTION,
    routes: EMPTY_FEATURE_COLLECTION,
    communities: EMPTY_FEATURE_COLLECTION,
  };

  Object.entries(sources).forEach(([sourceId, data]) => {
    if (!map.getSource(sourceId)) {
      map.addSource(sourceId, { type: "geojson", data });
    }
  });

  // 311 request points — style by priorityScore when data is connected
  if (!map.getLayer("requests-circle")) {
    map.addLayer({
      id: "requests-circle",
      type: "circle",
      source: "requests",
      layout: { visibility: "none" },
      paint: {
        "circle-radius": 6,
        "circle-color": [
          "interpolate",
          ["linear"],
          ["coalesce", ["get", "priorityScore"], 0],
          0,
          "#9ca3af",
          50,
          "#f59e0b",
          80,
          "#c8102e",
        ],
        "circle-stroke-width": 1,
        "circle-stroke-color": "#ffffff",
      },
    });
  }

  // Optional high-priority subset of the same requests source
  if (!map.getLayer("requests-high-priority")) {
    map.addLayer({
      id: "requests-high-priority",
      type: "circle",
      source: "requests",
      layout: { visibility: "none" },
      filter: [">=", ["coalesce", ["get", "priorityScore"], 0], 80],
      paint: {
        "circle-radius": 8,
        "circle-color": "#c8102e",
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff",
      },
    });
  }

  // Crew assignment routes — LineStrings; color by crew property later
  if (!map.getLayer("routes-line")) {
    map.addLayer({
      id: "routes-line",
      type: "line",
      source: "routes",
      layout: {
        visibility: "none",
        "line-join": "round",
        "line-cap": "round",
      },
      paint: {
        "line-color": ["coalesce", ["get", "crewColor"], "#525252"],
        "line-width": 3,
        "line-opacity": 0.9,
      },
    });
  }

  // Calgary community boundaries (polygons) — empty until data is loaded
  if (!map.getLayer("communities-fill")) {
    map.addLayer({
      id: "communities-fill",
      type: "fill",
      source: "communities",
      layout: { visibility: "none" },
      paint: {
        "fill-color": "#c8102e",
        "fill-opacity": 0.06,
      },
    });
  }

  if (!map.getLayer("communities-outline")) {
    map.addLayer({
      id: "communities-outline",
      type: "line",
      source: "communities",
      layout: { visibility: "none" },
      paint: {
        "line-color": "#737373",
        "line-width": 1,
      },
    });
  }
}

function applyLayerVisibility(map, layers) {
  Object.entries(LAYER_VISIBILITY).forEach(([key, layerIds]) => {
    layerIds.forEach((layerId) => {
      if (map.getLayer(layerId)) {
        map.setLayoutProperty(layerId, "visibility", visibility(layers[key]));
      }
    });
  });
}

function CalgaryMap() {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const [tokenMissing, setTokenMissing] = useState(false);
  const [mapReady, setMapReady] = useState(false);

  const [layers, setLayers] = useState(INITIAL_LAYERS);
  const [search, setSearch] = useState("");
  const [crewFilter, setCrewFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");

  useEffect(() => {
    if (mapRef.current || !containerRef.current) return;

    const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN;
    if (!token) {
      setTokenMissing(true);
      return;
    }

    mapboxgl.accessToken = token;

    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/outdoors-v12",
      center: CALGARY_CENTER,
      zoom: DEFAULT_ZOOM,
      attributionControl: true,
    });

    // Bottom-right so it does not collide with search/filters (top-right)
    // or the Layers panel (bottom-left)
    map.addControl(
      new mapboxgl.NavigationControl({ showCompass: false }),
      "bottom-right",
    );

    map.on("load", () => {
      addOperationalSourcesAndLayers(map);
      applyLayerVisibility(map, INITIAL_LAYERS);
      setMapReady(true);
    });

    mapRef.current = map;

    const resizeObserver = new ResizeObserver(() => {
      map.resize();
    });
    resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      map.remove();
      mapRef.current = null;
      setMapReady(false);
    };
  }, []);

  // Keep Mapbox layer visibility in sync with Layers panel state
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    applyLayerVisibility(map, layers);
  }, [layers, mapReady]);

  const handleLayerChange = (id, checked) => {
    setLayers((prev) => ({ ...prev, [id]: checked }));
  };

  if (tokenMissing) {
    return (
      <div className="flex h-full w-full items-center justify-center rounded-md bg-neutral-100 px-6 text-center">
        <div>
          <p className="text-sm font-medium text-text">Mapbox token required</p>
          <p className="mt-1 text-xs text-text-muted">
            Add{" "}
            <code className="rounded-sm border border-border bg-white px-1 py-0.5">
              VITE_MAPBOX_ACCESS_TOKEN
            </code>{" "}
            to{" "}
            <code className="rounded-sm border border-border bg-white px-1 py-0.5">
              frontend/.env
            </code>{" "}
            and restart the dev server.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative h-full w-full overflow-hidden rounded-md border border-border">
      <div ref={containerRef} className="h-full w-full" />

      {/* Top-right: search + filters */}
      <div className="pointer-events-none absolute top-3 right-3 z-10">
        <MapSearchFilters
          search={search}
          onSearchChange={setSearch}
          crewFilter={crewFilter}
          onCrewFilterChange={setCrewFilter}
          priorityFilter={priorityFilter}
          onPriorityFilterChange={setPriorityFilter}
        />
      </div>

      {/* Bottom-left: layer toggles */}
      <div className="pointer-events-none absolute bottom-3 left-3 z-10">
        <MapLayersPanel layers={layers} onChange={handleLayerChange} />
      </div>
    </div>
  );
}

export default CalgaryMap;
