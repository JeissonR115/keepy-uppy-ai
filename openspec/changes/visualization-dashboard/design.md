# Design

## Context

`generate_graphs` ya obtiene y valida la geometría, escribe el grafo y construye el reporte final después de comprobar la ruta. `run_episode_batch` emite un resumen por episodio a un `TextIO`, actualmente stdout. Los grafos y la geometría usan contratos schema-version-one; el panel debe consumir archivos y seguir funcionando aunque Godot no esté instalado.

## Goals / Non-Goals

**Goals:**

- Conservar los artefactos generados en ubicaciones predecibles y facilitar su carga validada fuera de la UI.
- Mantener salidas legibles por máquina y compatibilidad con los grafos y resúmenes existentes.
- Separar las funciones puras de carga y transformación de la capa Streamlit para poder probarlas sin iniciar el panel.
- Mantener las bibliotecas de visualización en un grupo opcional.

**Non-Goals:**

- Cambiar el esquema del puente, la simulación o los archivos de Godot.
- Persistir telemetría completa de cada tick; el formato actual de episodios conserva resúmenes terminales.
- Entrenar agentes o servir el panel remotamente.

## Decisions

- **Conservar el payload original de geometría.** Guardar el diccionario JSON entregado por `get_level_geometry` antes de convertirlo a `LevelGeometry`. Así se preservan campos del contrato que el modelo Python aún no interprete. Se escribe de forma atómica, igual que el grafo.
- **Añadir directorios de salida configurables al generador.** Los valores predeterminados son `reports/` y `geometry/` junto al directorio de grafos por defecto del repositorio. El reporte JSON conserva las claves del reporte actual y añade `graph_path` y `route_check`; stdout continúa emitiendo el mismo objeto.
- **Usar JSONL append-only para episodios.** Una opción de CLI habilita el archivo fechado bajo `episodes/`; stdout sigue siendo el destino actual. Cada resumen se escribe en ambas salidas una vez completado, para que una interrupción no borre episodios ya guardados. El resumen cuenta los eventos de tipo `fault` recibidos durante el episodio; su duración se expresa con el contador de pasos existente.
- **Crear una capa de datos sin dependencias de UI.** Funciones de lectura descubrirán niveles por sus artefactos, validarán los esquemas conocidos y devolverán errores que incluyan ruta y número de línea cuando aplique. Funciones de transformación expondrán puntos, segmentos, aristas, métricas y campos de episodio en estructuras aptas para graficar.
- **Mantener el panel como adaptador delgado.** Streamlit ofrece páginas Niveles, Métricas y Episodios; Plotly representa geometría, aristas, nodos y gráficos. Las páginas consultan la capa de datos y no leen archivos directamente.
- **Gatear la vista en vivo por disponibilidad.** Se detecta `GODOT_BIN` ejecutable y configuración de proyecto antes de mostrar controles de simulación. Las páginas offline no dependen de la vista en vivo; esta vista usa el launcher y el cliente existentes y libera la sesión al cerrar.
- **Mantener `viz` opcional en `pyproject.toml`.** El punto de entrada `keepy-dashboard` instala/ejecuta Streamlit solo en el entorno con el grupo `viz`; no se añade ninguna dependencia de visualización al grupo base.

Alternativas consideradas: incrustar la UI en el CLI existente (mezcla responsabilidades y complica las pruebas), guardar reportes solo en stdout (no permite uso offline reproducible) y volver a consultar Godot para dibujar el nivel (incumple la inspección offline).

## Risks / Trade-offs

- [El formato de geometría o reportes puede evolucionar] → Validar `schema_version`, conservar el payload de geometría y mostrar errores compatibles con el archivo afectado.
- [JSONL puede contener una última línea parcial tras una interrupción abrupta] → Leer línea por línea, informar la línea inválida y conservar los registros anteriores.
- [La vista en vivo puede dejar un proceso Godot activo si falla la UI] → Usar el ciclo de vida del `GodotSimulation` como administrador de contexto y manejar su cierre en `finally`.
- [La comparación entre niveles puede usar reportes de distintas fechas o semillas] → Mostrar el nivel y los metadatos disponibles de cada reporte; no presentar comparaciones como ejecuciones emparejadas.

## Migration Plan

No requiere migración. Los grafos ya existentes siguen siendo válidos; se pueden regenerar para producir geometría y reportes. Los resúmenes JSONL solo aparecen cuando se solicita persistencia. La reversión consiste en retirar el grupo opcional y el entry point, sin alterar ni eliminar los archivos de datos.
