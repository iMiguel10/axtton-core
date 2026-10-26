import type { ComponentProps } from "react";

import { cn } from "@/shared/lib/utils";

/** <textarea> nativo con el aspecto de Input. */
export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(
        "border-input bg-card placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-ring/50 dark:bg-input/30 min-h-20 w-full rounded-lg border px-2.5 py-1.5 text-base outline-none focus-visible:ring-3 disabled:opacity-50 md:text-sm",
        className,
      )}
      {...props}
    />
  );
}
