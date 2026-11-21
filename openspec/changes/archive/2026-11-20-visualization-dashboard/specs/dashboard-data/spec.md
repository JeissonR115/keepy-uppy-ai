# Spec Delta

## Purpose

Define los artefactos locales y las operaciones de lectura que permiten inspeccionar grafos, geometría y episodios sin ejecutar Godot ni depender de la salida de una ejecución anterior.

## ADDED Requirements

### Requirement: Persist graph generation reports
El generador SHALL guardar en `reports/<level>.json` un reporte legible por máquina que incluya los conteos de nodos y aristas por acción, cada candidato descartado con origen, destino, acción, motivo y resultado del sondeo, los nodos inalcanzables y el resultado completo de comprobación de ruta.

#### Scenario: Generate and persist a level report
- **WHEN** termina la generación de un grafo para un nivel
- **THEN** el reporte guardado corresponde a ese nivel y contiene los mismos resultados que el reporte JSON emitido por stdout

#### Scenario: Preserve rejected probe details
- **WHEN** se descarta un candidato de transición
- **THEN** el reporte guardado conserva su identificador de origen y destino, tipo de acción, motivo y datos del sondeo

### Requirement: Persist exported level geometry
El generador SHALL guardar la geometría schema-version-one recibida del puente en `geometry/<level>.json` sin perder campos del contrato.

#### Scenario: Generate geometry for offline inspection
- **WHEN** se genera un grafo para un nivel
- **THEN** la copia de geometría del nivel queda disponible como JSON válido y puede leerse sin conexión a Godot

### Requirement: Save episode summaries as JSONL
El comando de episodios SHALL permitir escribir cada resumen completado en `episodes/<date>.jsonl`, un objeto JSON por línea, preservando la emisión existente por stdout.

#### Scenario: Save a completed episode
- **WHEN** una ejecución solicita persistencia y termina un episodio
- **THEN** se añade una línea JSON con nivel, semilla, pasos, estado terminal, motivo, evento, cantidad de eventos `fault` y puntuación

#### Scenario: Append episodes from the same date
- **WHEN** otro episodio del mismo día se guarda en el mismo archivo
- **THEN** el comando añade una nueva línea sin reemplazar los resúmenes anteriores

### Requirement: Read dashboard data with validation
Las funciones de carga de datos SHALL validar los esquemas admitidos y la forma de los registros antes de devolver datos para visualización, e informar de forma identificable sobre archivos ausentes o inválidos.

#### Scenario: Load valid stored artifacts
- **WHEN** se cargan un grafo, un reporte, una geometría o un archivo JSONL válidos
- **THEN** los datos se devuelven estructurados y asociados con su nivel o episodio

#### Scenario: Reject malformed stored data
- **WHEN** un archivo requerido tiene JSON inválido, un esquema no admitido o campos esenciales ausentes
- **THEN** la carga devuelve un error identificable que indica el archivo y el problema
