# Programador externo para METAR

Este módulo desacopla **el disparo de la actualización** del programador interno de GitHub Actions.
La fuente y la clasificación METAR continúan en `scripts/actualizar_metar.py`; el JSON
continúa en `data/metar_latest.json` y el sitio sigue alojado en GitHub Pages.

**Arquitectura:**

Cloudflare Cron Trigger (cada 10 min) → GitHub API `workflow_dispatch` →
GitHub Actions ejecuta Python → publica `data/metar_latest.json` →
el mapa METAR lee JSON de GitHub raw.

## Activación (única vez)

1. Crear o iniciar sesión en una cuenta de [Cloudflare Workers](https://dash.cloudflare.com/).
2. En GitHub, crear un **fine-grained personal access token** limitado
   solamente al repositorio `mauricioNico/visualizadorMeteorologico`, con permiso
   **Actions: Read and write** y sin otros permisos innecesarios.
   Puede tener fecha de caducidad; planificar su renovación antes de que expire.
3. Desde una terminal con Node.js en la raíz de este directorio:

   ```bash
   npx wrangler login
   npx wrangler deploy
   npx wrangler secret put GITHUB_TOKEN
   ```

   El despliegue inicial crea el Worker; luego, al configurar el secreto, Wrangler\n   publica una nueva versión. Cuando pida el secreto, introducirlo en la terminal. **Nunca pegarlo en un archivo
   del repositorio, mensaje público, issue ni chat.**
4. En Cloudflare Workers, abrir el Worker `visualizador-metar-scheduler` y verificar
   que tenga activo el Cron Trigger `4,14,24,34,44,54 * * * *` (horas UTC).
5. Consultar `https://<tu-worker>.workers.dev/health` para comprobar la fecha
   de publicación y antigüedad del JSON.
6. Comprobar en GitHub Actions que comienzan a aparecer ejecuciones del workflow
   **Actualizar METAR del mapa interactivo** con evento `workflow_dispatch`.

## Comportamiento

- Sólo el **evento cron de Cloudflare** puede iniciar el workflow. El endpoint público
  del Worker es de lectura: `/health`.
- El código responde a la API de GitHub sin exponer la credencial.
- Reintenta respuestas temporales, pero falla claramente ante 401/403/404.
- GitHub Actions sigue siendo el ejecutor del Python. Si GitHub Actions, NOAA o
  el repositorio dejan de funcionar, la actualización puede atrasarse;
  **no existe garantía de 100 %**.
- Cloudflare puede tardar hasta unos 15 minutos en propagar los cambios de cron.
- Si el token expira, hay que renovarlo y actualizar el secreto en Cloudflare.
- Para independencia total de GitHub Actions habría que trasladar también
  procesamiento y almacenamiento a una plataforma externa (por ejemplo,
  Worker con KV/R2 y una transformación específica de METAR).

Documentación:
- Cloudflare: https://developers.cloudflare.com/workers/configuration/cron-triggers/
- Credenciales Worker: https://developers.cloudflare.com/workers/configuration/secrets/
- GitHub Dispatch: https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
