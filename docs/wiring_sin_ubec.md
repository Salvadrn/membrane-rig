# Cableado sin UBEC — el rig completo, servo alimentado desde el Pi

Estado: **cableado de trabajo del 2026-08-07**, decidido en el banco cuando el UBEC
dejó de entregar. Sustituye la ruta de alimentación del servo que describe
`wiring_dos_protoboards.html`; **todo lo demás de esa hoja sigue vigente**, y ahí
están los detalles hoyo por hoyo.

## Por qué este cableado existe

El UBEC bajaba los 12 V a 6 V para el servo. Con el UBEC fuera, el servo se
alimenta del riel de 5 V del Pi. Eso normalmente está **prohibido** en este
proyecto —un servo atorado pide 2.5 A, hunde el riel y reinicia el Pi, y este
proyecto ya perdió una placa— pero aquí se acepta bajo dos condiciones concretas
que Adrián verificó en el banco:

* **La válvula es muy suave**, casi sin resistencia, así que el servo no se
  acerca a corriente de bloqueo.
* **El pico de arranque se absorbe localmente** con un capacitor junto al servo,
  que es lo que un fusible NO puede hacer: el daño viene de una caída de voltaje
  de microsegundos, y un fusible tarda segundos en abrir.

Si la válvula alguna vez se traba, esta decisión deja de ser válida. La señal de
que eso pasó la da el propio Pi (ver *Comprobación* al final).

## A · Alimentaciones

| Qué | De dónde | Notas |
|---|---|---|
| ADS1115 `VDD` | Pi **pin 1** (3.3 V) | nunca 5 V: sus entradas no toleran más que su propio riel |
| Transductor rojo | Pi **pin 4** (5 V) | consume unos mA, no molesta |
| Servo rojo | Pi **pin 2** (5 V) | + capacitor, ver sección C |
| Bobina V1738 | **+12 V**, salida del fusible | NO pasa por ningún riel de protoboard |

El +12 V **no vive en un riel**: un contacto de protoboard está dado a ~1 A y por
ahí pasa más. Va punto a punto desde la salida del fusible a sus dos columnas
dedicadas en la placa B.

## B · Sensado — protoboard A

| Desde | Hasta |
|---|---|
| Transductor **rojo** | Pi pin 4 (5 V) |
| Transductor **negro** | riel − de A |
| Transductor **verde** (señal) | R1 **10 kΩ** en serie |
| R1 → R2, ese nodo | **A0** del ADS1115 |
| R2 **22 kΩ** | del nodo A0 al riel − |
| ADS `VDD` | Pi pin 1 (3.3 V) |
| ADS `GND` | riel − de A |
| ADS `SDA` | Pi **pin 3** |
| ADS `SCL` | Pi **pin 5** |
| ADS `ADDR` | riel − de A → dirección **0x48** |

El divisor es lo único entre una fuente de 4.5 V y un chip de 3.3 V. Relación
**medida** en este banco: **0.7346** (no la nominal 0.6875 — ya está en
`config.yaml` con su procedencia).

`ADDR` y la señal del servo **no se tocan en ningún punto**. Compartieron fila el
2026-08-06 y eso tiró el ADS del bus.

## C · Servo — sin UBEC

| Desde | Hasta |
|---|---|
| Pi **pin 2** (5 V) | rojo del servo |
| Pi **pin 20** (GND) | negro del servo |
| Pi **pin 12** (GPIO18) | señal del servo |
| **Capacitor ≥1000 µF** | entre rojo y negro, **pegado al servo** |

Polaridad del capacitor: la **franja** del cuerpo es el negativo, va al negro.
Al revés conduce, se calienta y termina en corto.

**El negro del servo va al pin 20, no al 9.** El pin 9 lleva la tierra del
sensado; si la corriente del servo regresa por ahí, su caída se suma a lo que
mide el ADC. El 2026-08-06 el ruido de presión pasó de 0.04 a 0.35 kPa p-p al
conectar el servo, y esta separación es la que ataca eso.

GPIO18 lo maneja el **PWM del kernel**, no pigpio. Necesita en
`/boot/firmware/config.txt`:

```
dtoverlay=pwm,pin=18,func=2
```

y **ninguna línea `gpio=18=`** — esa gana sobre el overlay y le roba el pin al
PWM en silencio.

## D · Diverter — protoboard B

| Desde | Hasta |
|---|---|
| **+12 V** (salida del fusible) | V1738 **polo 1** |
| V1738 **polo 2** | **drain** del IRLZ44N |
| IRLZ44N **source** | tierra común |
| Pi **pin 16** (GPIO23) | **470 Ω** en serie → **compuerta** |
| **10 kΩ** | de la compuerta a la tierra lógica |
| **1N5819** en paralelo con la bobina | **banda al polo 1** (el lado de +12 V) |

**El polo 3 no se conecta a nada.** No es un repuesto: es la llave
anti-inversión. Aterrizarlo hace que el plug metido al revés deje de ser
inofensivo.

**La 10 kΩ no es opcional.** Mientras el Pi arranca, GPIO23 todavía es entrada y
la compuerta flotaría — el diverter podría energizarse solo. Esa resistencia es
lo único que lo mantiene apagado durante el arranque.

**La banda del 1N5819 al polo 1.** Al cortar la bobina el campo colapsa y genera
un pico inverso de decenas de volts; el diodo lo recircula. Montado al revés es
un corto franco sobre los 12 V en cuanto energices.

## E · Tierra — un solo punto

Une el riel − de A con el de B, y de ahí **un solo cable** al pin 9 del Pi.
El servo es la excepción deliberada: su retorno va aparte al pin 20.

No uses los pines **6 ni 14** — están dañados en esta placa.

## F · Antes de energizar

Con la fuente **desconectada**:

1. **Cada riel −, de extremo a extremo, en las dos placas.** Muchas placas de 830
   puntos los traen partidos a la mitad y no se ve. Un riel partido significa que
   la mitad de tus tierras no son tierra, *"y el síntoma aparece hasta que algo no
   funciona por razones que parecen de software"*.
2. **Riel de 12 V, + contra −** → **OL**.
3. **Polaridad del barril** → centro es **+12 V**.
4. **Plug del V1738** → polo 1 al +12 V fusible, polo 2 al drain, **polo 3 a nada**.
5. **Banda del 1N5819** hacia el polo 1.

Las puntas del cable de 22 AWG son trenzadas y se abren entre filas. **Estáñalas**
antes de meterlas: es la causa raíz de las intermitencias del 2026-08-06.

## Comprobación

```bash
i2cdetect -y 1                    # debe dar 0x48
vcgencmd get_throttled            # ANTES de mover el servo
```

Mueve el servo varias veces y repite `get_throttled`:

* sigue en **`0x0`** → el riel del Pi nunca se hundió; la decisión de alimentar
  el servo desde el Pi está dentro de margen y queda validada por medición.
* **cambió** → hubo subtensión. Desconecta el servo del Pi y consigue fuente
  aparte antes de seguir.

Ese bit es pegajoso: registra el hundimiento aunque el riel se recupere. Es la
única forma objetiva de saber si esto le está costando al Pi.
