/**
 * Disparador externo del workflow METAR (Cloudflare Cron Triggers).
 *
 * No almacena ni expone el token; debe configurarse como secreto GITHUB_TOKEN
 * en Cloudflare. Un visitante no puede iniciar el workflow por HTTP.
 */
const ENDPOINT =
  "https://api.github.com/repos/mauricioNico/visualizadorMeteorologico/actions/workflows/actualizar-metar.yml/dispatches";
const METAR_JSON =
  "https://raw.githubusercontent.com/mauricioNico/visualizadorMeteorologico/main/data/metar_latest.json";

async function dispatchWorkflow(env) {
  if (!env.GITHUB_TOKEN) {
    throw new Error("Falta el secreto GITHUB_TOKEN en Cloudflare Workers");
  }

  let lastError;
  for (let attempt = 1; attempt <= 3; attempt++) {
    try {
      const response = await fetch(ENDPOINT, {
        method: "POST",
        headers: {
          Authorization: "Bearer " + env.GITHUB_TOKEN,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2026-03-10",
          "User-Agent": "visualizador-metar-external-scheduler",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: "main" }),
        signal: AbortSignal.timeout(12000),
      });
      // GitHub workflow_dispatch responde 204 No Content cuando acepta el disparo.
      if (response.status === 204) {
        console.log("Disparo de workflow aceptado por GitHub");
        return;
      }
      const message = (await response.text()).slice(0, 250);
      // No insistir con errores permanentes: credencial sin permisos, no encontrada.
      if ([400, 401, 403, 404, 422].includes(response.status)) {
        throw new Error("Error permanente GitHub HTTP " + response.status + ": " + message);
      }
      lastError = new Error("Error temporal GitHub HTTP " + response.status);
    } catch (error) {
      if (String(error.message).startsWith("Error permanente")) throw error;
      lastError = error;
    }
    if (attempt < 3) await new Promise(resolve => setTimeout(resolve, attempt * 1500));
  }
  throw lastError || new Error("No pudo iniciarse el workflow");
}

async function health() {
  try {
    const res = await fetch(METAR_JSON + "?t=" + Date.now(), {
      headers: { "User-Agent": "visualizador-metar-scheduler-health" },
      cf: { cacheTtl: 0 },
    });
    if (!res.ok) throw new Error("GitHub raw HTTP " + res.status);
    const obj = await res.json();
    const lastUpdate = Date.parse(obj.generatedAt);
    const ageMinutes = Number.isFinite(lastUpdate)
      ? Math.round((Date.now() - lastUpdate) / 60000)
      : null;
    return new Response(JSON.stringify({
      source: "GitHub raw / NOAA AWC",
      generatedAt: obj.generatedAt ?? null,
      stationCount: Array.isArray(obj.stations) ? obj.stations.length : null,
      ageMinutes,
      status: ageMinutes === null ? "unknown" : ageMinutes > 90 ? "delayed" : "current",
      note: "Este endpoint es informativo. El disparador se ejecuta únicamente desde el cron de Cloudflare."
    }), {
      status: 200,
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
    });
  } catch (error) {
    return new Response(JSON.stringify({ status: "unavailable", error: String(error.message) }), {
      status: 503,
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" }
    });
  }
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(dispatchWorkflow(env));
  },
  async fetch(request) {
    // Endpoint de sólo lectura, no expone el token ni permite disparar workflows.
    if (new URL(request.url).pathname === "/health" && request.method === "GET") {
      return health();
    }
    return new Response("METAR scheduler · GET /health", {
      status: 200,
      headers: { "Content-Type": "text/plain; charset=utf-8" }
    });
  }
};
