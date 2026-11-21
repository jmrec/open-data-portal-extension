import { Layers, Map as MapIcon, Settings2 } from "lucide-react";
import type {
  ExpressionSpecification,
  MapLayerMouseEvent,
  Map as MapLibreMap,
} from "maplibre-gl";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { AdminLevel } from "#/catalog/levels.ts";
import { bucketBreaks, bucketOf } from "#/lib/buckets.ts";
import { env } from "../env";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu";
import { MapControls, Map as MapView, useMap } from "./ui/map";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "./ui/tooltip";

// Layers of PH_Adm_Boundaries.pmtiles, built in boundaries/.
export const LEVELS = [
  {
    id: "region",
    sourceLayer: "PH_Adm1_Regions",
    codeKey: "adm1_psgc",
    nameKey: "adm1_en",
    label: "Region",
  },
  {
    id: "province",
    sourceLayer: "PH_Adm2_ProvDists",
    codeKey: "adm2_psgc",
    nameKey: "adm2_en",
    label: "Province",
  },
  {
    id: "city",
    sourceLayer: "PH_Adm3_MuniCities",
    codeKey: "adm3_psgc",
    nameKey: "adm3_en",
    label: "City/Mun.",
  },
  {
    id: "barangay",
    sourceLayer: "PH_Adm4_BgySubMuns",
    codeKey: "adm4_psgc",
    nameKey: "adm4_en",
    label: "Barangay",
  },
] as const satisfies readonly {
  id: AdminLevel;
  sourceLayer: string;
  codeKey: string;
  nameKey: string;
  label: string;
}[];

type LevelConfig = (typeof LEVELS)[number];

const SOURCE = "boundaries";
const PROMOTE_ID = Object.fromEntries(
  LEVELS.map((level) => [level.sourceLayer, level.codeKey]),
);
const fillId = (level: AdminLevel) => `${level}-fill`;
const outlineId = (level: AdminLevel) => `${level}-outline`;
const selectId = (level: AdminLevel) => `${level}-select`;
const OUR_LAYERS = new Set(
  LEVELS.flatMap((l) => [fillId(l.id), outlineId(l.id), selectId(l.id)]),
);

// Ordinal blue ramps, validated with the dataviz skill's checker
// (--ordinal, light on #fcfcfb and dark on #1a1a19). Dark runs the other way
// so the busiest places stand out against the dark surface.
const RAMP = {
  light: ["#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281"],
  dark: ["#184f95", "#256abf", "#3987e5", "#6da7ec", "#9ec5f4"],
} as const;
const OUTLINE = { light: "#94a3b8", dark: "#475569" } as const;
const SELECT = { light: "#0f172a", dark: "#f8fafc" } as const;

const CENTER: [number, number] = [122.2, 12.3];
const INITIAL_ZOOM = 5;
const MAX_ZOOM = 16;
const PH_BOUNDS: [[number, number], [number, number]] = [
  [110.5, 3.5],
  [131.5, 22.5],
];
const LIGHT_STYLE_URL = "https://tiles.openfreemap.org/styles/positron";
const DARK_STYLE_URL = "https://tiles.openfreemap.org/styles/dark";

function fillColor(theme: "light" | "dark"): ExpressionSpecification {
  const ramp = RAMP[theme];
  return [
    "match",
    ["coalesce", ["feature-state", "bucket"], -1],
    0,
    ramp[0],
    1,
    ramp[1],
    2,
    ramp[2],
    3,
    ramp[3],
    4,
    ramp[4],
    "rgba(0,0,0,0)",
  ];
}

function addLayers(map: MapLibreMap, theme: "light" | "dark") {
  if (!map.getSource(SOURCE)) {
    map.addSource(SOURCE, {
      type: "vector",
      url: env.VITE_TILE_SERVER_URL,
      promoteId: PROMOTE_ID,
      encoding: env.VITE_TILE_ENCODING,
    });
  }
  for (const level of LEVELS) {
    if (!map.getLayer(fillId(level.id))) {
      map.addLayer({
        id: fillId(level.id),
        type: "fill",
        source: SOURCE,
        "source-layer": level.sourceLayer,
        layout: { visibility: "none" },
        paint: {
          "fill-color": fillColor(theme),
          "fill-opacity": [
            "case",
            ["boolean", ["feature-state", "hover"], false],
            0.95,
            0.75,
          ],
        },
      });
    }
    if (!map.getLayer(outlineId(level.id))) {
      map.addLayer({
        id: outlineId(level.id),
        type: "line",
        source: SOURCE,
        "source-layer": level.sourceLayer,
        layout: { visibility: "none" },
        paint: { "line-color": OUTLINE[theme], "line-width": 0.6 },
      });
    }
    if (!map.getLayer(selectId(level.id))) {
      map.addLayer({
        id: selectId(level.id),
        type: "line",
        source: SOURCE,
        "source-layer": level.sourceLayer,
        filter: ["==", ["get", level.codeKey], ""],
        paint: { "line-color": SELECT[theme], "line-width": 2.5 },
      });
    }
  }
}

function removeLayers(map: MapLibreMap) {
  for (const id of OUR_LAYERS) if (map.getLayer(id)) map.removeLayer(id);
  if (map.getSource(SOURCE)) map.removeSource(SOURCE);
}

function showLevel(map: MapLibreMap, active: AdminLevel) {
  for (const level of LEVELS) {
    const visibility = level.id === active ? "visible" : "none";
    for (const id of [
      fillId(level.id),
      outlineId(level.id),
      selectId(level.id),
    ]) {
      if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", visibility);
    }
  }
}

function setBaseMap(map: MapLibreMap, visible: boolean) {
  for (const layer of map.getStyle().layers) {
    if (!OUR_LAYERS.has(layer.id)) {
      map.setLayoutProperty(
        layer.id,
        "visibility",
        visible ? "visible" : "none",
      );
    }
  }
}

function paintCounts(
  map: MapLibreMap,
  level: LevelConfig,
  counts: Map<string, number>,
  breaks: number[],
) {
  for (const l of LEVELS) {
    map.removeFeatureState({ source: SOURCE, sourceLayer: l.sourceLayer });
  }
  for (const [code, rows] of counts) {
    map.setFeatureState(
      { source: SOURCE, sourceLayer: level.sourceLayer, id: code },
      { bucket: bucketOf(rows, breaks), rows },
    );
  }
}

export type HoverInfo = { x: number; y: number; name: string; code: string };

type LayersProps = {
  level: AdminLevel;
  counts: Map<string, number>;
  breaks: number[];
  showBaseMap: boolean;
  selected: string | null;
  onHover: (info: HoverInfo | null) => void;
  onSelect: (code: string) => void;
};

function PlaceLayers({
  level,
  counts,
  breaks,
  showBaseMap,
  selected,
  onHover,
  onSelect,
}: LayersProps) {
  const { map, isLoaded, resolvedTheme } = useMap();
  const config = LEVELS.find((l) => l.id === level) ?? LEVELS[1];
  const configRef = useRef(config);
  configRef.current = config;
  const onHoverRef = useRef(onHover);
  onHoverRef.current = onHover;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  // Layers and events, re-added whenever the style reloads (theme switch).
  useEffect(() => {
    if (!map || !isLoaded) return;
    addLayers(map, resolvedTheme);
    let hovered: string | null = null;
    const clearHover = () => {
      if (hovered === null) return;
      map.setFeatureState(
        {
          source: SOURCE,
          sourceLayer: configRef.current.sourceLayer,
          id: hovered,
        },
        { hover: false },
      );
      hovered = null;
    };
    const handlers = LEVELS.map((l) => {
      const move = (e: MapLayerMouseEvent) => {
        const feature = e.features?.[0];
        if (!feature || configRef.current.id !== l.id) return;
        const code = String(feature.properties?.[l.codeKey] ?? "");
        if (!code) return;
        if (code !== hovered) {
          clearHover();
          hovered = code;
          map.setFeatureState(
            { source: SOURCE, sourceLayer: l.sourceLayer, id: code },
            { hover: true },
          );
        }
        map.getCanvas().style.cursor = "pointer";
        onHoverRef.current({
          x: e.point.x,
          y: e.point.y,
          code,
          name: String(feature.properties?.[l.nameKey] ?? code),
        });
      };
      const leave = () => {
        clearHover();
        map.getCanvas().style.cursor = "";
        onHoverRef.current(null);
      };
      const click = (e: MapLayerMouseEvent) => {
        const code = e.features?.[0]?.properties?.[l.codeKey];
        if (code && configRef.current.id === l.id)
          onSelectRef.current(String(code));
      };
      map.on("mousemove", fillId(l.id), move);
      map.on("mouseleave", fillId(l.id), leave);
      map.on("click", fillId(l.id), click);
      return { id: fillId(l.id), move, leave, click };
    });
    return () => {
      for (const h of handlers) {
        map.off("mousemove", h.id, h.move);
        map.off("mouseleave", h.id, h.leave);
        map.off("click", h.id, h.click);
      }
      removeLayers(map);
    };
  }, [map, isLoaded, resolvedTheme]);

  useEffect(() => {
    if (!map || !isLoaded || !map.getSource(SOURCE)) return;
    showLevel(map, config.id);
    paintCounts(map, config, counts, breaks);
  }, [map, isLoaded, config, counts, breaks]);

  useEffect(() => {
    if (!map || !isLoaded || !map.getSource(SOURCE)) return;
    setBaseMap(map, showBaseMap);
  }, [map, isLoaded, showBaseMap]);

  useEffect(() => {
    if (!map || !isLoaded) return;
    for (const l of LEVELS) {
      if (map.getLayer(selectId(l.id))) {
        map.setFilter(selectId(l.id), [
          "==",
          ["get", l.codeKey],
          selected ?? "",
        ]);
      }
    }
  }, [map, isLoaded, selected]);

  useEffect(() => {
    if (!map || !isLoaded) return;
    const observer = new ResizeObserver(() => map.resize());
    observer.observe(map.getContainer());
    return () => observer.disconnect();
  }, [map, isLoaded]);

  return null;
}

function Legend({
  breaks,
  theme,
}: {
  breaks: number[];
  theme: "light" | "dark";
}) {
  const ramp = RAMP[theme];
  const fmt = new Intl.NumberFormat("en");
  return (
    <Card className="w-44 gap-2 py-3">
      <CardHeader className="px-3">
        <CardTitle className="text-xs font-semibold">Tagged rows</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-1.5 px-3 text-xs">
        {breaks.length === 0 ? (
          <p className="text-muted-foreground">No rows at this level.</p>
        ) : (
          breaks.map((upper, i) => {
            const lower = i === 0 ? 1 : (breaks[i - 1] ?? 0) + 1;
            return (
              <div key={upper} className="flex items-center gap-2">
                <span
                  className="size-3 shrink-0 rounded-sm"
                  style={{ backgroundColor: ramp[i] }}
                />
                <span className="tabular-nums">
                  {lower === upper
                    ? fmt.format(upper)
                    : `${fmt.format(lower)}–${fmt.format(upper)}`}
                </span>
              </div>
            );
          })
        )}
        <p className="text-muted-foreground">No color: no tagged rows</p>
      </CardContent>
    </Card>
  );
}

function ThemedLegend({ breaks }: { breaks: number[] }) {
  const { resolvedTheme } = useMap();
  return <Legend breaks={breaks} theme={resolvedTheme} />;
}

export default function PlaceMap({
  level,
  onLevelChange,
  counts,
  selected,
  onSelect,
  children,
}: {
  level: AdminLevel;
  onLevelChange: (level: AdminLevel) => void;
  counts: Map<string, number>;
  selected: string | null;
  onSelect: (code: string) => void;
  children?: React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [showBaseMap, setShowBaseMap] = useState(true);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const breaks = useBreaks(counts);

  const popupRef = useRef<HTMLDivElement>(null);
  const [popupLeft, setPopupLeft] = useState(false);
  useLayoutEffect(() => {
    if (!hover || !containerRef.current) return;
    setPopupLeft(hover.x > containerRef.current.clientWidth / 1.3);
  }, [hover]);

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden">
      <MapView
        className="absolute inset-0 h-full w-full"
        center={CENTER}
        zoom={INITIAL_ZOOM}
        maxZoom={MAX_ZOOM}
        maxBounds={PH_BOUNDS}
        styles={{ light: LIGHT_STYLE_URL, dark: DARK_STYLE_URL }}
      >
        <MapControls position="bottom-right" showZoom showLocate />
        <PlaceLayers
          level={level}
          counts={counts}
          breaks={breaks}
          showBaseMap={showBaseMap}
          selected={selected}
          onHover={setHover}
          onSelect={onSelect}
        />
        <div className="absolute bottom-3 left-3 z-10">
          <ThemedLegend breaks={breaks} />
        </div>
      </MapView>

      <TooltipProvider delayDuration={200}>
        <div className="absolute right-2 top-3 z-10 flex flex-col gap-1.5">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                type="button"
                variant={showBaseMap ? "default" : "secondary"}
                size="icon"
                aria-label={showBaseMap ? "Hide base map" : "Show base map"}
                onClick={() => setShowBaseMap((v) => !v)}
              >
                <MapIcon />
              </Button>
            </TooltipTrigger>
            <TooltipContent side="left">
              {showBaseMap ? "Hide base map" : "Show base map"}
            </TooltipContent>
          </Tooltip>

          <DropdownMenu>
            <Tooltip>
              <TooltipTrigger asChild>
                <DropdownMenuTrigger asChild>
                  <Button
                    type="button"
                    variant="secondary"
                    size="icon"
                    aria-label="Choose level"
                  >
                    <Settings2 />
                  </Button>
                </DropdownMenuTrigger>
              </TooltipTrigger>
              <TooltipContent side="left">Level</TooltipContent>
            </Tooltip>
            <DropdownMenuContent align="end" className="w-40">
              <DropdownMenuGroup>
                <DropdownMenuLabel>
                  <span className="flex items-center gap-1.5">
                    <Layers /> Level
                  </span>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuRadioGroup
                  value={level}
                  onValueChange={(value) => onLevelChange(value as AdminLevel)}
                >
                  {LEVELS.map((l) => (
                    <DropdownMenuRadioItem key={l.id} value={l.id}>
                      {l.label}
                    </DropdownMenuRadioItem>
                  ))}
                </DropdownMenuRadioGroup>
              </DropdownMenuGroup>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </TooltipProvider>

      {hover && (
        <div
          ref={popupRef}
          className="pointer-events-none absolute z-50 flex flex-col gap-0.5 rounded-md border bg-popover px-2.5 py-1.5 text-xs text-popover-foreground shadow-md"
          style={{
            left: popupLeft ? undefined : hover.x + 12,
            right: popupLeft
              ? (containerRef.current?.clientWidth ?? 0) - hover.x + 12
              : undefined,
            top: hover.y + 12,
          }}
        >
          <p className="font-semibold">{hover.name}</p>
          <p className="text-muted-foreground tabular-nums">
            {new Intl.NumberFormat("en").format(counts.get(hover.code) ?? 0)}{" "}
            tagged rows
          </p>
        </div>
      )}

      {children}
    </div>
  );
}

function useBreaks(counts: Map<string, number>): number[] {
  return useMemo(() => bucketBreaks([...counts.values()]), [counts]);
}
