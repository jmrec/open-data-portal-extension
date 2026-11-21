import { calloutsExtension } from "@tanstack/markdown/extensions/callouts";
import { parseMarkdown } from "@tanstack/markdown/parser";
import { Markdown } from "@tanstack/markdown/react";
import { useQuery } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { getDatasets } from "#/catalog/functions.ts";
import aboutMarkdown from "#/data/about.md?raw";

export const Route = createFileRoute("/about")({
  component: About,
});

const parsed = parseMarkdown(aboutMarkdown, {
  extensions: [calloutsExtension()],
});

const fmt = new Intl.NumberFormat("en");

function About() {
  const { data: datasets = [] } = useQuery({
    queryKey: ["datasets"],
    queryFn: () => getDatasets(),
  });

  return (
    <main className="page-wrap px-4 py-12">
      <section className="flex flex-col gap-10 p-6 sm:p-8">
        <div className="flex flex-col gap-2">
          <p className="island-kicker">About</p>
          <h1 className="display-title text-4xl font-bold text-(--sea-ink) sm:text-5xl">
            Every dataset, by place
          </h1>
        </div>
        <div className="prose max-w-3xl dark:prose-invert">
          <Markdown>{parsed}</Markdown>
        </div>

        {datasets.length > 0 && (
          <div className="flex max-w-3xl flex-col gap-3">
            <h2 className="text-xl font-semibold">Datasets</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="py-2 pr-4 font-medium">Dataset</th>
                    <th className="py-2 pr-4 text-right font-medium">Rows</th>
                    <th className="py-2 pr-4 text-right font-medium">Placed</th>
                    <th className="py-2 font-medium">Source and license</th>
                  </tr>
                </thead>
                <tbody>
                  {datasets.map((d) => (
                    <tr key={d.name} className="border-t align-top">
                      <td className="py-2 pr-4">
                        <p className="font-medium">{d.name}</p>
                        {d.description && (
                          <p className="text-xs text-muted-foreground">
                            {d.description}
                          </p>
                        )}
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {fmt.format(d.rows)}
                      </td>
                      <td className="py-2 pr-4 text-right tabular-nums">
                        {d.rows
                          ? `${((100 * d.auto) / d.rows).toFixed(1)}%`
                          : "–"}
                      </td>
                      <td className="py-2 text-xs">
                        {d.attribution ?? "–"}
                        {d.license && (
                          <span className="text-muted-foreground">
                            {" "}
                            · {d.license}
                          </span>
                        )}
                        {d.url && (
                          <>
                            {" · "}
                            <a
                              href={d.url}
                              target="_blank"
                              rel="noreferrer"
                              className="underline"
                            >
                              link
                            </a>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </section>
    </main>
  );
}
