import { z } from "zod";

/** Contraseña nueva con confirmación. El mínimo coincide con el del backend. */
export const newPasswordSchema = z
  .object({
    password: z.string().min(10, "validation.passwordLength"),
    confirm: z.string(),
  })
  .refine((values) => values.password === values.confirm, {
    path: ["confirm"],
    message: "validation.passwordsDiffer",
  });

export type NewPasswordForm = z.infer<typeof newPasswordSchema>;
