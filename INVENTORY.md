# Inventario de piezas

Estado físico de las piezas del rig. `BOM.csv` es la lista de compra; esto es qué
hay realmente en la mano. Adrián reporta las llegadas conforme caen.

Última actualización: 2026-08-04

## En la mano

| Pieza | Notas |
|---|---|
| Raspberry Pi 4 + microSD | ya se tenía. **⚠ PROBLEMA REPORTADO — naturaleza por confirmar.** Deja de contar como pieza sana: es la causa raíz de los días de "no responde" desde 2026-07-29, que se habían atribuido a red. Posible reemplazo. **Si se reemplaza, tiene que ser Pi 4 — ver la restricción abajo** |
| Probeta graduada **1000 mL** | ya se tenía; capacidad confirmada por Adrián 2026-07-30. División menor **por confirmar** (típicamente 10 mL en esta capacidad). **⚠ Con el caudal del sim se llena en 17–35 s, no en los 60 s de `test.collection_s`** — ver abajo |
| Manómetro de carátula | ya se tenía; sirve de referencia para calibrar el transductor |
| Válvula de bola de aire (SS, verde) | ya se tenía; es la que va a mover el servo |
| IRLZ44N MOSFET (pack de 10) | llegó 2026-07-27 |
| V1738 bloque de terminales enchufable (3 polos) | llegó 2026-07-27; ya está en `BOM.csv` a $0.00 (compra propia de Adrián, fuera del pedido de Roxanne). Precio y link **pendientes**. Uso recomendado: bobina del diverter en polos 1–2, polo 3 muerto = llave anti-inversión (ver `docs/ASSEMBLY.md`) |
| Fuente 12 V 3 A | llegó 2026-07-27. **⚠ Su barril NUNCA se midió y los archivos no coinciden**: este inventario decía "asumido 5.5×2.1 (`B013OVYRZU`)" pero `BOM.csv` compró **`B01C010YJI`** — son dos piezas distintas. Ver el bloqueo abajo |
| Protoboard 830 + jumpers | confirmado por Adrián 2026-07-27 |
| Cable 22AWG stranded | confirmado por Adrián 2026-07-27 |
| UBEC 12 V→6 V 3 A | confirmado por Adrián. Jumper a **6 V** (no tiene posición de 6.8 V). Las bandas de par están rederivadas a 6 V en `ASSEMBLY.md` |
| Servo DS3218 | confirmado por Adrián. **No energizar todavía** (ver bloqueos) |
| ADS1115 ADC (HiLetgo) | confirmado por Adrián. El "hilego" del chat era esta pieza |
| Kit de resistencias 1 % | confirmado por Adrián; verificado que trae 22 kΩ (por eso el divisor es 10k/22k y no 10k/20k) |
| Sonda DS18B20 waterproof | llegó 2026-07-27; era el item #4 del pedido. Desbloquea la cadena de temperatura completa |
| **Transductor 0–15 PSI, 0.5–4.5 V, G1/4** | llegó 2026-07-27; item #1, el prioritario. **Cierra la cadena de sensado completa**: transductor → divisor 10k/22k → ADS1115 → Pi. Para MONTARLO en el rig hace falta el adaptador G1/4 → Swagelok — **la orden de McMaster ya llegó**, falta confirmar si lo incluye |
| Kit de capacitores electrolíticos (470 / 1000 µF) | llegó 2026-07-27; item #8. Van al punto estrella del riel de 12 V. **Ya no los bloquea ninguna pieza** — llegaron el fusible (#7) y el barrel jack (#6), que era donde aterrizaba el punto estrella |
| **Solenoide 3 vías 231Y-6-12VDC** | llegó; item #2. **⚠ Orificio de 1.5 mm, Cv 0.09–0.21 — puede estrangular la medición.** Ver "El diverter puede invalidar la medición" abajo. No energizar: falta el 1N5819 |
| Termorretráctil 650 pzas 2:1 | llegó; item #9. **Cierra el hueco de "no hay con qué aislar"** — ver la nota de herramientas |
| Fittings Swagelok / McMaster | **LLEGARON** (confirmado por Adrián). ⚠ **Falta verificar QUÉ llegó exactamente** — si incluye el adaptador G1/4→Swagelok del transductor y la tee, la cadena de sensado se puede montar en el rig y el cuello de botella mecánico desaparece. Pedir foto o lista de empaque |
| **Pin headers macho 2.54 mm** (110 pzas, `B0FFSRKF7W`) | **ORDENADO, sin llegar.** No estaba en `BOM.csv`. Es la solución limpia al Paso 0: soldar un pin a cada punta trenzada, en vez de sacrificar jumpers del kit |
| Kit de tornillos M4 | llegó; item #10. Sirve para baseplate, marco y bracket del servo. **NO sirve para montar el Pi** — ver abajo |
| **Portafusibles + fusibles 3 A** | llegó; item #7. **Desbloquea el riel de 12 V** junto con el barrel jack |
| **Barrel jack 5.5×2.1 → tornillo** | llegó; item #6. Era el segundo bloqueo del riel de 12 V, ahora cerrado |
| **Válvula de alivio ajustable** | llegó; item #3. ⚠ **EN LA MANO NO ES MONTADA**: no protege nada hasta estar instalada Y tarada. Confirmar su rango al montarla y registrar el punto de tarado |
| **Multímetro** | confirmado por Adrián 2026-07-29. Desbloquea medir `divider_ratio`, los rieles del header y el cero del transductor **sin la Pi** |
| **Cautín + soldadura** | confirmado por Adrián 2026-07-29. Desbloquea el Paso 0: colas de conductor sólido en las puntas trenzadas (sonda, 22AWG y —confirmar— transductor) |

> **`BOM.csv` no lista ni una herramienta** — ni multímetro, ni cautín, ni soldadura, ni pinzas de
> corte, ni pelacables. Tampoco hay **alambre sólido** en el BOM (la única línea de cable es 22AWG
> *stranded*), así que las colas del Paso 0 salen de sacrificar jumpers del kit. Ver
> `docs/wiring_banco.html`.
>
> **Aislar: RESUELTO** — llegó el termorretráctil (#9). Cubre los empalmes del Paso 0 y las
> soldaduras de drain/source del IRLZ44N, que quedan a 2.54 mm una de otra con +12 V y tierra.
> **Gotcha clásico: el termorretráctil se ENSARTA ANTES de soldar.** Si sueldas primero, no hay
> forma de meterlo y hay que desoldar. Ensarta un tramo en cada cable antes de acercar el cautín, y
> déjalo lejos de la punta mientras sueldas para que no se encoja antes de tiempo. Cinta de aislar
> sigue sin estar en el BOM; ya no bloquea nada, pero vale como consumible de taller.

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

   Ya no hace falta reiniciar la app si la sonda aparece tarde: el driver
   **reintenta resolver la ruta en cada lectura** (antes la resolvía una sola vez
   al construirse y quedaba muerta toda la sesión — carrera de arranque real con
   systemd). También **rechaza el 85.000 °C** de power-on-reset del DS18B20, que
   llega con CRC válido y dejaría `k` un 66 % baja. Cuando la sonda quede en el chorro
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

   **La columna de agua ES ahora la referencia de calibración.** El Keller LEX1
   quedó fuera del plan (Adrián, 2026-08-03: leerlo eléctricamente necesita un
   cable que el lab no tiene), así que el transductor es el único canal de
   presión. Ver `docs/ASSEMBLY.md` § paso 2.

**Actualización 2026-07-29: el multímetro SÍ está en la mesa**, así que el paso 3 se
puede hacer directo y la alternativa de abajo dejó de ser necesaria. Al revés de lo
que decía esta sección, hoy el cuello de botella es la **Pi** (no responde y
`install.sh` nunca corrió, así que `i2cdetect` no existe todavía): los pasos 2 y 4 y
la parte de "lo que reporta el driver" del 5 quedan **diferidos**, y los que sí se
pueden cerrar hoy son justo los que usan multímetro. Secuencia completa de armado con
esa frontera marcada: `docs/wiring_banco.html`.

Se conserva la alternativa **sin multímetro** por si sirve de contra-verificación:
`sensor.ads_channel` es 0, así que **A1 del ADS1115 está libre**.
Metiendo la entrada del divisor también a A1, el ratio sale como `A0/A1` leído por
el mismo ADC, y los errores de ganancia y de referencia **se cancelan en el
cociente** — sale mejor que con un multímetro barato. Requiere un script corto con
`adafruit_ads1x15` (el rig solo lee A0) y, por lo tanto, la Pi viva. Propuesta sin
verificar; ver `docs/wiring_protoboard.html`.

## ⚠ Si se reemplaza la Pi: tiene que ser Pi 4, NO Pi 5

Restricción de hardware/software, **verificada contra el código el 2026-08-04**.
Es la clase de compra que se hace en cinco minutos y se descubre incompatible en
tres semanas, así que queda escrita antes de comprar.

**`pigpio` no funciona en la Pi 5.** La Pi 5 mueve el GPIO al southbridge
**RP1**; `pigpio` accede directo a los registros del SoC (BCM2711 y anteriores) y
no está portado. Lo que se cae, verificado con `grep`:

| Archivo | Qué usa | En Pi 5 |
|---|---|---|
| `src/hal/servo_valve.py:57` | `pigpio.pi()` + `set_servo_pulsewidth()` | **muerto** — es el actuador principal, el lazo de presión completo |
| `src/hal/pwm_valve.py:36` | `pigpio.pi()` + `hardware_PWM()` | **muerto** — topología alterna, hoy sin construir |
| `install.sh:19` | `systemctl enable --now pigpiod` | **el aprovisionamiento falla aquí**, antes de todo lo demás |

Ese último renglón es el que más importa y no es obvio: **`install.sh` nunca ha
corrido**. Comprar una Pi 5 significa que el primer intento de instalar el rig
se atora en la línea 19, y el síntoma —"pigpiod no arranca"— no se parece en
nada a "compré el modelo equivocado".

Lo que **sí** sobrevive a una Pi 5, para no exagerar el argumento:
`gpio_diverter.py` usa **gpiozero**, que en 2.x usa `lgpio` por defecto y sí
soporta la Pi 5 — el docstring dice "pigpio backend" pero no lo impone. I²C
(ADS1115) y 1-Wire (DS18B20) también funcionan. **Es el servo lo que no.**

Y un derivado que se iría en silencio: la resistencia de gate de **470 Ω** se
derivó del límite de **8 mA del BCM2711**. Los pads del RP1 tienen otra
característica de drive, así que en una Pi 5 ese número deja de estar
justificado y hay que rederivarlo — junto con lo que dependa de él en
`ASSEMBLY.md` y en las seis hojas de cableado.

**No es que la Pi 5 sea imposible: es que cuesta reescribir el driver del servo
y rederivar el gate, a cambio de cero beneficio para este rig.**

### Antes de comprar Pi: descartar lo barato

Adrián va a pagar esto de su bolsa, así que vale decirlo: **una Pi que "no
responde" casi nunca es una Pi muerta.** En orden de probabilidad y de costo:

1. **microSD corrupta** — la causa #1. Cuesta $0 descartarla: se reflashea otra
   tarjeta y se arranca. Si arranca, la Pi está sana y el gasto se evitó.
2. **Fuente USB-C insuficiente** — la Pi 4 quiere 5 V 3 A. Segunda causa más
   común, y tiene una trampa: **si el problema es la fuente, una Pi nueva con la
   fuente vieja reproduce la falla idéntica** y parecerá que llegó defectuosa.
3. **La Pi de verdad.** Hasta descartar 1 y 2, esto es una hipótesis.

Comprar sin saber cuál de las tres es puede ser dinero tirado.

## Pendiente de compra

Del correo a Roxanne (borrador sin enviar) ya llegaron **#3, #6, #7** y #9 —
salieron de esta tabla. **Adrián va a comprar lo que falta él mismo, fuera del
ciclo de Roxanne** (decisión 2026-08-04).

| # | Pieza | Link |
|---|---|---|
| 5 | Adaptador 1/4" NPT-M × barb (×3) | B07VJK7KML |
| 10 | Kit de tornillos M4 | B0FGV8F6G7 |

### Falta y no está en el correo

| Pieza | Por qué importa |
|---|---|
| **Diodo 1N5819 (flyback)** | **crítico** — confirmado por Adrián que NO ha llegado. Sin él, al cortar la bobina el pico inverso mata el IRLZ44N. El diverter no se energiza sin este diodo montado |
| Tubería de silicón 1/4" ID | línea de permeato |
| Kit de barbs barb-a-barb | uniones de la tubería |
| PTFE thread-seal tape | juntas NPT del diverter |
| Abrazaderas de manguera | cada junta barb-silicón |
| Enclosure + coupling servo | impresión 3D propia, no es compra |

**Salieron de esta tabla** (estaban desactualizados al 2026-08-04):

- **Fittings Swagelok / McMaster** — ya **llegaron**. Lo que falta no es
  comprarlos, es **verificar qué trajo el paquete**: si incluye el adaptador
  G1/4 → Swagelok del transductor y la tee. Eso es una foto o una lista de
  empaque, no dinero.
- **Cinta de aislar** — su única justificación era que el termorretráctil no
  había llegado. **Ya llegó** (item #9), así que hay con qué aislar.

### ⚠ Para la lista de compra directa: NO incluir M3 para montar la Pi

Está mal por dos motivos independientes, y es el que quiero corregirte antes de
que se compre:

1. **No hace falta tornillería para la Pi**: va en una **carcasa que Adrián ya
   tiene**.
2. **Aunque hiciera falta, el M3 no entra.** Los barrenos de la Pi son de
   ~2.7 mm = **M2.5**. Es un error que este repo ya cometió una vez y corrigió.

El **kit M4 (item #10) sí sirve**, pero para otra cosa: baseplate, marco que
reacciona el par del servo y bracket.

### El 1N5819 no debería bloquear tres semanas

Es el único bloqueo por pieza que queda en todo el rig, y es un diodo de
centavos. Si comprarlo en línea tarda, **cualquier tienda local de electrónica
lo resuelve el mismo día** — y si no hay 1N5819, sirve un **1N4001–1N4007**:

| | 1N5819 (BOM) | 1N4001–4007 (sustituto) |
|---|---|---|
| Tipo | Schottky | rectificador estándar |
| Rating | 40 V / 1 A | 50–1000 V / 1 A |
| Recuperación | rápida | ~2 µs |
| ¿Sirve aquí? | sí | **sí** |

La recuperación lenta del 1N400x solo importaría conmutando a frecuencia alta.
El diverter conmuta **una o dos veces por punto de medición**, así que la
diferencia es irrelevante. Lo que importa es lo que ambos cumplen: soportar los
**1.08 A** de la bobina y bloquear los 12 V en directa.

Comprar **varios**, no uno: es la pieza que si se quema deja el rig parado otra
vez.

## Bloqueos activos

- **El riel de 12 V ya NO está bloqueado por piezas** — llegaron el fusible (#7)
  y el barrel jack (#6). Queda un solo bloqueo real y es del **diverter**, no del
  riel: **sin el 1N5819 montado no se energiza la bobina**.
- **⚠ Pero antes de conectar: el barril de la fuente sigue sin medirse.** El item #6 que se va a comprar es específicamente un
  adaptador **5.5×2.1**. Este inventario registraba ese tamaño como *asumido*,
  con un ASIN (`B013OVYRZU`) que además **no es el que compró `BOM.csv`**
  (`B01C010YJI`). Si el plug real no es 5.5×2.1, **el #6 no entra aunque
  llegue** y el riel sigue bloqueado.

  **Medible HOY con calibrador**, sin energizar nada: diámetro exterior e
  interior del barril. Y **la polaridad tampoco está fijada en ningún archivo** —
  hay que confirmar **centro positivo** con el multímetro antes de conectar. Con
  el riel invertido, el diodo de cuerpo del IRLZ44N y el 1N5819 quedan **los dos
  en directa**: corto franco desde el primer instante.

- **No energizar el diverter sin el 1N5819 montado** en paralelo a la bobina.
  Es el único bloqueo por pieza que queda.
- **No energizar ni acoplar el servo.** `ServoValve` lo manda a 700 µs solo al
  arrancar en modo hardware y `servo_close_us` sigue en 0 (sin calibrar). La
  calibración de extremos va con la válvula DESACOPLADA del vástago.
- **La Pi tiene un problema de hardware — ya no es "no responde por red".**
  Reportado 2026-08-01; naturaleza por confirmar con Adrián. Esto **explica
  retroactivamente** los días de silencio desde 2026-07-29, que este archivo
  atribuía a red. El software del rig nunca se instaló ahí: `install.sh` es el
  que habilita I²C/1-Wire e instala `i2c-tools`, así que `i2cdetect` **no existe
  todavía** y toda verificación que dependa de la Pi sigue diferida — ahora con
  causa raíz, no con un misterio. Si termina en reemplazo, **Pi 4, no Pi 5**
  (ver la sección de arriba), y antes conviene descartar microSD y fuente.

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

### El alivio (item #3): REINSTAURADO, pero pedido ≠ instalado

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

## Mediciones de banco pendientes — calibrador y multímetro, sin energizar

Cuatro números que hoy son supuestos, todos medibles en una sola sesión de banco
y todos bloqueando decisiones que llevan días abiertas:

- [ ] **Barril de la fuente de 12 V**: diámetro exterior e interior, y **polaridad
      (centro +)** con el multímetro. Bloquea el riel de 12 V — ver bloqueos.
- [ ] **Rosca del manómetro (que es el Keller LEX1)**: si es G1/4, el transductor
      entra en ese mismo puerto y el adaptador deja de hacer falta. Ahora sin
      trade: el LEX1 salió del plan de medición, así que tomar su puerto no
      desplaza ningún canal. Ver `docs/ASSEMBLY.md`.
- [ ] **Par de arranque del vástago, EN SECO** (ΔP = 0). Da el piso; decide si el
      DS3218 alcanza pelón. Medir después a la tarada del regulador y registrar
      **a qué ΔP** corresponde cada número.
- [ ] **Probeta: DOS números, no uno.** La **división menor** (fija δV, el error
      de lectura) y la **capacidad real hasta la marca superior** (fija
      `t_max = 0.8·V_max/Q`, cuánto se puede colectar). Son los dos términos
      independientes de la fórmula de error de Datos — con solo uno no sale.
      No bloquea nada hoy; se lee de paso mientras el calibrador está afuera.

Y uno que no es de banco pero destraba más que ninguno:

- [ ] **Diámetro interior y largo del tubo buzo**, y el tramo **tee → portamalla**.
      Las caídas de presión que cita `ASSEMBLY.md` están calculadas contra un buzo
      *supuesto*; el buzo decide si su caída es despreciable o se come la prueba, y
      el tramo tee→portamalla es el único que cae DENTRO de la medición.
- [ ] **Rating de presión de los DOS recipientes** — tanque y portamalla son piezas
      distintas y ninguno está escrito en el repo. El alivio se tara por debajo del
      menor de los dos, así que sin ese número no hay contra qué tararlo.
- [ ] **Tarada del regulador de la línea de aire.** Se lee de su carátula. Sin
      alivio mecánico es la **única** cota física sobre lo que la celda puede
      ver, y hoy gatea: presurizar con seguridad, el tope de la recuperación de
      techo, si hace falta un solenoide de corte, dimensionar el servo, y medir
      el par de arranque.

## Tornillería: RESUELTO — Adrián ya tiene carcasa para el Pi

El Pi va montado en una **carcasa que Adrián ya tenía**, así que no hace falta
tornillería para él. Eso cierra el hueco de M2.5 que se había abierto.

Queda registrado el hecho subyacente por si alguien vuelve a montar el Pi a
tornillo: **sus barrenos son de ~2.7 mm = M2.5**, así que ni el M4 que llegó ni
el M3 que pedía el BOM entran. `BOM.csv` y `docs/ASSEMBLY.md` ya están corregidos
para que nadie re-derive el error.

El **kit M4 sí sirve** para lo que no es el Pi: baseplate, el marco metálico que
reacciona el par del servo, y el bracket.

**Dos cosas que la carcasa NO cubre:**
- **Acceso al header de 40 pines.** Muchas carcasas lo tapan. Confirmar que los
  jumpers pueden salir — si no, hay que abrirle una ranura o usar otra.
- **La caja de electrónica del BOM es otra cosa.** Esa era para alojar Pi +
  protoboard + UBEC + portafusibles con protección contra salpicaduras. Una
  carcasa de Pi no la sustituye. Cuánto importa depende de cómo quede el arreglo
  final — y ahora importa más, porque el rig se queda operándose sin Adrián
  enfrente.

## ⚠ El diverter puede invalidar la medición — verificar ANTES de tomar datos

Adrián vio el orificio y le pareció muy chico. Tenía razón: **1.5 mm, Cv 0.09–0.21**
(la propia página del fabricante da los dos números; el cálculo de orificio con
Cd 0.6 da ~0.062, lo que respalda el pesimista).

El diverter está **aguas abajo de la membrana**, y todo el cálculo supone que ese
lado está a atmósfera — o sea que lo que lee el transductor *es* la ΔP
transmembrana. Si el orificio restringe, hay contrapresión y la ΔP real es menor.

**Y lo grave no es el sesgo: la caída va con Q², y Q crece con ΔP.** El error
crece con la presión, así que no desplaza la recta de Darcy — **la dobla**.

| Caudal | Contrapresión @Cv 0.09 | @Cv 0.21 |
|---|---|---|
| 5 mL/s | 5.3 kPa | 1.0 kPa |
| 10 mL/s | 21.4 kPa | 3.9 kPa |
| 15 mL/s | 48.1 kPa | 8.8 kPa |
| 30 mL/s | 192 kPa | **35.4 kPa** |

Contra 35 kPa de presión de trabajo. A 30 mL/s con el Cv **optimista** la válvula
se come la prueba entera. Transparente solo hasta **2–5 mL/s**; el sim asume 28–60.

**El R² no lo caza.** Simulado contra el ajuste real: una recta doblada lo
suficiente para dejar `k` **49.5 % baja** sigue dando **R² = 0.9969** y
`follows_darcy = True`. Con tres setpoints una curvatura suave es invisible.

**Todo depende de un número que nunca se ha medido: el caudal real.** Es el mismo
pendiente que ya tenía Datos por el desbordamiento de la probeta — dos problemas,
una sola medición. Prueba de aceptación en `docs/COMMISSIONING.md` § Stage 10.5.

## La probeta se desborda antes de que termine la ventana de colecta

Con el caudal del **sim** y `test.collection_s: 60`:

| Setpoint | Caudal | En 60 s | La probeta de 1000 mL se llena en |
|---|---|---|---|
| 20 kPa | 28.8 mL/s | 1728 mL | **34.7 s** |
| 40 kPa | 44.5 mL/s | 2671 mL | **22.5 s** |
| 60 kPa | 60.2 mL/s | 3614 mL | **16.6 s** |

O sea: el procedimiento tal como está **no es operable** con esta probeta. Y no
se arregla comprando una más grande — una de 2000 mL se llenaría en 33–69 s,
igual de al filo.

**Lo que sí lo arregla es acortar la ventana**, y sale barato: Datos cuantificó
que a 10 s la incertidumbre en `k` por lectura a ojo sigue siendo ~2.2 % con una
probeta gruesa (±5 mL), contra 0.4 % a 60 s. `test.collection_s` es de **Control**.

**Pero antes de mover nada: esto es caudal de SIMULACIÓN.** El caudal real es de
las primeras cosas que el rig dirá al conectarse, y puede no parecerse. La acción
correcta es medir el caudal real primero y dimensionar la ventana contra la
probeta que existe, no rediseñar sobre un número simulado.

## Discrepancias abiertas

- ~~UBEC 6 V vs 6.8 V.~~ **RESUELTO.** El Hobbywing UBEC-3A solo entrega 5 V o
  6 V por jumper: no existe posición de 6.8 V, así que la doc pedía una tensión
  que la pieza no puede dar. Las bandas de par se rederivaron **a 6 V** (calado
  2.00 N·m interpolado del datasheet): **≤0.95 pelón · 0.95–1.42 con reducción
  2:1 · >1.42 servo mayor**. Corregido en `ASSEMBLY.md`, `gen_bom.py` y
  `.claude/roles/hardware.md`.
