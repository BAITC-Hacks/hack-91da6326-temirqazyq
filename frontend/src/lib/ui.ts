import {
  BusFront,
  Trees,
  HeartPulse,
  ShieldCheck,
  Building2,
} from "lucide-react";
import type { Category, Priority } from "./types";
import { ensureSession, needsSession } from "./session.ts";
import { publicErrorMessage, serviceUnavailable } from "./feedback.ts";

export const categories: Record<
  Category,
  {
    label: string;
    color: string;
    light: string;
    icon: typeof BusFront;
    indicators: string[];
  }
> = {
  transport: {
    label: "Транспорт",
    color: "#537bd5",
    light: "#edf2fc",
    icon: BusFront,
    indicators: ["T1", "T2"],
  },
  ecology: {
    label: "Экология",
    color: "#248e6b",
    light: "#eaf6ef",
    icon: Trees,
    indicators: ["E1", "E2"],
  },
  social: {
    label: "Социальная сфера",
    color: "#8f68c3",
    light: "#f3eefb",
    icon: HeartPulse,
    indicators: ["S1", "S2"],
  },
  safety: {
    label: "Безопасность",
    color: "#c38a30",
    light: "#fcf4e5",
    icon: ShieldCheck,
    indicators: ["B1", "B2"],
  },
  services: {
    label: "Городские сервисы",
    color: "#468e9e",
    light: "#edf6f8",
    icon: Building2,
    indicators: ["C1", "C2"],
  },
};
export const indicatorNames: Record<string, string> = {
  T1: "Разгрузка дорог",
  T2: "Общественный транспорт",
  E1: "Озеленение",
  E2: "Качество воздуха",
  S1: "Школы и детсады",
  S2: "Поликлиники",
  B1: "Безопасность улиц",
  B2: "Дорожная безопасность",
  C1: "Надёжность ЖКХ",
  C2: "Обращения жителей",
};
export const priorities: Record<Priority, string> = {
  balanced: "Сбалансированное развитие",
  overall_score: "Качество жизни города",
  weakest_district: "Поддержка слабого района",
  reduce_critical: "Снижение критических показателей",
  transport: "Транспорт",
  ecology: "Экология",
  social: "Социальная сфера",
  safety: "Безопасность",
  services: "Городские сервисы",
};
export const fmt = (value: number, digits = 2) =>
  value.toLocaleString("ru-RU", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
export const signed = (value: number, digits = 2) =>
  `${value > 0 ? "+" : ""}${fmt(value, digits)}`;
export const keys = Object.keys(categories) as Category[];

export async function api<T>(
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  try {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (needsSession(path)) headers["X-Session-ID"] = await ensureSession();
    const response = await fetch(`/api/${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      signal,
      cache: "no-store",
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      if (
        response.status === 422 &&
        payload?.valid === false &&
        Array.isArray(payload.errors) &&
        body !== undefined &&
        (path.startsWith("scenario/") || path === "optimizer/search")
      )
        return payload as T;
      throw new Error(serviceUnavailable);
    }
    if (payload === null) throw new Error(serviceUnavailable);
    return payload as T;
  } catch (error) {
    if (signal?.aborted) throw error;
    // Next forwards this fixed diagnostic to the development terminal. Never
    // log response bodies, credentials, session IDs or the user's request.
    console.warn("[client] REQUEST_UNAVAILABLE");
    throw new Error(publicErrorMessage(error));
  }
}
