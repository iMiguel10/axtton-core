import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { AppSplash } from "@/shared/components/Loading";

import { fetchWorkshopBySlug } from "./api";
import { UnknownEntry, WorkshopEntry } from "./RequestLinkPage";

/**
 * `/portal/{nombre}` (decisión 0007): la dirección corta que el taller imprime. Se
 * busca el taller por su nombre y se enseña su entrada, la misma que por su id.
 */
export function SlugEntryPage() {
  const { slug = "" } = useParams();
  const found = useQuery({
    queryKey: ["portal", "slug", slug],
    queryFn: () => fetchWorkshopBySlug(slug),
    retry: false,
  });
  if (found.isPending) return <AppSplash />;
  if (!found.data) return <UnknownEntry />;
  return <WorkshopEntry workshopId={found.data.workshop_id} />;
}
