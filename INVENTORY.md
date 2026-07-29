# Inventario de piezas

Estado físico de las piezas del rig. `BOM.csv` es la lista de compra; esto es qué
hay realmente en la mano. Adrián reporta las llegadas conforme caen.

Última actualización: 2026-07-27

## En la mano

| Pieza | Notas |
|---|---|
| Raspberry Pi 4 + microSD | ya se tenía |
| Probeta graduada | ya se tenía |
| Manómetro de carátula | ya se tenía; sirve de referencia para calibrar el transductor |
| Válvula de bola de aire (SS, verde) | ya se tenía; es la que va a mover el servo |
| IRLZ44N MOSFET (pack de 10) | llegó 2026-07-27 |
| V1738 bloque de terminales enchufable (3 polos) | llegó 2026-07-27; ya está en `BOM.csv` a $0.00 (compra propia de Adrián, fuera del pedido de Roxanne). Precio y link **pendientes**. Uso recomendado: bobina del diverter en polos 1–2, polo 3 muerto = llave anti-inversión (ver `docs/ASSEMBLY.md`) |
| Fuente 12 V 3 A | llegó 2026-07-27; asumido barrel 5.5×2.1 (B013OVYRZU) |
| Protoboard 830 + jumpers | confirmado por Adrián 2026-07-27 |
| Cable 22AWG stranded | confirmado por Adrián 2026-07-27 |
| UBEC 12 V→6 V 3 A | confirmado por Adrián. Ojo: el BOM dice 6 V y `ASSEMBLY.md` menciona 6.8 V en el criterio de par — ver "Discrepancias abiertas" |
| Servo DS3218 | confirmado por Adrián. **No energizar todavía** (ver bloqueos) |
| ADS1115 ADC (HiLetgo) | confirmado por Adrián. El "hilego" del chat era esta pieza |
| Kit de resistencias 1 % | confirmado por Adrián; verificado que trae 22 kΩ (por eso el divisor es 10k/22k y no 10k/20k) |
| Sonda DS18B20 waterproof | llegó 2026-07-27; era el item #4 del pedido. Desbloquea la cadena de temperatura completa |
| **Transductor 0–15 PSI, 0.5–4.5 V, G1/4** | llegó 2026-07-27; item #1, el prioritario. **Cierra la cadena de sensado completa**: transductor → divisor 10k/22k → ADS1115 → Pi. Para MONTARLO en el rig falta el adaptador G1/4 → Swagelok (estado desconocido) |
| Kit de capacitores electrolíticos (470 / 1000 µF) | llegó 2026-07-27; item #8. **No desbloquea nada todavía**: van al riel de 12 V, que sigue trabado por el fusible |

## Se puede hacer HOY — sin que falte nada

La cadena de sensado de baja tensión **no depende del riel de 12 V**, así que no la
bloquean ni el fusible ni el diodo. Con lo que ya hay en la mano:

1. **Montar el ADS1115 en el protoboard** y cablearlo al Pi (VDD→3.3 V, GND→tierra
   común, SDA→GPIO2, SCL→GPIO3, ADDR→GND). Ver `docs/wiring_ads1115.png`.
2. **Confirmar el bus:** `i2cdetect -y 1` debe mostrar `0x48`. Esto valida el módulo
   y el cableado I²C sin ninguna pieza faltante.
3. **Armar el divisor 10k/22k y MEDIR su ratio real** — alimenta la entrada con un
   voltaje conocido del Pi (3.3 V o 5 V), mide entrada y salida y divide. Ese número
   va a `sensor.divider_ratio` en `config.yaml`. **Es gating para un `k` publicable**
   (un 3 % de error aquí sesga `k` un 3 % con el R² intacto). No necesita el
   transductor.

4. **Cablear la sonda DS18B20** (dato→GPIO4, + pull-up 4.7k a 3.3 V) y verla
   enumerar. **Ojo — bloqueo mecánico:** las tres puntas de la sonda son de
   conductor **trenzado**, y un clip de protoboard está hecho para conductor
   sólido: no se sostienen en la fila. El cable 22AWG del inventario también es
   trenzado. Hay que resolverlo antes (soldar colas de conductor sólido, o
   crimpear puntas dupont); estañar la punta *sirve* en protoboard pero es
   segundo mejor, y bajo tornillo (V1738) **no** se hace, porque el estaño fluye
   y la unión se afloja — eso ya lo dice `docs/ASSEMBLY.md`.
   Requiere habilitar 1-Wire **y reiniciar** la primera vez:

   ```
   sudo raspi-config nonint do_onewire 0   # luego reboot
   ls /sys/bus/w1/devices/                 # debe aparecer un 28-…
   ```

   Gotcha del driver: `Ds18b20` resuelve la ruta `/sys/bus/w1/devices/28-*` **una
   sola vez al construirse**, así que conectar la sonda con la app corriendo no
   sirve — hay que reiniciar la app. Y cuando la sonda quede montada en el chorro
   de permeato hay que cambiar `temperature.source` de `manual` a `probe` en
   `config.yaml`; hoy sigue en `manual`, que reporta ruido simulado, no medición.

5. **Verificar el transductor EN LA MESA, sin montarlo en el rig.** Es lo mejor que
   habilitó su llegada, porque separa la cadena eléctrica del montaje mecánico.

   Aliméntalo con los **5 V del Pi** (pin 2) — es ratiométrico, así que su salida
   depende de esa alimentación y no de otra — y mete su señal al divisor. A
   presión atmosférica la cadena debe dar exactamente esto:

   | Punto | Valor esperado |
   |---|---|
   | Salida del transductor | 0.500 V |
   | A0 del ADS1115 (tras el divisor ×0.6875) | **0.3438 V** |
   | Lo que reporta el driver | **0.000 kPa** |

   Si sale ese número, quedan validados **de una vez sensor, divisor, ADC y
   conversión**. Si sale distinto, el problema está en la cadena eléctrica y no en
   el montaje — que es justo lo que conviene separar antes de meter presión.

   **Segundo punto en la mesa: columna de agua.** `P = ρ·g·h`, con agua a 9.81 kPa
   por metro. Es el único patrón de presión gratis, seguro y trazable que hay sin
   el rig montado:

   | Altura | Presión |
   |---|---|
   | 0.5 m | 4.91 kPa |
   | 1.0 m | 9.81 kPa |
   | 2.0 m | 19.62 kPa |
   | 3.57 m | 35.02 kPa (el punto de trabajo) |

   **Pero ojo con el alcance real de esto:** el punto de atmósfera no necesita
   ningún fitting — se alimenta y se lee. El segundo punto **sí necesita sellar
   contra la rosca G1/4**, y ese adaptador no está confirmado. Sin él, hoy solo se
   puede hacer el punto de cero. No improvises un sello con manguera a presión.

   La calibración formal de 2 puntos sigue siendo contra el **Keller LEX1**, no
   contra la columna (ver `docs/ASSEMBLY.md`).

Los pasos 1, 2 y 4 no necesitan multímetro. El 3 sí — **pero hay una alternativa
sin multímetro**: `sensor.ads_channel` es 0, así que **A1 del ADS1115 está libre**.
Metiendo la entrada del divisor también a A1, el ratio sale como `A0/A1` leído por
el mismo ADC, y los errores de ganancia y de referencia **se cancelan en el
cociente** — sale mejor que con un multímetro barato. Requiere un script corto con
`adafruit_ads1x15` (el rig solo lee A0). Propuesta sin verificar; ver
`docs/wiring_protoboard.html`.

## Pendiente de compra

Los 10 items del correo a Roxanne (borrador sin enviar). Los tres primeros son
prioridad.

| # | Pieza | Link |
|---|---|---|
| 2 | Solenoide 3 vías 12 V para agua (231Y-6-12VDC) | ESValves |
| 3 | Válvula de alivio ajustable 0–20 PSI | B01KO7NVYK |
| 5 | Adaptador 1/4" NPT-M × barb (×3) | B07VJK7KML |
| 6 | Barrel jack 5.5×2.1 → terminal de tornillo | B077QD4G3Q |
| 7 | Portafusibles inline + fusible 3 A | B088FNTJDV |
| 9 | Termorretráctil 650 pzas 2:1 | B07WWWPR2X |
| 10 | Kit de tornillos M4 | B0FGV8F6G7 |

### Falta y no está en el correo

| Pieza | Por qué importa |
|---|---|
| **Diodo 1N5819 (flyback)** | **crítico** — confirmado por Adrián que NO ha llegado. Sin él, al cortar la bobina el pico inverso mata el IRLZ44N. El diverter no se energiza sin este diodo montado |
| Tubería de silicón 1/4" ID | línea de permeato |
| Kit de barbs barb-a-barb | uniones de la tubería |
| PTFE thread-seal tape | juntas NPT del diverter |
| Abrazaderas de manguera | cada junta barb-silicón |
| Fittings Swagelok / McMaster | orden de McMaster ya colocada por Roxanne — ¿llegó? |
| Enclosure + coupling servo | impresión 3D propia |
| Multímetro | necesario para medir `divider_ratio` y para la calibración de 2 puntos |

## Bloqueos activos

- **No energizar el riel de 12 V sin el fusible de 3 A** (item #7, no ha llegado).
  La fuente ya está en la mano y el protoboard también, así que la tentación es
  real: se puede cablear todo, pero no se conecta la fuente.
- **No energizar el diverter sin el 1N5819 montado** en paralelo a la bobina.
- **No energizar ni acoplar el servo.** `ServoValve` lo manda a 700 µs solo al
  arrancar en modo hardware y `servo_close_us` sigue en 0 (sin calibrar). La
  calibración de extremos va con la válvula DESACOPLADA del vástago.

## Presión de ensayo: 35 kPa — confirmado (2026-07-27)

**RESUELTO — falsa alarma, y el diseño actual NO cambia.** Adrián dijo primero
"pruebas de hasta 40 PSI", pero fue confusión de unidades: **sus ensayos son de
35 kPa** (= 5.08 PSI = 0.35 bar). Eso cabe cómodo en todo lo que ya está
dimensionado. Nada del rig se rediseña.

| Capa | kPa | margen sobre 35 kPa |
|---|---|---|
| setpoints configurados (max) | 60.0 | 1.7× |
| límite del espécimen | 65.0 | 1.9× |
| corte global de software | 80.0 | 2.3× |
| alivio mecánico | ~90.0 | 2.6× |
| tope del transductor 0–15 PSI | 103.4 | 3.0× |
| tope del Keller LEX1 (2 bar) | 200.0 | 5.7× |

El ensayo usa el **34 % del span** del transductor de 0–15 PSI — la zona correcta.
Exactitud ±1 % FS = ±1.03 kPa = **±3.0 %** en el punto de 35 kPa.

**El transductor 0–15 PSI del pedido (item #1) es el correcto. No se cambia.**

### Lo que SÍ sigue mal: el alivio (item #3)

Único punto vivo, y ahora está **más apretado** que antes:

`BOM.csv` especifica un **CR25-100** (ajustable 0–100 psi). Pero `INVENTORY` item #3
dice "ajustable 0–20 PSI" con ASIN `B01KO7NVYK`, que al rastrearlo apunta a un
Midwest CPR-25 anunciado como **"5 Psi"** — dato de título de búsqueda, sin
confirmar porque la página devuelve error.

Si ese alivio es de **5 psi fijos = 34.5 kPa**, se abre **por debajo del ensayo de
35 kPa**: ventearía durante toda la prueba. Un alivio por debajo de la presión de
trabajo no protege — impide trabajar, que es lo que empuja a quitarlo.

**Confirmar antes de ordenar:** que sea ajustable y que su rango cubra un punto de
consigna de ~90 kPa (13 psi), por debajo del límite del recipiente.

### Sigue sin documentarse

**El rating de presión del recipiente y su brida.** `ASSEMBLY.md` manda fijar el
alivio "below the vessel's limit" y ese límite no existe escrito en ningún archivo
del repo. A 35 kPa el margen es cómodo, pero el número debería estar registrado.

## Discrepancias abiertas

- **UBEC 6 V vs 6.8 V.** `BOM.csv` y `ASSEMBLY.md:88` dicen 6 V; `ASSEMBLY.md:40`
  y `:62` y `.claude/roles/hardware.md:32` usan 6.8 V para el criterio de par
  ("≤1.0 N·m → DS3218 pelón"). Ese umbral de 1.0 N·m es un valor **derivado** de
  suponer 6.8 V: a 6 V hay menos par y el umbral debe apretarse. En revisión.
