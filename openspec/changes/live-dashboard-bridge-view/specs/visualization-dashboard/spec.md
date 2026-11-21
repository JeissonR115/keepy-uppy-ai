# Spec Delta

## MODIFIED Requirements

### Requirement: Offer live simulation only when configured
La página en vivo SHALL permitir observar una partida interactiva existente a través de un host y puerto de puente configurados, SHALL mostrar posiciones de los bots, del globo, el turno, la acción y la ruta activa cuando estén disponibles, y SHALL no iniciar ni controlar una simulación sustituta.

#### Scenario: Live bridge is configured
- **WHEN** el panel tiene una dirección y puerto válidos y el puente ya está ejecutando una partida
- **THEN** la página en vivo se conecta como observador y muestra el estado actualizado de esa partida

#### Scenario: Live bridge is unavailable
- **WHEN** el host o puerto no están disponibles o el puerto no cumple el protocolo
- **THEN** la página informa explícitamente el fallo y mantiene disponibles las páginas basadas en archivos

#### Scenario: Host and port are missing
- **WHEN** no se configura una dirección o puerto de observación
- **THEN** la página en vivo informa que falta la configuración y no inicia Godot ni una simulación headless

#### Scenario: Godot executable is configured
- **WHEN** `GODOT_BIN` y `GODOT_PROJECT_PATH` existen pero el puerto no tiene una partida activa
- **THEN** el panel no inicia automáticamente una partida sustituta y continúa mostrando el estado de desconexión

#### Scenario: Godot is configured
- **WHEN** el panel tiene `GODOT_BIN` válido y puede iniciar o conectar con la simulación
- **THEN** la página en vivo permite observar una partida interactiva existente si el puerto configurado está disponible

#### Scenario: Godot is unavailable
- **WHEN** no hay `GODOT_BIN` configurado o ejecutable
- **THEN** el panel desactiva el modo headless y mantiene disponibles las páginas basadas en archivos, sin impedir el intento de observar un puente loopback ya activo
