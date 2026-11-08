# Consola web (Astro + React)

Interfaz local de la Fase A. **Astro usa Vite por dentro**: no hay un `vite.config.ts`
separado; el proxy del API se configura en `astro.config.mjs`.

## Comandos

```bash
npm install
npm run dev      # http://localhost:5173 (proxy /api -> 127.0.0.1:8000)
npm run check    # astro check (tipos y componentes)
npm run build    # sitio estático en dist/
npm run preview  # sirve dist/ localmente
```

La API debe estar corriendo en `http://127.0.0.1:8000`:

```bash
python -m uvicorn handlers.console_api:app --app-dir src --reload --port 8000
```

## Estructura

```text
src/
├── pages/index.astro          # shell de la consola
├── layouts/ConsoleLayout.astro
├── components/                # islas React (client:only="react")
│   ├── ConsoleApp.tsx
│   ├── TenantSidebar.tsx
│   ├── ChatPanel.tsx
│   ├── TracePanel.tsx
│   ├── TenantConfigForm.tsx
│   └── PromptEditor.tsx
├── api.ts                     # cliente HTTP tipado
├── types.ts
└── styles/global.css
```

## Variables

- `VITE_API_BASE_URL`: opcional; por defecto se usa el proxy `/api` de Astro/Vite.

## Nota de seguridad

`npm audit` reporta advisories de Astro 5 (XSS en directivas y RCE en optimización de
imágenes). La consola es local, estática y no procesa imágenes ni HTML de terceros, así
que el riesgo real es bajo. Antes de desplegarla (Fase D) hay que subir a Astro 7 y
Node 22, que es la versión que corregirá esos avisos. `TODO(verify)` en la Fase D.
