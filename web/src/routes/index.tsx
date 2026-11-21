import { useQuery } from "@tanstack/react-query";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Database } from "lucide-react";
import { useEffect, useMemo } from "react";
import { getDatasets, getPlace, getPlaceCounts } from "#/catalog/functions.ts";
import { type AdminLevel, LEVEL_IDS } from "#/catalog/levels.ts";
import PlaceMap from "#/components/PlaceMap.tsx";
import PlaceSheet from "#/components/PlaceSheet.tsx";
import { Button } from "#/components/ui/button.tsx";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "#/components/ui/dropdown-menu.tsx";

type Search = { place?: string; level?: AdminLevel; dataset?: string };

const ALL = "__all__";

/** A 10-digit PSGC code; router.tsx keeps digit-only values as strings. */
function psgcParam(value: unknown): string | undefined {
  return typeof value === "string" && /^\d{10}$/.test(value)
    ? value
    : undefined;
}

export const Route = createFileRoute("/")({
  validateSearch: (search: Record<string, unknown>): Search => ({
    place: psgcParam(search.place),
    level: LEVEL_IDS.includes(search.level as AdminLevel)
      ? (search.level as AdminLevel)
      : undefined,
    dataset: typeof search.dataset === "string" ? search.dataset : undefined,
  }),
  component: PlacePage,
});

function PlacePage() {
  const search = Route.useSearch();
  const navigate = useNavigate({ from: Route.fullPath });
  const level = search.level ?? "province";
  const update = (next: Partial<Search>) =>
    void navigate({ search: (prev) => ({ ...prev, ...next }) });

  const { data: datasets = [] } = useQuery({
    queryKey: ["datasets"],
    queryFn: () => getDatasets(),
  });
  const { data: countPairs } = useQuery({
    queryKey: ["place-counts", level, search.dataset],
    queryFn: () => getPlaceCounts({ data: { level, dataset: search.dataset } }),
    placeholderData: (previous) => previous,
  });
  const counts = useMemo(() => new Map(countPairs ?? []), [countPairs]);
  const { data: place, isFetching } = useQuery({
    queryKey: ["place", search.place],
    queryFn: () => getPlace({ data: { code: search.place ?? "" } }),
    enabled: Boolean(search.place),
  });

  // A breadcrumb or child link can select a place at another level.
  useEffect(() => {
    if (place && place.code === search.place && place.level !== level) {
      update({ level: place.level });
    }
  });

  useEffect(() => {
    const root = document.documentElement;
    root.classList.add("map-layout");
    return () => root.classList.remove("map-layout");
  }, []);

  const datasetLabel = search.dataset ?? "All datasets";

  return (
    <main className="relative min-h-0 overflow-hidden">
      <section className="h-full w-full overflow-hidden">
        <PlaceMap
          level={level}
          onLevelChange={(next) => update({ level: next, place: undefined })}
          counts={counts}
          selected={search.place ?? null}
          onSelect={(code) =>
            update({ place: code === search.place ? undefined : code })
          }
        >
          <div className="absolute left-3 top-3 z-10">
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button type="button" variant="secondary" size="sm">
                  <Database data-icon="inline-start" />
                  {datasetLabel}
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuGroup>
                  <DropdownMenuLabel>Shade by</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  <DropdownMenuRadioGroup
                    value={search.dataset ?? ALL}
                    onValueChange={(value) =>
                      update({ dataset: value === ALL ? undefined : value })
                    }
                  >
                    <DropdownMenuRadioItem value={ALL}>
                      All datasets
                    </DropdownMenuRadioItem>
                    {datasets.map((d) => (
                      <DropdownMenuRadioItem key={d.name} value={d.name}>
                        {d.name}
                      </DropdownMenuRadioItem>
                    ))}
                  </DropdownMenuRadioGroup>
                </DropdownMenuGroup>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {search.place && (
            <PlaceSheet
              place={
                place === null || place?.code === search.place
                  ? place
                  : undefined
              }
              loading={isFetching}
              onSelect={(code) => update({ place: code })}
              onClose={() => update({ place: undefined })}
            />
          )}
        </PlaceMap>
      </section>
    </main>
  );
}
