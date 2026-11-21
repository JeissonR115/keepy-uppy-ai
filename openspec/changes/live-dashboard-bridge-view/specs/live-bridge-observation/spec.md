# Spec Delta

## Purpose

Permite que una herramienta local observe una partida interactiva conectada al puente de Godot y muestre las decisiones de la política sin controlar ni reiniciar la simulación.

## ADDED Requirements

### Requirement: Attach to an existing live bridge
El observador SHALL conectarse a la dirección y puerto configurados sin iniciar Godot, reiniciar la partida, avanzar pasos físicos ni enviar acciones de juego.

#### Scenario: Live bridge is available
- **WHEN** el observador recibe el saludo de protocolo válido en el puerto configurado
- **THEN** entra en modo de observación y comienza a recibir datos de la partida existente

#### Scenario: Live bridge is unavailable
- **WHEN** el puerto no acepta la conexión o el protocolo no es válido
- **THEN** el observador muestra un error identificable y no intenta iniciar una simulación sustituta

#### Scenario: Match ownership remains external
- **WHEN** el observador está conectado
- **THEN** no envía comandos `reset`, `step`, `close`, ni acciones de jugador

### Requirement: Receive live policy observations
El observador SHALL recibir tick, turno, posiciones y velocidades de ambos jugadores y del globo, puntuación y nivel antes de actualizar su vista.

#### Scenario: Observation belongs to the active match
- **WHEN** llega una observación con una sesión y secuencia válidas
- **THEN** la vista actualiza los datos del nivel activo y el tick correspondiente

#### Scenario: Observation is stale or malformed
- **WHEN** una observación no puede validarse o pertenece a una sesión diferente
- **THEN** el observador informa el problema y conserva explícitamente el último estado válido

### Requirement: Receive live policy decisions
El observador SHALL recibir la acción seleccionada y los metadatos de decisión de la política para el mismo tick o secuencia de observación.

#### Scenario: Decision is available
- **WHEN** la política selecciona una acción y publica su decisión
- **THEN** la vista muestra fase, acción, objetivo o predicción, estado de ruta, IDs de nodos y waypoint

#### Scenario: Decision is unavailable
- **WHEN** la partida continúa pero aún no existe telemetría de decisión
- **THEN** la vista mantiene el estado de observación y muestra que la decisión está pendiente

### Requirement: Stay synchronized with controller and disconnection
El observador SHALL permanecer independiente del cliente controlador y SHALL detenerse limpiamente cuando el puente cierre o cambie de partida.

#### Scenario: Controller remains active
- **WHEN** el observador se conecta además del cliente Python que controla el bot
- **THEN** el cliente controlador conserva sus acciones y el observador no altera el juego

#### Scenario: Bridge disconnects
- **WHEN** se interrumpe el puente o termina la partida
- **THEN** el observador muestra el estado de desconexión y libera su conexión
