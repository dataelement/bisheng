/** A resource URL belongs to its previous management tenant. */
export function knowledgeScopeLanding(pathname: string, search: string): string | null {
  if (pathname !== "/filelib" && !pathname.startsWith("/filelib/")) return null;
  const views = new URLSearchParams(search).getAll("view");
  const view = views.length === 1 ? views[0] : null;
  return view === "admin" || view === "qa" ? `/filelib?view=${view}` : "/filelib";
}
