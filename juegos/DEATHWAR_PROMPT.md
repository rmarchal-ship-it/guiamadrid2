# Prompt para recuperar contexto del juego DEATH WAR

Copia y pega esto en un nuevo terminal de Claude Code:

---

```
Lee el archivo /tmp/deathwar.html y el resumen en juegos/DEATHWAR_RESUMEN.md.

Es un FPS single-file HTML5 con raycasting (Canvas 2D) y audio sintetizado (Web Audio API). Todo en un solo archivo, sin dependencias. Idioma de la UI: español.

## Estado actual del juego

### Lo que funciona:
- Motor raycasting DDA completo con fog, z-buffer, sprites billboard
- 2 modos: Partida Rápida (arena combat) y Modo Historia (capítulos)
- Capítulo 1: bosque → mazmorra → boss Volkov → rescatar Sargento Reyes
- Capítulo 2: cutscene explosión → ruinas 32x32 → gafas rayos-X → rescatar 8 enterrados → ending "CONTINUARÁ"
- Inventario de armas: 4 slots max (espada melee + pistola + 2 pickups de escopeta/rifle/SMG)
- 5 niveles de dificultad con stats diferentes
- Música adaptativa por capas (6 estados: explore/combat/boss/dungeon/dungeon_combat/victory)
- HUD completo: barra HP, slots inventario con clip(), kills, minimapa, objetivos
- Movimiento con inercia (velocidad + fricción)
- Progresión con localStorage (desbloqueo capítulos)
- Fog of war en minimapa

### Capítulos pendientes:
- Capítulo 3, 4, 5 están como "PRÓXIMAMENTE" en el selector

## Reglas de desarrollo

1. **NUNCA modifiques sistemas que funcionan** sin que te lo pida explícitamente
2. **Archivo único**: todo va en deathwar.html, no crear archivos separados
3. **Al añadir features**: integrar en el código existente, no duplicar funciones
4. **Mapas**: usar resizeMap(w,h) para cambiar tamaño. Generadores: generateForestMap/generateDungeonMap/generateRuinsMap
5. **Armas nuevas**: añadir a WEAPONS{} y a WEAPON_KEYS[] si son loot
6. **Capítulos nuevos**: añadir al array CHAPTERS[] con nombre, subtítulo, briefing, objetivos, enemigos
7. **Audio**: usar snd(freq,dur,type,vol) para SFX. Para música: añadir estado en getMusicState() y handler en startMusicLayer()
8. **HUD**: renderHUD() maneja toda la interfaz. Usar X.save()/clip()/restore() para textos en slots
9. **Colores de pared**: arrays wallColors[] y wallDark[] indexados por tipo de tile (1-3 bosque, 4 puerta, 5-7 mazmorra, 8-10 ruinas)
10. **NO usar librerías externas** — todo vanilla JS

## Servidor de desarrollo

Para probar el juego:
ruby -run -e httpd /tmp -p 8765
Abrir: http://localhost:8765/deathwar.html

O configurar Claude Preview con launch.json:
{
  "version": "0.0.1",
  "configurations": [{
    "name": "war-zone",
    "runtimeExecutable": "ruby",
    "runtimeArgs": ["-run", "-e", "httpd", "/tmp", "-p", "8765"],
    "port": 8765
  }]
}

## Preferencias del usuario
- Comunicarse en español
- Respuestas concisas, ir al grano
- Implementar directamente, no dar vueltas con planes
- Preguntar antes de cambios grandes
- Verificar cambios visualmente con preview cuando sea posible
```

---

**Nota**: El archivo del juego debe estar en `/tmp/deathwar.html`. Si lo has movido a otra ubicación, cambia la ruta en el prompt.
