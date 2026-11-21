# visualization-dashboard Specification

## Purpose
Ofrece una interfaz local para explorar visualmente los niveles, las métricas de navegación y los episodios guardados, usando los artefactos persistidos por las herramientas del proyecto.

## Requirements

### Requirement: Install and launch the dashboard optionally
El proyecto SHALL proporcionar el comando `uv run keepy-dashboard` con sus dependencias de visualización en el grupo opcional `viz`, sin instalarlas mediante la sincronización base.

#### Scenario: Install the base project
- **WHEN** se ejecuta `uv sync` sin grupos opcionales
- **THEN** Streamlit y Plotly no se instalan como dependencias del proyecto

#### Scenario: Launch the dashboard
- **WHEN** se instala el grupo `viz` y se ejecuta `uv run keepy-dashboard`
- **THEN** se abre el panel local con las páginas disponibles

### Requirement: Inspect a navigation level
La página de niveles SHALL permitir seleccionar un nivel y mostrar su geometría como fondo, nodos y transiciones aceptadas por acción, nodos inalcanzables y candidatos descartados con una distinción visual clara.

#### Scenario: Explore a generated level
- **WHEN** se selecciona un nivel con geometría, grafo y reporte válidos
- **THEN** el panel muestra los datos espaciales del nivel con identificadores, posición, costo y motivo de rechazo en los tooltips aplicables

#### Scenario: Filter edges by action
- **WHEN** el usuario cambia los tipos de acción visibles
- **THEN** la vista actualiza las aristas aceptadas para mostrar solo los tipos seleccionados

#### Scenario: Level artifacts are missing
- **WHEN** no existen todos los archivos requeridos para un nivel
- **THEN** la página informa qué artefactos faltan y sigue permitiendo explorar niveles completos

### Requirement: Compare graph metrics across levels
La página de métricas SHALL presentar conteos y resultados de ruta por nivel en tablas y gráficos, y permitir comparar los niveles cuyos reportes estén disponibles.

#### Scenario: Compare generated levels
- **WHEN** hay reportes de varios niveles
- **THEN** la página muestra sus conteos de nodos, aristas por acción, descartes, inalcanzables y estado de ruta en una comparación común

### Requirement: Analyze saved episodes
La página de episodios SHALL permitir cargar archivos JSONL y mostrar puntos, faltas, motivo de fin y duración de los episodios válidos.

#### Scenario: Load an episode history
- **WHEN** se selecciona un archivo JSONL con resúmenes de episodios
- **THEN** la página presenta los valores disponibles por episodio y distribuciones comparables

#### Scenario: Episode file contains invalid records
- **WHEN** una línea del archivo seleccionado no contiene un resumen válido
- **THEN** la página identifica la línea inválida sin ocultar el error

### Requirement: Offer live simulation only when configured
La página en vivo SHALL estar disponible únicamente cuando exista una configuración ejecutable de Godot y SHALL mostrar posiciones de los bots, del globo y la ruta activa mientras recibe observaciones.

#### Scenario: Godot is configured
- **WHEN** el panel detecta `GODOT_BIN` válido y puede iniciar o conectar con la simulación
- **THEN** la página en vivo permite observar el estado de la simulación y su ruta activa

#### Scenario: Godot is unavailable
- **WHEN** no hay `GODOT_BIN` configurado o ejecutable
- **THEN** el panel desactiva la página en vivo y mantiene disponibles las páginas basadas en archivos
