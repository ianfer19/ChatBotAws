import { ApiError } from "./api";

/** Convierte cualquier error de la consola en un mensaje accionable en español. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.message} (${error.code})`;
  }
  if (error instanceof TypeError) {
    return "No se pudo conectar con la API local. ¿Está corriendo en 127.0.0.1:8000?";
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Error inesperado de la consola.";
}
