import { ChevronRight, X } from "lucide-react";
import type { PlaceDataset, PlaceDetail } from "#/catalog/queries.ts";
import { summarize } from "#/lib/summarize.ts";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Separator } from "./ui/separator";
import { Skeleton } from "./ui/skeleton";

const fmt = new Intl.NumberFormat("en");

const LEVEL_LABEL = {
  region: "Region",
  province: "Province",
  city: "City / municipality",
  barangay: "Barangay",
} as const;

function DatasetCard({ entry }: { entry: PlaceDataset }) {
  const { dataset } = entry;
  const source = [dataset.attribution, dataset.license]
    .filter(Boolean)
    .join(" · ");
  return (
    <Card className="gap-3 py-4">
      <CardHeader className="px-4">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm">{dataset.name}</CardTitle>
          <Badge variant="secondary" className="tabular-nums">
            {fmt.format(entry.rows)}
          </Badge>
        </div>
        {dataset.description && (
          <CardDescription className="text-xs">
            {dataset.description}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-1.5 px-4 text-xs">
        {entry.sample.map((row, i) => {
          const { title, rest } = summarize(row);
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: sample rows have no id of their own
            <div key={i} className="flex min-w-0 flex-col">
              <span className="truncate font-medium">{title}</span>
              {rest && (
                <span className="truncate text-muted-foreground">{rest}</span>
              )}
            </div>
          );
        })}
        {entry.rows > entry.sample.length && (
          <p className="text-muted-foreground">
            and {fmt.format(entry.rows - entry.sample.length)} more
          </p>
        )}
      </CardContent>
      {source && (
        <CardFooter className="px-4 text-[11px] text-muted-foreground">
          {source}
        </CardFooter>
      )}
    </Card>
  );
}

export default function PlaceSheet({
  place,
  loading,
  onSelect,
  onClose,
}: {
  place: PlaceDetail | null | undefined;
  loading: boolean;
  onSelect: (code: string) => void;
  onClose: () => void;
}) {
  return (
    <aside className="absolute inset-y-3 right-14 z-20 flex w-80 max-w-[calc(100%-4.5rem)] flex-col">
      <Card className="h-full gap-0 overflow-hidden py-0">
        <CardHeader className="shrink-0 gap-1 border-b px-4 py-3">
          <div className="flex items-start justify-between gap-2">
            <div className="flex min-w-0 flex-col gap-0.5">
              {place ? (
                <>
                  <CardTitle className="truncate text-base">
                    {place.name}
                  </CardTitle>
                  <CardDescription className="text-xs">
                    {LEVEL_LABEL[place.level]} · {place.code}
                  </CardDescription>
                </>
              ) : (
                <Skeleton className="h-5 w-40" />
              )}
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon-sm"
              aria-label="Close"
              onClick={onClose}
            >
              <X />
            </Button>
          </div>
          {place && place.ancestors.length > 0 && (
            <nav
              aria-label="Places above"
              className="flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground"
            >
              {place.ancestors.map((a, i) => (
                <span key={a.code} className="flex items-center gap-1">
                  {i > 0 && <ChevronRight className="size-3" />}
                  <button
                    type="button"
                    onClick={() => onSelect(a.code)}
                    className="cursor-pointer hover:text-foreground hover:underline"
                  >
                    {a.name}
                  </button>
                </span>
              ))}
            </nav>
          )}
        </CardHeader>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
          {loading && !place ? (
            <>
              <Skeleton className="h-28 w-full" />
              <Skeleton className="h-28 w-full" />
            </>
          ) : !place ? (
            <p className="p-1 text-sm text-muted-foreground">
              This code isn't a current PSGC place.
            </p>
          ) : (
            <>
              {place.datasets.length === 0 ? (
                <p className="p-1 text-sm text-muted-foreground">
                  No tagged dataset has rows here yet.
                </p>
              ) : (
                place.datasets.map((entry) => (
                  <DatasetCard key={entry.dataset.name} entry={entry} />
                ))
              )}

              {place.children.length > 0 && (
                <>
                  <Separator />
                  <section className="flex flex-col gap-1">
                    <h3 className="px-1 text-xs font-semibold text-muted-foreground">
                      Inside {place.name}
                    </h3>
                    {place.children.map((child) => (
                      <button
                        type="button"
                        key={child.code}
                        onClick={() => onSelect(child.code)}
                        className="flex cursor-pointer items-center justify-between gap-2 rounded-md px-2 py-1 text-left text-xs hover:bg-muted"
                      >
                        <span className="truncate">{child.name}</span>
                        <span className="shrink-0 tabular-nums text-muted-foreground">
                          {fmt.format(child.rows)}
                        </span>
                      </button>
                    ))}
                  </section>
                </>
              )}
            </>
          )}
        </div>
      </Card>
    </aside>
  );
}
