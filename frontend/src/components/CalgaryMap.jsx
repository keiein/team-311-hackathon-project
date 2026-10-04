import { useEffect, useMemo, useRef, useState } from "react";
import mapboxgl from "mapbox-gl";
import MapLayersPanel from "./MapLayersPanel";
import MapSearchFilters from "./MapSearchFilters";
import CrewLegend from "./CrewLegend";
import CommunityLegend from "./CommunityLegend";
import DisruptionControls from "./DisruptionControls";
import { loadRequestsCollection } from "../data/loadRequests";
import { useSimulation } from "../simulation/SimulationContext";
import { buildTodaysJobsGeoJSON, crewLegendFromDispatch } from "../simulation/buildTodaysJobsGeoJSON.js";
import { mapboxCrewColorExpression } from "../simulation/crewColors.js";
import {
  buildCommunitySummaries,
  communityLegendFromSummaries,
  enrichCommunitiesGeoJSON,
} from "../simulation/buildCommunitySummaries.js";
import { normalizeCommunityName } from "../simulation/communityColors.js";

const CALGARY_CENTER = [-114.0719, 51.0447];
const DEFAULT_ZOOM = 11;

const EMPTY_FEATURE_COLLECTION = {
  type: "FeatureCollection",
  features: [],
};

const INITIAL_LAYERS = {
  requests: true,
  todaysJobs: false,
  highPriority: false,
  communities: false,
};

/**
 * Layer visibility + intended draw order (base → top):
 * communities fill/outline → 311 requests → today's jobs
 */
const LAYER_VISIBILITY = {
  communities: ["communities-fill", "communities-outline"],
  requests: ["requests-circle"],
  highPriority: ["requests-high-priority"],
  todaysJobs: ["todays-jobs-circle", "todays-jobs-label"],
};

function visibility(isVisible) {
  return isVisible ? "visible" : "none";
}

const dataUrl = (file) => `${import.meta.env.BASE_URL}data/${file}`;
const PRIORITY_BANDS = ["High", "Medium", "Low"];

function esc(value) {
  return String(value ?? "-").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function requestPopup(p) {
  return `<div style="font-size:12px;line-height:1.45;max-width:240px">
    <strong>${esc(p.serviceType)}</strong><br/>
    Priority <strong>${esc(p.priorityScore)}</strong> (${esc(p.priorityBand)}), ${esc(p.severityName)}<br/>
    ${esc(p.community)} &middot; waiting ${esc(p.daysWaiting)} days${p.overdue ? " &middot; overdue" : ""}<br/>
    <span style="color:#525252">#${esc(p.id)} &middot; ${esc(p.crew)} crew</span></div>`;
}

function todaysJobPopup(p) {
  const color = p.crewColor || "#525252";
  return `<div style="font-size:12px;line-height:1.45;max-width:260px">
    <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
      <span style="display:inline-block;width:10px;height:10px;border-radius:999px;background:${esc(color)};border:1px solid #fff;box-shadow:0 0 0 1px #d4d4d4"></span>
      <strong>Ticket #${esc(p.service_request_id || p.id)}</strong>
    </div>
    ${esc(p.service_name || p.serviceType)}<br/>
    ${esc(p.community)}<br/><br/>
    Priority: <strong>${esc(p.priority ?? p.priorityScore)}</strong><br/>
    Rank: #${esc(p.priority_rank ?? p.priorityRank)}<br/><br/>
    <strong>${esc(p.crew)}</strong><br/>
    Stop ${esc(p.stop_number ?? p.stopNumber)} of ${esc(p.stopTotal)}
  </div>`;
}

function communityTodayPopup(polygonProps, summary, crewFilter) {
  const name = polygonProps.name || "Community";
  if (!summary || summary.totalJobs === 0) {
    return `<div style="font-size:12px;line-height:1.45;max-width:280px">
      <strong>${esc(name)}</strong><br/><br/>
      No jobs scheduled here today.
    </div>`;
  }

  const crewRows = summary.jobsByCrew
    .map((row) => {
      const filteredNote =
        crewFilter !== "all" && row.crew === crewFilter
          ? ' <span style="color:#525252">(filtered)</span>'
          : "";
      return `<div style="display:flex;align-items:center;gap:6px;margin-top:3px">
        <span style="display:inline-block;width:10px;height:10px;border-radius:999px;background:${esc(row.color)};border:1px solid #fff;box-shadow:0 0 0 1px #d4d4d4"></span>
        <span>${esc(row.crew)} — ${esc(row.jobs)} job${row.jobs === 1 ? "" : "s"}${filteredNote}</span>
      </div>`;
    })
    .join("");

  let filterLine = "";
  if (crewFilter && crewFilter !== "all") {
    const filteredJobs = summary.jobsByCrew.find((r) => r.crew === crewFilter)?.jobs ?? 0;
    filterLine = `<div style="margin-top:6px;color:#525252">${esc(crewFilter)}: ${esc(filteredJobs)} of those jobs <em>(map filter only)</em></div>`;
  }

  let highest = "";
  if (summary.highestPriority) {
    const hp = summary.highestPriority;
    highest = `<div style="margin-top:8px;padding-top:6px;border-top:1px solid #e5e5e5">
      Highest-priority job:<br/>
      Ticket #${esc(hp.id)}<br/>
      ${esc(hp.serviceType)}<br/>
      Priority rank #${esc(hp.priorityRank)}
    </div>`;
  }

  return `<div style="font-size:12px;line-height:1.45;max-width:280px">
    <strong>${esc(name)}</strong><br/><br/>
    Today's jobs: <strong>${esc(summary.totalJobs)}</strong><br/>
    Active crews: <strong>${esc(summary.activeCrews)}</strong>
    ${filterLine}
    <div style="margin-top:8px">${crewRows}</div>
    ${highest}
  </div>`;
}

const CLICKABLE_LAYERS = [
  "todays-jobs-circle",
  "requests-high-priority",
  "requests-circle",
  "communities-fill",
];

function addOperationalSourcesAndLayers(map) {
  if (!map.getSource("communities")) {
    map.addSource("communities", {
      type: "geojson",
      data: EMPTY_FEATURE_COLLECTION,
      promoteId: "code",
    });
  }
  if (!map.getSource("requests")) {
    map.addSource("requests", { type: "geojson", data: EMPTY_FEATURE_COLLECTION });
  }
  if (!map.getSource("todaysJobs")) {
    map.addSource("todaysJobs", { type: "geojson", data: EMPTY_FEATURE_COLLECTION });
  }

  // 1) Community polygons UNDER everything else
  if (!map.getLayer("communities-fill")) {
    map.addLayer({
      id: "communities-fill",
      type: "fill",
      source: "communities",
      layout: { visibility: "none" },
      paint: {
        "fill-color": ["coalesce", ["get", "communityColor"], "#d4d4d4"],
        "fill-opacity": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          0.34,
          0.14,
        ],
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
        "line-color": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          "#171717",
          "#737373",
        ],
        "line-width": [
          "case",
          ["boolean", ["feature-state", "selected"], false],
          2.5,
          0.8,
        ],
        "line-opacity": 0.95,
      },
    });
  }

  // 2) 311 request points — priority coloring (unchanged meaning)
  if (!map.getLayer("requests-circle")) {
    map.addLayer({
      id: "requests-circle",
      type: "circle",
      source: "requests",
      layout: { visibility: "none", "circle-sort-key": ["coalesce", ["get", "priorityScore"], 0] },
      paint: {
        "circle-radius": 6,
        "circle-color": [
          "step",
          ["coalesce", ["get", "priorityScore"], 0],
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

  // 3) Today's Jobs — crew colors ON TOP
  if (!map.getLayer("todays-jobs-circle")) {
    map.addLayer({
      id: "todays-jobs-circle",
      type: "circle",
      source: "todaysJobs",
      layout: {
        visibility: "none",
        "circle-sort-key": ["coalesce", ["get", "crewNumber"], 0],
      },
      paint: {
        "circle-radius": 7,
        "circle-color": mapboxCrewColorExpression("crewNumber"),
        "circle-stroke-width": 1.5,
        "circle-stroke-color": "#ffffff",
        "circle-opacity": 0.95,
      },
    });
  }

  if (!map.getLayer("todays-jobs-label")) {
    map.addLayer({
      id: "todays-jobs-label",
      type: "symbol",
      source: "todaysJobs",
      layout: {
        visibility: "none",
        "text-field": ["to-string", ["get", "crewNumber"]],
        "text-size": 10,
        "text-font": ["Open Sans Bold", "Arial Unicode MS Bold"],
        "text-allow-overlap": true,
        "text-ignore-placement": true,
      },
      paint: {
        "text-color": "#ffffff",
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
  const selectedCommunityRef = useRef(null);
  const interactionRef = useRef({ summaries: new Map(), crewFilter: "all" });

  const [tokenMissing, setTokenMissing] = useState(false);
  const [mapReady, setMapReady] = useState(false);

  const [layers, setLayers] = useState(INITIAL_LAYERS);
  const [search, setSearch] = useState("");
  const [crewFilter, setCrewFilter] = useState("all");
  const [priorityFilter, setPriorityFilter] = useState("all");
  const [data, setData] = useState(null);
  const [selectedCommunityKey, setSelectedCommunityKey] = useState(null);

  const { status: simStatus, dispatch } = useSimulation();

  useEffect(() => {
    let active = true;
    Promise.all([
      loadRequestsCollection(),
      fetch(dataUrl("communities.geojson")).then((r) => (r.ok ? r.json() : EMPTY_FEATURE_COLLECTION)),
    ])
      .then(([requests, communities]) => active && setData({ requests, communities }))
      .catch(() => active && setData({ requests: EMPTY_FEATURE_COLLECTION, communities: EMPTY_FEATURE_COLLECTION }));
    return () => {
      active = false;
    };
  }, []);

  const communitySummaries = useMemo(() => {
    if (!data?.requests || !dispatch) return new Map();
    return buildCommunitySummaries(dispatch, data.requests);
  }, [data, dispatch]);

  const communityLegend = useMemo(
    () => communityLegendFromSummaries(communitySummaries),
    [communitySummaries],
  );

  const communitiesStyled = useMemo(() => {
    if (!data?.communities) return EMPTY_FEATURE_COLLECTION;
    return enrichCommunitiesGeoJSON(data.communities, communitySummaries);
  }, [data, communitySummaries]);

  const todaysJobsAll = useMemo(() => {
    if (!data?.requests || !dispatch) return EMPTY_FEATURE_COLLECTION;
    return buildTodaysJobsGeoJSON(dispatch, data.requests);
  }, [data, dispatch]);

  const crewLegend = useMemo(() => crewLegendFromDispatch(dispatch), [dispatch]);

  interactionRef.current = { summaries: communitySummaries, crewFilter };

  const crewOptions = useMemo(() => {
    if (layers.todaysJobs && crewLegend.length) {
      return crewLegend.map((row) => row.crew);
    }
    if (!data) return [];
    return [...new Set(data.requests.features.map((f) => f.properties.crew))].filter(Boolean).sort();
  }, [layers.todaysJobs, crewLegend, data]);

  useEffect(() => {
    if (crewFilter === "all") return;
    if (!crewOptions.includes(crewFilter)) setCrewFilter("all");
  }, [crewOptions, crewFilter]);

  const assignedIdsForCrew = useMemo(() => {
    if (!dispatch?.morning || crewFilter === "all" || !layers.todaysJobs) return null;
    return new Set(
      dispatch.morning.filter((row) => row.crew === crewFilter).map((row) => String(row.id)),
    );
  }, [dispatch, crewFilter, layers.todaysJobs]);

  const filteredRequests = useMemo(() => {
    if (!data) return EMPTY_FEATURE_COLLECTION;
    const needle = search.trim().toLowerCase();
    const features = data.requests.features.filter((f) => {
      const p = f.properties;
      if (priorityFilter !== "all" && p.priorityBand !== priorityFilter) return false;
      if (layers.todaysJobs && assignedIdsForCrew) {
        if (!assignedIdsForCrew.has(String(p.id))) return false;
      } else if (!layers.todaysJobs && crewFilter !== "all" && p.crew !== crewFilter) {
        return false;
      }
      if (!needle) return true;
      return [p.id, p.serviceType, p.community].some((v) => String(v ?? "").toLowerCase().includes(needle));
    });
    return { type: "FeatureCollection", features };
  }, [data, search, crewFilter, priorityFilter, layers.todaysJobs, assignedIdsForCrew]);

  const filteredTodaysJobs = useMemo(() => {
    if (!todaysJobsAll.features.length) return EMPTY_FEATURE_COLLECTION;
    const needle = search.trim().toLowerCase();
    const features = todaysJobsAll.features.filter((f) => {
      const p = f.properties;
      if (crewFilter !== "all" && p.crew !== crewFilter) return false;
      if (priorityFilter !== "all" && p.priorityBand !== priorityFilter) return false;
      if (!needle) return true;
      return [p.id, p.serviceType, p.service_name, p.community].some((v) =>
        String(v ?? "").toLowerCase().includes(needle),
      );
    });
    return { type: "FeatureCollection", features };
  }, [todaysJobsAll, search, crewFilter, priorityFilter]);

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

    map.addControl(new mapboxgl.NavigationControl({ showCompass: false }), "bottom-right");

    map.on("load", () => {
      addOperationalSourcesAndLayers(map);
      applyLayerVisibility(map, INITIAL_LAYERS);
      setMapReady(true);
    });

    const visibleClickable = () =>
      CLICKABLE_LAYERS.filter((id) => map.getLayer(id) && map.getLayoutProperty(id, "visibility") !== "none");

    map.on("click", (event) => {
      const hit = map.queryRenderedFeatures(event.point, { layers: visibleClickable() })[0];
      if (!hit) return;

      let html;
      if (hit.layer.id === "communities-fill") {
        const key = normalizeCommunityName(hit.properties.name);
        const code = hit.properties.code;
        const { summaries, crewFilter: filter } = interactionRef.current;

        // Selection highlight via feature-state
        if (selectedCommunityRef.current && selectedCommunityRef.current !== code) {
          try {
            map.setFeatureState({ source: "communities", id: selectedCommunityRef.current }, { selected: false });
          } catch {
            /* ignore missing feature */
          }
        }
        if (code) {
          try {
            map.setFeatureState({ source: "communities", id: code }, { selected: true });
            selectedCommunityRef.current = code;
            setSelectedCommunityKey(key);
          } catch {
            /* ignore */
          }
        }

        html = communityTodayPopup(hit.properties, summaries.get(key), filter);
      } else if (hit.layer.id === "todays-jobs-circle") {
        html = todaysJobPopup(hit.properties);
      } else {
        html = requestPopup(hit.properties);
      }
      new mapboxgl.Popup({ offset: 8 }).setLngLat(event.lngLat).setHTML(html).addTo(map);
    });

    map.on("mousemove", (event) => {
      const over = map.queryRenderedFeatures(event.point, { layers: visibleClickable() }).length > 0;
      map.getCanvas().style.cursor = over ? "pointer" : "";
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

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    map.getSource("communities")?.setData(communitiesStyled);
  }, [mapReady, communitiesStyled]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    map.getSource("requests")?.setData(filteredRequests);
  }, [mapReady, filteredRequests]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    map.getSource("todaysJobs")?.setData(filteredTodaysJobs);
  }, [mapReady, filteredTodaysJobs]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;
    applyLayerVisibility(map, layers);
  }, [layers, mapReady]);

  // Re-apply selection after communities data refresh (setData clears feature-state)
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !selectedCommunityRef.current) return;
    const id = selectedCommunityRef.current;
    // Wait a tick so setData has applied
    const t = window.setTimeout(() => {
      try {
        map.setFeatureState({ source: "communities", id }, { selected: true });
      } catch {
        /* ignore */
      }
    }, 0);
    return () => window.clearTimeout(t);
  }, [mapReady, communitiesStyled, selectedCommunityKey]);

  const handleLayerChange = (id, checked) => {
    setLayers((prev) => ({ ...prev, [id]: checked }));
    if (id === "todaysJobs" && checked) setCrewFilter("all");
    if (id === "communities" && !checked) {
      const map = mapRef.current;
      if (map && selectedCommunityRef.current) {
        try {
          map.setFeatureState(
            { source: "communities", id: selectedCommunityRef.current },
            { selected: false },
          );
        } catch {
          /* ignore */
        }
      }
      selectedCommunityRef.current = null;
      setSelectedCommunityKey(null);
    }
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

      <div className="pointer-events-none absolute top-3 right-3 z-10 flex flex-col items-end gap-2">
        {simStatus === "ready" && <DisruptionControls />}
        <MapSearchFilters
          search={search}
          onSearchChange={setSearch}
          crewFilter={crewFilter}
          onCrewFilterChange={setCrewFilter}
          priorityFilter={priorityFilter}
          onPriorityFilterChange={setPriorityFilter}
          crewOptions={crewOptions}
          priorityOptions={PRIORITY_BANDS}
        />
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 z-10 flex max-h-[70%] flex-col gap-2 overflow-hidden">
        <MapLayersPanel layers={layers} onChange={handleLayerChange} />
        {layers.todaysJobs && <CrewLegend crews={crewLegend} highlightCrew={crewFilter} />}
        {layers.communities && <CommunityLegend communities={communityLegend} />}
      </div>
    </div>
  );
}

export default CalgaryMap;
