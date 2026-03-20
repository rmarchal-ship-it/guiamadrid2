# DEATH WAR — Resumen Técnico Completo

**Archivo**: `/tmp/deathwar.html` (~2300 líneas)
**Tipo**: FPS single-file HTML5 con raycasting 2D en Canvas
**Idioma UI**: Español | **Código**: JavaScript vanilla
**Tecnologías**: Canvas 2D, Web Audio API, localStorage, Pointer Lock API

---

## Arquitectura

Un solo archivo HTML contiene CSS + HTML + JavaScript. Motor de raycasting DDA que renderiza un mundo 3D falso desde un mapa 2D de tiles. Sin dependencias externas.

### Estructura del archivo
| Sección | Líneas aprox | Contenido |
|---------|-------------|-----------|
| CSS | 6-31 | Estilos menú, botones, animaciones |
| HTML DOM | 35-107 | Menú inicio, selección capítulo, briefing, HUD, game over, victoria |
| Config/Constantes | 108-140 | Dificultades, velocidades, canvas |
| Audio | 144-433 | SFX sintetizados, música adaptativa por capas |
| Mapa/Generación | 435-574 | resizeMap, generateForestMap, generateDungeonMap, generateRuinsMap |
| Jugador/Armas | 576-600 | WEAPONS, inventario (max 4 slots), pickups |
| Historia/Capítulos | 656-887 | CHAPTERS[], objetivos, briefing, progresión |
| Controles | 910-945 | Teclado (WASD/QE/1234/J/Y), ratón (pointer lock) |
| Reset/Init | 1022-1032 | resetGame() |
| Raycasting | 1033-1105 | castRay() DDA, renderScene() con cielo/suelo/niebla |
| Renderizado entidades | 1106-1270 | Sprites enemigos/boss con z-buffer, animaciones |
| HUD | 1268-1397 | Barra inferior: HP + inventario + kills/rescate + minimapa |
| Arma 1ª persona | 1399-1444 | Espada animada / pistola con flash |
| Minimapa | 1445-1474 | 100x100px, fog-of-war |
| Movimiento | 1477-1537 | Velocidad con fricción, colisiones 4 puntos |
| Disparo | 1538-1575 | shoot() con cono de precisión, melee vs ranged |
| IA enemigos | 1577-1608 | Patrulla aleatoria, persecución <10 tiles, disparo por precisión |
| Pickups render | 1610-1655 | Bobbing, colores por tipo |
| Objetivos/Historia | 1709-1815 | HUD objetivos, puerta mazmorra, rescate rehén |
| Cutscene Cap2 | 1817-2052 | 5 fases: celebración→explosión→inconsciencia→radio→gameplay |
| Personas enterradas | 2055-2120 | Visión rayos-X, esqueletos bajo escombros |
| loadRuinsMap | 2126-2180 | Inicialización Cap2: gafas + 8 enterrados |
| Game Loop | 2178-2305 | requestAnimationFrame, update+render 60fps |

---

## Sistemas de Juego

### Movimiento
- **Velocidad con inercia**: ACCEL=0.008, FRICTION=0.82
- **Rotación suave**: ROT_ACCEL=0.004, ROT_FRICTION=0.80
- **Colisión**: 4 puntos con margen 0.2 (canMove)
- **Fog of war**: FOG_RADIUS=4 tiles, se revela al caminar

### Combate
- **5 armas**: Espada (melee, 50dmg), Pistola (15dmg, ∞ammo), Escopeta (40dmg, 8), Rifle (30dmg, 12), SMG (18dmg, 20)
- **Inventario**: Max 4 slots. Espada+Pistola fijos. Escopeta/Rifle/SMG como loot
- **Cambio arma**: Teclas 1-4
- **Melee**: Arco ancho (0.6), rango 1.8 tiles
- **Ranged**: Raycast con cono de precisión
- **Pistola**: Munición compartida (ammo general). Otras armas: ammo propio, se descarta al vaciarse

### IA Enemigos
- **Patrulla**: Movimiento aleatorio con cambio de dirección cada 60-120 frames
- **Detección**: Radio 10 tiles
- **Persecución**: Se mueve hacia el jugador, velocidad ESPEED=0.012
- **Disparo**: Según dificultad (shootRate, accuracy)
- **Boss**: HP 500, multiplicador daño x3, tamaño sprite mayor

### Dificultades (5 niveles)
| Nivel | pDmg | eDmg | eHP | shootRate | accuracy |
|-------|------|------|-----|-----------|----------|
| FACIL | 25 | 10 | 50 | 80 | 0.2 |
| NORMAL | 15 | 25 | 100 | 50 | 0.4 |
| MEDIO | 12 | 30 | 120 | 40 | 0.5 |
| PRO | 10 | 40 | 150 | 30 | 0.6 |
| MUY DIFICIL | 8 | 50 | 200 | 20 | 0.7 |

### Generación de Mapas
- **Bosque** (32x32): Hash-based con densidad 40%, spawn despejado (1-5,1-5), puerta aleatoria lejos del spawn
- **Mazmorra** (32x32): Patrón de cruz de corredores, 10 salas talladas, paredes tipo 5-7
- **Ruinas** (32x32): 12 salas de escombros, 3 corredores spine H + 3 V (filas/cols 8,16,24), paredes tipo 8-10

### Rendering
- **Raycasting DDA**: 60 iteraciones max, strips de 2px
- **FOV**: π/3 normal, π/5 apuntando (right-click)
- **Z-buffer**: Float32Array de 800 elementos
- **Distancia max render**: 20 tiles con fog
- **Sprites**: Billboard con animación de caminar y muerte
- **Efectos**: Flash disparo (naranja), flash daño (rojo), viñeta borde, low-HP rojo

---

## Sistema de Historia

### Capítulo 1: RESCATE — "Operación Sombra Roja"
- **Fase 0 (Bosque)**: Encontrar llave, localizar puerta de mazmorra
- **Fase 1 (Mazmorra)**: Matar al boss Coronel Volkov "El Martillo" (500HP), rescatar Sargento Reyes
- **8 enemigos** + 1 boss
- **Briefing**: 7 mensajes de radio del comandante

### Capítulo 2: ENTRE RUINAS — "Silencio en la Frecuencia"
- **Cutscene**: 5 fases (celebración → explosión → inconsciencia → radio estática → despertar)
- **Fase 2 (Ruinas 32x32)**: Sin combate, sin armas
- **Misión**: Encontrar gafas rayos-X (centro mapa 15.5,15.5), rescatar 8 personas enterradas
- **Mecánica rescate**: Acercarse + pulsar Y, cavar durante digTimer
- **Ending**: Secuencia de 8 diálogos buscando a Reyes y Comandante → "CONTINUARÁ..."

### Progresión
- **localStorage** key `dw_story`: `{unlocked: N}`
- Capítulo N+1 se desbloquea al completar capítulo N
- 5 capítulos en el selector (3 bloqueados como "PROXIMAMENTE")

---

## Audio

### SFX (sintetizados con Web Audio API)
- `snd(freq, dur, type, vol)` — oscilador básico con decay exponencial
- `sndShot()` — sawtooth+square para disparo
- `sndHit()` — sine+sawtooth para impacto
- `sndHurt()` — sawtooth para daño al jugador
- `sndWin()` — melodía 3 notas (Do-Mi-Sol)

### Música Adaptativa (6 estados)
| Estado | Trigger | Carácter |
|--------|---------|----------|
| explore | Sin enemigos cerca | Drones graves 42/63Hz, viento filtrado, susurros |
| combat | Enemigo <10 tiles | Drones 38/57Hz, rumble, heartbeat cada 2s |
| boss | Boss <12 tiles | Drones muy graves 30/45Hz, tension hits, heartbeat 1.1s |
| dungeon | En mazmorra, sin combate | Sub-bass 30/45Hz, goteos aleatorios reverberados |
| dungeon_combat | En mazmorra + enemigo cerca | Mix dungeon+combat |
| victory/gameover | Fin de partida | Melodía o silencio |

### Arquitectura audio
- Master gain (MUSIC_VOL=0.12) → destination
- Delay node 350ms + feedback 0.3 + lowpass 800Hz = reverb
- Noise buffer 2s precalculado para capas de ruido

---

## HUD

### Barra inferior (full width)
- **HP bar** (izq): 110px, color verde→amarillo→rojo según salud
- **Slots inventario** (centro): Ancho dinámico, clip() para overflow, auto-shrink con measureText
- **Kills** (der): "KILLS X/Y" + "X vivos" / "CLEAR" (no en Cap2)
- **Rescate** (der, solo Cap2): "RESCATE X/8" + indicador RAYOS-X

### Otros elementos HUD
- **Crosshair**: Verde normal, rojo apuntando, amarillo al disparar
- **Minimapa**: 100x100px esquina inferior derecha, fog-of-war
- **Objetivos**: Panel semi-transparente con checklist ✓/○
- **Brújula Cap2**: Flecha apuntando a gafas rayos-X antes de recogerlas
- **Dificultad**: Nombre + daños top-left
- **FPS**: Top-left

---

## Controles
| Tecla | Acción |
|-------|--------|
| W/↑ | Avanzar |
| S/↓ | Retroceder |
| A/← | Girar izquierda |
| D/→ | Girar derecha |
| Q | Strafe izquierda |
| E | Strafe derecha |
| Click/J | Disparar/Atacar |
| Right-click | Apuntar (zoom) |
| 1-4 | Cambiar arma |
| Y | Interactuar (rescatar) |
| SPACE | Pausa |
| Ratón | Apuntar (pointer lock) |

---

## Funciones Principales

| Función | Línea | Qué hace |
|---------|-------|----------|
| generateForestMap() | 463 | Genera bosque procedural 32x32 |
| generateDungeonMap() | 493 | Genera mazmorra con salas y corredores |
| generateRuinsMap() | 519 | Genera ruinas 32x32 con escombros |
| castRay() | 1033 | Algoritmo DDA de raycasting |
| renderScene() | 1055 | Renderiza mundo 3D (paredes, cielo, suelo, fog) |
| renderEntities() | 1106 | Renderiza enemigos como sprites billboard |
| renderHUD() | 1268 | Dibuja toda la interfaz de juego |
| renderWeapon() | 1399 | Arma en primera persona (espada/pistola) |
| renderMinimap() | 1445 | Mini-radar con fog of war |
| updatePlayer() | 1484 | Input, movimiento con inercia, disparo |
| shoot() | 1538 | Lógica de disparo (melee + ranged) |
| updateEntities() | 1577 | IA enemigos (patrulla, persecución, disparo) |
| checkPickups() | 602 | Recogida de items |
| resetGame() | 1022 | Reinicializa estado completo |
| startCutscene() | 1829 | Inicia cinemática Cap2 |
| renderCutscene() | 1861 | Renderiza cinemática por fases |
| loadRuinsMap() | 2126 | Carga Cap2: gafas + enterrados |
| renderBuriedPeople() | 2055 | Visión rayos-X de enterrados |
| checkStoryObjectives() | 841 | Verifica y actualiza objetivos |
| gameLoop() | 2178 | Bucle principal 60fps |

---

## Servidor de desarrollo

```bash
# En /tmp/ con el archivo deathwar.html
ruby -run -e httpd /tmp -p 8765
# Abrir: http://localhost:8765/deathwar.html
```

O con el launch.json de Claude Preview (nombre: "war-zone", puerto 8765).
