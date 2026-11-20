# Tasks

## 1. Persistencia de geometría y reportes de grafos

- [x] 1.1 Extender el flujo de generación para guardar payloads de geometría y reportes JSON completos en `geometry/` y `reports/`, con directorios configurables y escrituras seguras; verificar con pruebas unitarias que grafo, reporte, geometría y stdout coincidan.
- [x] 1.2 Actualizar la CLI `generate-graph` con opciones de directorio para reportes y geometría, y documentar los nuevos artefactos y opciones en `docs/graph-generation.md`; verificar la ayuda y ejemplos documentados.

## 2. Persistencia y carga de episodios

- [x] 2.1 Añadir opción de persistencia fechada JSONL a `run-episode`, acumular eventos `fault` y mantener stdout; verificar escritura de varias líneas, append en fecha repetida, conteo de faltas y preservación de salida actual en pruebas.
- [x] 2.2 Crear funciones independientes de la UI para descubrir, cargar y validar grafos, reportes, geometría y episodios JSONL, y transformar datos para vistas espaciales y métricas; verificar esquemas válidos, archivos ausentes, JSON inválido y líneas JSONL defectuosas sin requerir Godot.

## 3. Panel offline

- [x] 3.1 Añadir Streamlit y Plotly al grupo opcional `viz` y registrar `keepy-dashboard`; verificar que la sincronización base no incluya estas bibliotecas y que la CLI exponga el entry point.
- [x] 3.2 Implementar las páginas Niveles, Métricas y Episodios usando exclusivamente la capa de datos, con filtros, tooltips, estados vacíos y errores identificables; verificar transformaciones en pruebas y recorrer el panel con artefactos de ejemplo.
- [x] 3.3 Documentar instalación opcional, comando, páginas, formatos de archivos y capturas en `docs/dashboard.md`, y enlazarlo desde `README.md`; verificar que los comandos documentados correspondan a la CLI.

## 4. Vista en vivo e integración

- [x] 4.1 Añadir página en vivo condicionada por la configuración ejecutable de Godot, reutilizando launcher y cliente, mostrando bots, globo y ruta activa y cerrando recursos al salir; verificar visibilidad sin Godot y ciclo de vida en una prueba de integración marcada como opcional.
- [x] 4.2 Validar el cambio completo con las pruebas nuevas y existentes, ejecutar `openspec validate visualization-dashboard` y comprobar que cuatro conjuntos de artefactos generados pueden abrirse offline.
