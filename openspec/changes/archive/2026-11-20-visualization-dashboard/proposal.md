# Proposal

## Why

Los grafos generados ya incluyen cobertura, rechazos y una prueba física de ruta, pero el reporte solo aparece en stdout y no se conserva la geometría usada para construirlo. Esto dificulta comparar niveles, inspeccionar episodios terminados y revisar los datos sin volver a iniciar Godot.

## What Changes

- Guardar por nivel el reporte completo de generación y la geometría exportada, conservando los grafos schema-version-one existentes.
- Permitir guardar resúmenes de episodios en archivos JSONL fechados, manteniendo la salida actual por stdout.
- Añadir un panel local opcional con Streamlit y Plotly para inspeccionar niveles, métricas y episodios desde los artefactos guardados.
- Añadir una página de simulación en vivo solo cuando la instalación y configuración de Godot lo permitan.
- Documentar instalación, ejecución, formatos de datos y capturas del panel.

## Capabilities

### New Capabilities

- `dashboard-data`: Persistencia y carga validada de geometría, reportes de grafos y resultados de episodios para inspección local.
- `visualization-dashboard`: Panel local para visualizar geometría y navegación, comparar métricas y analizar episodios guardados.

### Modified Capabilities

Ninguna.

## Impact

- Afecta `src/keepy_ai/graph/workflow.py`, `src/keepy_ai/cli.py`, el comando `run-episode` y nuevos módulos de carga y visualización.
- Añade un grupo opcional `viz` de dependencias y el comando `keepy-dashboard`; la instalación base seguirá sin Streamlit ni Plotly.
- Crea artefactos locales bajo `reports/`, `geometry/` y `episodes/`, y documentación en `docs/dashboard.md` con un enlace desde `README.md`.
- Consume los formatos existentes de grafos schema-version-one y geometría schema-version-one del puente; no modifica el contrato ni el proyecto Godot.
