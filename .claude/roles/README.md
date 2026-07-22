# Roles de agente — membrane-rig

Este repo se trabaja con **6 sesiones de Claude Code**, una por área. El contexto
compartido está en [`CLAUDE.md`](../../CLAUDE.md) (léelo siempre); tu rol
específico está en este directorio.

| Rol | Archivo | Área |
|---|---|---|
| General | [`general.md`](general.md) | Coordinación, Raspberry Pi, despliegue, memoria |
| Control | [`control.md`](control.md) | Lazo PID, secuenciador, seguridad, playlist |
| Hardware | [`hardware.md`](hardware.md) | Drivers HAL, BOM, cableado, calibración |
| Datos | [`datos.md`](datos.md) | Análisis de Darcy, gráficas, Excel, logging |
| Interfaz | [`ui.md`](ui.md) | UI web y CLI, apps de Mac |
| Paper | [`paper.md`](paper.md) | Paper científico, README, docs de laboratorio |

## Cómo arrancar una sesión

Abre una sesión nueva de Claude Code en `~/Desktop/membrane-rig` y pégale:

```
Eres el agente <Rol> de membrane-rig. Lee CLAUDE.md y .claude/roles/<archivo>.md
antes de hacer nada, y confírmame que entendiste tu área.
```

Ponle a la sesión el título **`Membrane Rig — <Rol>`** para ubicarla después.

## Reglas que aplican a todos

- Todos trabajan en el checkout principal `~/Desktop/membrane-rig`. No hay
  worktrees: las áreas son disjuntas y el `.venv` vive aquí.
- `git pull` antes de tocar. `commit` + `push` al terminar, a nombre de Adrián.
- Si necesitas algo de otra área, **no lo edites**: manda mensaje a esa sesión.
- Ningún agente afloja los límites de presión. Ver la escalera en `CLAUDE.md`.
- Todo resultado de simulación se etiqueta como tal hasta validarlo en el rig.
