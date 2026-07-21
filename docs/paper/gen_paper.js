const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, AlignmentType, Table, TableRow, TableCell,
  WidthType, BorderStyle, LevelFormat, ShadingType, PositionalTab,
  PositionalTabAlignment, PositionalTabLeader, ImageRun,
} = require("docx");

const FIGDIR = __dirname;

const FONT = "Times New Roman";
const SZ = 22;          // 11 pt body
const OUT = require("path").join(__dirname, "Automated_Membrane_Permeability_System_Martinez.docx");

// ---------- helpers ----------
const P = (text, opts = {}) => new Paragraph({
  alignment: opts.align || AlignmentType.JUSTIFIED,
  spacing: { after: opts.after ?? 120, line: 276 },
  indent: opts.indent,
  children: Array.isArray(text) ? text : [new TextRun({ text, font: FONT, size: opts.size || SZ, bold: opts.bold, italics: opts.italics })],
});

const H1 = (text) => new Paragraph({
  spacing: { before: 240, after: 120 },
  children: [new TextRun({ text, font: FONT, size: 24, bold: true })],
});

const H2 = (text) => new Paragraph({
  spacing: { before: 160, after: 100 },
  children: [new TextRun({ text, font: FONT, size: 22, bold: true, italics: true })],
});

const R = (text, o = {}) => new TextRun({ text, font: FONT, size: SZ, ...o });

const EQ = (runs, num) => new Paragraph({
  spacing: { before: 80, after: 80 },
  indent: { left: 720 },
  children: [
    ...runs,
    new TextRun({ font: FONT, size: SZ, children: [new PositionalTab({ alignment: PositionalTabAlignment.RIGHT, relativeTo: "margin", leader: PositionalTabLeader.NONE }), `(${num})`] }),
  ],
});

const cell = (text, w, opts = {}) => new TableCell({
  width: { size: w, type: WidthType.DXA },
  shading: opts.head ? { type: ShadingType.CLEAR, fill: "E8EDF4" } : undefined,
  margins: { top: 60, bottom: 60, left: 100, right: 100 },
  children: [new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text, font: FONT, size: 20, bold: !!opts.head })],
  })],
});

const table = (widths, rows) => new Table({
  columnWidths: widths,
  width: { size: widths.reduce((a, b) => a + b, 0), type: WidthType.DXA },
  rows: rows.map((r, i) => new TableRow({ children: r.map((t, j) => cell(t, widths[j], { head: i === 0 })) })),
});

const caption = (text) => new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 80, after: 200 },
  children: [new TextRun({ text, font: FONT, size: 20, italics: true })],
});

const figure = (file, w, h) => new Paragraph({
  alignment: AlignmentType.CENTER,
  spacing: { before: 160, after: 60 },
  children: [new ImageRun({
    type: "png",
    data: fs.readFileSync(`${FIGDIR}/${file}`),
    transformation: { width: w, height: h },
  })],
});

const bullets = (items) => items.map(t => new Paragraph({
  numbering: { reference: "bul", level: 0 },
  spacing: { after: 60, line: 276 },
  alignment: AlignmentType.JUSTIFIED,
  children: [new TextRun({ text: t, font: FONT, size: SZ })],
}));

// ---------- content ----------
const children = [];

// Title block
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { after: 160 },
  children: [new TextRun({ text: "An Automated Raspberry Pi–Based Pressure Control and Data Acquisition System for Membrane Permeability Characterization", font: FONT, size: 32, bold: true })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { after: 40 },
  children: [new TextRun({ text: "Salvador Adrián Martínez García", font: FONT, size: 24 })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { after: 40 },
  children: [new TextRun({ text: "ENLACE Research Program, University of California San Diego, La Jolla, CA", font: FONT, size: 20, italics: true })],
}));
children.push(new Paragraph({
  alignment: AlignmentType.CENTER, spacing: { after: 240 },
  children: [new TextRun({ text: "July 2026", font: FONT, size: 20 })],
}));

// Abstract
children.push(H1("Abstract"));
children.push(P("Membrane permeability characterization by constant-pressure permeate collection is conventionally performed manually: an operator regulates the feed pressure with a hand valve while simultaneously timing the collection of permeate with a stopwatch and repositioning the outlet hose between containers. Both tasks introduce operator-dependent error into the flow-rate measurement from which the Darcy permeability is derived. This work presents a low-cost automated test platform, built around a Raspberry Pi 4 single-board computer, that closes the loop on both error sources. Feed pressure is regulated by a proportional–integral–derivative (PID) controller commanding a servo-actuated quarter-turn valve on the compressed-air inlet of an air-over-water pressure vessel, while a three-way solenoid diverter automates the timed routing of permeate between waste and measurement containers. Water temperature is measured in situ and the temperature-dependent viscosity is computed automatically, so that the derived permeability is temperature-corrected per run. The full software stack — hardware abstraction, control loop, test sequencing, safety supervision, data logging, and a browser-based user interface — was validated in a hardware-free simulation mode. Simulated runs held setpoints of 20–60 kPa against a ±8 kPa oscillating supply disturbance, reproduced a reference manual dataset (permeability k = 1.44 × 10⁻¹² m², mean hydraulic pore size 6.78 µm, R² = 0.994), and confirmed that the derived permeability is invariant with water temperature, as theory requires."));
children.push(P([R("Keywords: ", { bold: true }), R("membrane permeability; Darcy's law; process automation; Raspberry Pi; PID control; instrumentation")], { after: 240 }));

// 1. Introduction
children.push(H1("1. Introduction"));
children.push(P("The permeability of porous membranes is routinely characterized by driving water through a membrane specimen at a series of controlled transmembrane pressures and measuring the resulting volumetric flow rate. Under laminar, viscous-dominated flow the two quantities are related by Darcy's law [1], and the slope of the flow-rate–versus–pressure line yields the permeability, from which a mean hydraulic pore size follows. In the target application — mesh membranes for two-phase cooling devices, where pore size controls the trade-off between permeate flow and capillary pumping pressure — permeability values in the 10⁻¹²–10⁻¹³ m² range must be resolved reliably across specimens."));
children.push(P("In the existing manual procedure, a compressor pressurizes a water reservoir; an operator throttles a valve by hand until an analog gauge reads the target pressure, holds it there by continuous adjustment, and simultaneously starts a stopwatch while moving the outlet hose into a graduated container. After a fixed time, the hose is withdrawn and the collected volume is read. This procedure has two operator-dependent error sources: (i) the regulated pressure wanders with compressor cycling and operator attention, and (ii) the collection interval and the hose transfer are timed by hand. Both propagate directly into the measured flow rate and therefore into the reported permeability."));
children.push(P("This paper describes an automated test platform that removes the operator from both tasks while logging every measured quantity. The system was designed around three constraints: minimal cost (commodity hobby-grade actuation and sensing), non-invasive integration with the existing stainless-steel test vessel, and a software architecture that can be exercised end-to-end without hardware, so that control logic and analysis could be verified before the instrument was assembled."));

// 2. System description
children.push(H1("2. System Description"));
children.push(H2("2.1 Apparatus"));
children.push(P("The test cell is an existing stainless-steel pressure vessel with the membrane specimen clamped at a bolted mid-plane flange. Compressed air from the laboratory gas panel pressurizes the headspace above a column of distilled water (air-over-water configuration); the pressurized water permeates the membrane and exits through an outlet port. The automation adds five elements to this vessel (Fig. 1): (i) a hobby servomotor (20 kg·cm class) coupled through a 3-D-printed transmission to the quarter-turn ball valve on the air inlet; (ii) a ratiometric pressure transducer (0–103.4 kPa, 0.5–4.5 V) teed into the feed line adjacent to the existing analog gauge; (iii) a waterproof DS18B20 digital thermometer immersed in the permeate stream; (iv) a 12 V three-way solenoid valve on the permeate outlet that routes flow either to waste or to the graduated measurement container; and (v) an adjustable mechanical pressure-relief valve on the air side as a hardware overpressure backstop, independent of all software."));
children.push(figure("fig1_system.png", 600, 360));
children.push(caption("Figure 1. System block diagram. The controller closes two loops: pressure (transducer → PID → servo-actuated air valve) and collection timing (sequencer → solenoid diverter). The mechanical relief valve is deliberately outside the control system."));
children.push(H2("2.2 Sensing chain"));
children.push(P("The Raspberry Pi has no analog inputs, so the transducer signal is digitized by a 16-bit ADS1115 analog-to-digital converter on the I²C bus. Because the sensor output spans 0.5–4.5 V while the converter operates from 3.3 V, the signal first passes through a 10 kΩ/20 kΩ resistive divider; the software inverts the divider and the sensor's linear transfer function to recover pressure. The resulting resolution is approximately 0.005 kPa per count — two orders of magnitude finer than the control requirement — so measurement quality is limited by electrical noise (±0.1–0.3 kPa in practice) rather than quantization. The chain is calibrated by a two-point comparison against the existing analog gauge (atmospheric zero and one pressurized point), which also absorbs supply-rail tolerance in the ratiometric sensor. Water temperature is read over the 1-Wire bus at 0.3 Hz on a dedicated slow thread, and the dynamic viscosity of water is evaluated continuously from the Vogel correlation [2,3]:"));
children.push(EQ([
  R("μ(T) = 2.414 × 10", { italics: true }), new TextRun({ text: "−5", font: FONT, size: SZ, superScript: true }),
  R(" · 10", { italics: true }), new TextRun({ text: "247.8/(T − 140)", font: FONT, size: SZ, superScript: true }),
  R("  Pa·s,  T in K", { italics: false }),
], 1));
children.push(P("which reproduces tabulated values to better than 1% over 15–35 °C (1.002 mPa·s at 20 °C; 0.890 mPa·s at 25 °C). Because the rig runs with distilled water, the pure-water correlation applies without correction."));
children.push(H2("2.3 Pressure actuation"));
children.push(P("The controller expresses its output as a normalized 0–100% “pressure authority” command: 0% corresponds to the air valve fully closed (the safe state, in which the vessel self-depressurizes through the membrane) and 100% to fully open. The servo maps this command onto the valve stem angle through calibrated pulse-width endpoints. Ball valves have a strongly nonlinear installed flow characteristic; however, the operating point in this application sits near the closed end of travel, which is the flattest region of the curve, and the control specification is deliberately coarse (Section 6). The regulated variable of record is always the independently measured transducer pressure, not the valve position."));
children.push(H2("2.4 Software architecture"));
children.push(P("The control software (Python 3) is organized in layers that communicate only through explicit interfaces (Fig. 2), a structure chosen so that every layer can be tested without the layers below it:"));
children.push(...bullets([
  "Hardware abstraction layer (HAL). Abstract interfaces — PressureSensor, ProportionalValve, DiverterValve, TemperatureSensor — with two interchangeable implementations each: real drivers (ADS1115 over I²C, hardware-timed servo pulses via the pigpio daemon, GPIO/MOSFET solenoid drive, 1-Wire thermometry) and mock drivers bound to a first-order plant model. Selecting mode: sim in the configuration file runs the complete system, including its user interface, with no hardware attached.",
  "Control loop. A 20 Hz thread reads the sensor, evaluates safety, and updates a PID controller with back-calculation anti-windup and derivative-on-measurement [4]. Setpoint changes are applied through a rate-limited ramp so the loop approaches each target from below, which suppresses overshoot and cancels mechanical backlash in the valve transmission.",
  "Test sequencer. A finite-state machine executes each test point: STABILIZING (the PID holds the setpoint until the measured pressure remains within a configurable tolerance band for a configurable dwell time), then COLLECTING (the diverter routes permeate to the measurement container for a precisely timed interval while pressure statistics are accumulated over that window only), then advance to the next setpoint. A full sequence of setpoints, e.g. 20/40/60 kPa, runs unattended.",
  "Safety supervisor. Evaluated every cycle, independent of test state: overpressure beyond a hard software limit triggers an immediate close-and-abort; sensor readings outside the physically plausible range (e.g. a disconnected transducer reading 0 V) are classified as instrument faults after a three-sample grace period — never as “low pressure,” which would otherwise drive the controller to open the air valve against a dead sensor. Any unhandled exception or shutdown path drives both valves to their safe states.",
  "Data layer. Each run writes a timestamped CSV (pressure, setpoint, valve command, diverter state, water temperature at 20 Hz), a JSON metadata record (per-point statistics over the collection windows), and the automated analysis products of Section 3, including a chart image and a native spreadsheet workbook whose embedded trendline remains editable.",
  "User interface. A web application served by the Pi itself; any browser on the network (laptop or phone) provides live pressure/temperature display, parameter entry (setpoints, tolerance, dwell, collection time, PID gains — all without code changes), start/stop control, and a history panel of all stored runs with one-click download of each run's data products. For off-network operation the interface is published through an authenticated outbound tunnel, so no inbound firewall ports are required.",
]));
children.push(figure("fig2_software.png", 600, 348));
children.push(caption("Figure 2. Software layer map. Each box is one module; arrows indicate dependency direction. The hardware abstraction layer is the only code that touches physical devices, so replacing the real drivers with the mock plant exercises everything above it unchanged."));

children.push(H2("2.5 Automated collection and flow measurement"));
children.push(P("The three-way diverter replaces both the stopwatch and the manual hose transfer. During stabilization the permeate is routed to waste; the instant the sequencer enters COLLECTING, the solenoid switches the stream into the graduated container and the software clock — not an operator — defines the collection interval. The collected volume is read from the graduated container and entered by the operator at the end of the sequence (the single remaining manual step), and the flow rate follows as Q = V/t with t known to software precision."));

// 3. Analysis
children.push(H1("3. Automated Data Analysis"));
children.push(P("For each completed sequence the system fits the measured flow rates against the measured mean pressures of the corresponding collection windows by ordinary least squares:"));
children.push(EQ([R("Q = a + b · ΔP", { italics: true })], 2));
children.push(P("and derives the Darcy permeability from the slope, rather than from any individual point:"));
children.push(EQ([
  R("k = b", { italics: true }),
  new TextRun({ text: "Pa", font: FONT, size: SZ, subScript: true }),
  R(" · μ · L / A", { italics: true }),
], 3));
children.push(EQ([
  R("d", { italics: true }),
  new TextRun({ text: "h", font: FONT, size: SZ, subScript: true }),
  R(" = √(32 k)", { italics: true }),
], 4));
children.push(P([
  R("where "), R("b", { italics: true }), new TextRun({ text: "Pa", font: FONT, size: SZ, subScript: true }),
  R(" is the fitted slope converted to SI pressure units, "), R("μ", { italics: true }),
  R(" the viscosity evaluated at the run-mean measured water temperature, "), R("L", { italics: true }),
  R(" the membrane thickness, "), R("A", { italics: true }), R(" the active area, and "),
  R("d", { italics: true }), new TextRun({ text: "h", font: FONT, size: SZ, subScript: true }),
  R(" the mean hydraulic pore diameter. The slope method uses all replicate points simultaneously and is robust to the experimental scatter that corrupts per-point permeability averaging; the coefficient of determination R² of the fit doubles as a quantitative check that the specimen follows Darcy's law (a threshold of R² ≥ 0.98 is applied). Because pressure enters the analysis as the measured mean over each collection window, moderate imperfection in pressure regulation biases the result far less than it would in a fixed-nominal-pressure protocol: the regression is performed against what the pressure actually was, not what it was supposed to be."),
]));

// 4. Validation
children.push(H1("4. Validation in Simulation"));
children.push(P("All control logic, sequencing, safety behavior, and analysis were exercised in the hardware-free simulation mode, in which the mock plant follows first-order pressure dynamics with a sinusoidally oscillating supply (emulating compressor cycling) and produces a Darcy-consistent permeate flow whose magnitude scales inversely with viscosity."));
children.push(H2("4.1 Disturbance rejection"));
children.push(P("With the simulated supply oscillating by ±8 kPa with a 25 s period, the closed loop held each setpoint of a 20/40/60 kPa sequence with sub-kilopascal standard deviation while the valve command visibly counter-modulated by 9–13% of full scale (Table 1)."));
children.push(table([2340, 2340, 2340, 2340], [
  ["Setpoint (kPa)", "Mean (kPa)", "Std. dev. (kPa)", "Samples in band"],
  ["20", "19.46", "0.42", "100%"],
  ["40", "39.53", "0.37", "100%"],
  ["60", "59.07", "0.77", "100%"],
]));
children.push(caption("Table 1. Setpoint tracking under a ±8 kPa oscillating supply disturbance (simulation)."));
children.push(H2("4.2 Temperature invariance of the derived permeability"));
children.push(P("Permeability is a geometric property of the specimen; viscosity and flow rate vary with temperature but must cancel in Eq. (3). Running the identical simulated specimen at 20, 25, 30, and 35 °C, the fitted slope varied with temperature as expected while the derived k remained constant to five significant figures (5.4253 × 10⁻¹³ m², 0.000% spread) — a built-in physical consistency check that will also serve as a quality-control diagnostic on the real instrument."));
children.push(H2("4.3 Reproduction of a reference manual dataset"));
children.push(P("The analysis pipeline was benchmarked against a manually acquired 60-mesh dataset previously analyzed in a spreadsheet. The automated fit returned slope 7.858 × 10⁻⁷ (m³/s)/kPa, R² = 0.9936, k = 1.437 × 10⁻¹² m², and dh = 6.78 µm, matching the spreadsheet reference (7.86 × 10⁻⁷; 0.9936; 1.44 × 10⁻¹²; 6.79 µm) to within reading precision."));

// 5. Safety
children.push(H1("5. Safety Design"));
children.push(P("Protection is layered so that no single failure — software, sensor, or actuator — can leave the vessel pressurizing uncontrolled (Table 2). The safe state is “air inlet closed”: with the feed shut, the vessel self-depressurizes through the membrane. Because the servo holds position on power loss rather than springing closed, the mechanical relief valve, set above the software cutoff but far below the vessel rating, is the ultimate backstop and is deliberately independent of all electronics."));
children.push(table([3120, 3120, 3120], [
  ["Layer", "Pressure (kPa)", "Action"],
  ["Operating range", "≤ 60", "Normal tests"],
  ["Software cutoff", "80", "Close valve, abort run, alarm"],
  ["Mechanical relief valve", "~90", "Vents regardless of software"],
  ["Sensor full scale", "103", "Saturation bound of transducer"],
]));
children.push(caption("Table 2. Defense-in-depth pressure ladder."));
children.push(P("The sensor-fault philosophy deserves emphasis: a disconnected 0.5–4.5 V transducer reads near 0 V, which naive scaling would interpret as strong vacuum-side error and answer by opening the air valve. The supervisor instead classifies out-of-range signals as instrument faults and forces the safe state — a failure mode identified during design review and treated as the highest-priority safety requirement of the software."));

// 6. Limitations
children.push(H1("6. Limitations and Future Work"));
children.push(...bullets([
  "Coarse pressure regulation. A servo-driven ball valve is expected to regulate to roughly ±10–15% rather than the ±2% of a laboratory proportional valve. This is an accepted design trade: as noted in Section 3, the analysis regresses against measured pressures, so regulation coarseness increases scatter but not bias. A stepper-driven needle valve is the identified upgrade path if finer holding proves necessary.",
  "Actuator torque margin. The valve-stem breakaway torque has not yet been measured; the printed transmission includes a 2:1 reduction as margin, and a higher-torque servo is the fallback.",
  "Manual volume reading. Permeate volume is still read by eye from the graduated container; an electronic scale or level sensor would close the last manual step.",
  "Feed-forward. If compressor cycling on the real rig exceeds what feedback alone rejects, a second transducer on the supply side (the ADC has spare channels) enables feed-forward compensation.",
  "Hardware validation. All results reported here are simulation-based; instrument assembly and on-rig commissioning (transducer calibration, valve authority sweep, PID retuning against the physical plant) are the immediate next steps.",
]));

// 7. Conclusion
children.push(H1("7. Conclusion"));
children.push(P("A complete automation platform for constant-pressure membrane permeability testing was designed, implemented, and validated in simulation. The system replaces the two operator-dependent elements of the manual protocol — pressure holding and collection timing — with closed-loop control and solenoid-switched routing, adds in-situ temperature-compensated viscosity, and reduces a full multi-pressure characterization with analysis, plotting, and spreadsheet export to a single button press followed by one volume reading per test point. The layered software design permitted the entire instrument to be verified before any hardware was purchased, and the same simulation now provides a regression harness for future development."));

// Acknowledgments
children.push(H1("Acknowledgments"));
children.push(P("The author thanks the TEMP Laboratory at the University of California San Diego and the ENLACE research program for the experimental context and the membrane characterization methodology on which this instrument is based."));

// References
children.push(H1("References"));
const refs = [
  "[1] H. Darcy, Les fontaines publiques de la ville de Dijon, Victor Dalmont, Paris, 1856.",
  "[2] H. Vogel, “Das Temperaturabhängigkeitsgesetz der Viskosität von Flüssigkeiten,” Physikalische Zeitschrift, vol. 22, pp. 645–646, 1921.",
  "[3] L. Korson, W. Drost-Hansen, and F. J. Millero, “Viscosity of water at various temperatures,” J. Phys. Chem., vol. 73, no. 1, pp. 34–39, 1969.",
  "[4] K. J. Åström and T. Hägglund, Advanced PID Control, ISA — The Instrumentation, Systems, and Automation Society, 2006.",
];
refs.forEach(t => children.push(P(t, { after: 60 })));
children.push(P([R("Software availability: ", { italics: true }), R("the full control software, simulation mode, and assembly documentation are maintained in a version-controlled repository available from the author.")], { after: 0 }));

// ---------- document ----------
const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: SZ } } } },
  numbering: {
    config: [{
      reference: "bul",
      levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } }],
    }],
  },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
    children,
  }],
});

Packer.toBuffer(doc).then(buf => {
  fs.writeFileSync(OUT, buf);
  console.log("OK ->", OUT, buf.length, "bytes");
});
