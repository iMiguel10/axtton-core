import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./apiClient";

/**
 * TanStack Query guarda en caché lo que devuelve la API y se ocupa de lo que en F0
 * hacíamos a mano en cada useEffect: carga, error y descartar respuestas viejas.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 30,
      // Un 4xx (un 404, un 403) no se arregla reintentando: solo se reintenta una
      // vez ante fallos de red o 5xx.
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.status < 500) && failureCount < 1,
      refetchOnWindowFocus: false,
    },
    mutations: { retry: 0 },
  },
});
