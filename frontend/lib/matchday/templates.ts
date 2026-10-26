// Perspective copy in English, Spanish and Hindi: [headline, body] templates per moment kind(.variant) and stance,
// plus score, finish, substitution and recap phrases. Placeholders are filled in perspective.ts.

import type { Lang } from "./types";

export type Stance = "own" | "rival" | "casual" | "coach" | "analyst";
export type RecapScope = "now" | "ht" | "ft";
export type RecapPersona = "fan" | "casual" | "coach" | "analyst" | "player";
export interface LeadArgs { spoiler: boolean; a: string; b: string; sa: number; sb: number; scope: RecapScope; m: string }
export interface FanLeadArgs { spoiler: boolean; us: string; usS: number; themS: number }
export interface StatsArgs { sh: [number | string, number | string]; xg: [string, string]; po: [number | string, number | string] }
export interface RhythmArgs { p: string; share: number }
export interface RecapCopy {
  title: Record<RecapScope, string>;
  lead: (o: LeadArgs) => string;
  fanLead: (o: FanLeadArgs) => string;
  then: string[];
  stats: (o: StatsArgs) => string;
  rhythm: (o: RhythmArgs) => string;
  cta: Record<RecapPersona, string>;
  hashtag: (a: string, b: string) => string;
  push: (o: { text: string }) => string;
}

export const SCORE: Record<Lang, { ownGoal: (us: number, them: number) => string; rivalGoal: (us: number, them: number) => string }> = {
  en: {
    ownGoal: (us: number, them: number) => (us > them ? `We lead ${us}–${them}.` : us === them ? `Level at ${us}–${them}.` : `Back within one: ${us}–${them}.`),
    rivalGoal: (us: number, them: number) => (us > them ? `Still ahead ${us}–${them}. Hold on.` : us === them ? `Pegged back to ${us}–${them}.` : `We trail ${us}–${them}. Time to respond.`),
  },
  es: {
    ownGoal: (us: number, them: number) => (us > them ? `Ganamos ${us}–${them}.` : us === them ? `Empatamos ${us}–${them}.` : `A uno: ${us}–${them}.`),
    rivalGoal: (us: number, them: number) => (us > them ? `Seguimos arriba ${us}–${them}. A aguantar.` : us === them ? `Nos empatan ${us}–${them}.` : `Perdemos ${us}–${them}. Hay que reaccionar.`),
  },
  hi: {
    ownGoal: (us: number, them: number) => (us > them ? `हम ${us}–${them} से आगे।` : us === them ? `स्कोर ${us}–${them}, बराबरी।` : `अब बस एक गोल पीछे: ${us}–${them}।`),
    rivalGoal: (us: number, them: number) => (us > them ? `अब भी ${us}–${them} से आगे। डटे रहो।` : us === them ? `${us}–${them}, बराबरी हो गई।` : `हम ${us}–${them} से पीछे। अब जवाब देना होगा।`),
  },
};
export const HOW: Record<Lang, { pen: string; low: string; clear: string; og: string; ogTag: string }> = {
  en: { pen: "penalty converted", low: "a low-probability strike", clear: "a clear chance taken", og: "an own goal", ogTag: "(o.g.)" },
  es: { pen: "penalti convertido", low: "un remate de baja probabilidad", clear: "una ocasión clara convertida", og: "un gol en propia puerta", ogTag: "(p.p.)" },
  hi: { pen: "पेनल्टी पर गोल", low: "कम संभावना वाला शॉट", clear: "साफ़ मौका भुनाया", og: "आत्मघाती गोल", ogTag: "(आत्मघाती)" },
};

export const T: Record<Lang, Record<string, Partial<Record<Stance, [string, string]>>>> = {
  en: {
    goal: {
      own: ["GOAL! {p}!", "{m} · {ownScore}"], rival: ["{t} score. {p}.", "{m} · {rivalScore}"],
      casual: ["Goal for {t}!", "{p} scores on {m}. It's {sa}–{sb}."],
      coach: ["{t} goal: {how}", "{p} finishes ({xg} xG). Expect {o} to push their back line up and take more risk on the ball."],
      analyst: ["{t} {sa}–{sb} · {xg} xG", "{dist} m, {spd} km/h. {t} win chance {wcB}% → {wcA}%."],
    },
    chance: {
      own: ["So close, {p}!", "{m} · A {xgp}% chance goes begging."], rival: ["Let-off! {p} misses", "{m} · That was a {xgp}% chance against us."],
      casual: ["Huge chance for {p}", "{t} should have scored there ({m})."],
      coach: ["Big chance {t}: {xg} xG", "{p} from {dist} m. {o} must close that zone faster."],
      analyst: ["Missed chance · {xg} xG", "{p}, {dist} m, {spd} km/h. {t} xG so far: {txg}."],
    },
    card: {
      own: ["Booked: {p}", "{m} · Careful now, one more and he's off."], rival: ["{p} goes in the book", "{m} · He has to hold back in duels now."],
      casual: ["Yellow card for {p}", "{t} · {m}."],
      coach: ["Yellow: {p} ({t})", "Card risk limits his pressing. Protect him in duels."],
      analyst: ["Yellow card · {p}", "{t} fouls in the last 10′: {fouls}."],
    },
    sub: {
      own: ["Change for us: {p} on", "{p2} off · {m}."], rival: ["{t} change: {p} on", "{p2} makes way · {m}."],
      casual: ["Substitution for {t}", "{p} replaces {p2}."],
      coach: ["{t} sub: {p} for {p2}", "{subWhy}"],
      analyst: ["Sub · {p} ↔ {p2}", "{p2} leaves after {km} km and {sprints} sprints."],
    },
    "card.red": {
      own: ["Red card: {p}", "{m} · Down to ten. Everyone has to cover now."], rival: ["{p} is sent off!", "{m} · They're down to ten. Make the extra player count."],
      casual: ["Red card for {p}", "{t} down to ten · {m}."],
      coach: ["Red: {p} ({t})", "{t} must reshape with ten: drop a forward and keep the block compact."],
      analyst: ["Red card · {p}", "{t} fouls in the last 10′: {fouls}."],
    },
    "flow.chaos": {
      own: ["It's chaos out there", "Turnovers everywhere: the game has broken open."], rival: ["It's chaos out there", "Turnovers everywhere: the game has broken open."],
      casual: ["The game has gone wild", "The ball keeps changing hands; anything can happen."],
      coach: ["Chaos index {chaos}", "Turnovers {tov}/min, transitions {tr}/min. Restore structure: shorter passes, players behind the ball."],
      analyst: ["Chaos {chaos}/100", "Turnovers {tov}/min · duels {du}/min · long balls {lb}% · {seq} passes per possession."],
    },
    "flow.control": {
      own: ["We're running this game", "{t} control {ctrl}/100 over the last 5 minutes."], rival: ["{t} have taken control", "We can't keep the ball: control {ctrl}/100 to them."],
      casual: ["{t} are in control", "Long spells on the ball, few turnovers."],
      coach: ["{t} control the game ({ctrl})", "{poss}% possession, {acc}% passing. {o} need a pressing trigger to break the rhythm."],
      analyst: ["Control {t} {ctrl}/100", "Possession {poss}%, pass accuracy {acc}%."],
    },
    "flow.rhythm": {
      own: ["Rhythm change: {pattern}", "{patternDesc}"], rival: ["Rhythm change: {pattern}", "{patternDesc}"],
      casual: ["The game changes: {pattern}", "{patternDesc}"],
      coach: ["Rhythm: {pattern}", "Tempo {tempo} passes/min, ball in play {bip}%. {patternDesc}"],
      analyst: ["Pattern → {pattern}", "Tempo {tempo}/min · ball in play {bip}% · {seq} passes per possession."],
    },
    "shape.stretched": {
      own: ["Gaps opening in our shape", "{t} spread over {len} m. A compact block is 35 m or less."], rival: ["{t} are stretched", "{len} m from their last man to their first: space between the lines for us."],
      casual: ["{t} look stretched", "Big gaps between their defence and attack."],
      coach: ["{t} stretched: {len} m long", "Defence–midfield gap {gap} m. Re-compact: drop the front line or push the back line up."],
      analyst: ["{t} length {len} m · width {wid} m", "Compact reference ≤ 35 m × ≤ 40 m. Shape area {area} m²."],
    },
    "shape.lowblock": {
      own: ["We're defending deep", "Back line {def} m from goal, block {len} m long."], rival: ["{t} sit deep", "Their back line is {def} m from goal. Patience needed."],
      casual: ["{t} sit deep", "Everyone behind the ball."],
      coach: ["Low block {t}: line at {def} m", "Length {len} m, width {wid} m. Attack the half-spaces and switch play quickly."],
      analyst: ["{t} low block", "Back line {def} m · length {len} m · width {wid} m."],
    },
    "shape.highline": {
      own: ["We're pushing high", "Our back line is up at {def} m."], rival: ["{t} push their line high", "{def} m from their goal: space in behind to run into."],
      casual: ["{t} push right up", "Their defenders are close to halfway."],
      coach: ["High line {t}: {def} m", "Runs in behind from the far side will hurt them. Time the runs."],
      analyst: ["{t} back line {def} m", "Gap to midfield {gap} m · length {len} m."],
    },
    "speed.sprint": {
      own: ["{p} flies: {spd} km/h", "{m} · Fastest sprint of the match so far."], rival: ["{p} hits {spd} km/h", "Fastest sprint of the match so far. Watch the space behind our full-back."],
      casual: ["{p} at {spd} km/h!", "The fastest sprint of the match so far."],
      coach: ["Top speed {p}: {spd} km/h", "Repeated runs in behind: track the runner early."],
      analyst: ["Max speed {spd} km/h · {p}", "Sprints so far: {sprints}. Distance {km} km."],
    },
    "speed.rocket": {
      own: ["What a strike from {p}!", "{spd} km/h off the boot."], rival: ["{p} unleashes a rocket", "{spd} km/h, and too close for comfort."],
      casual: ["{spd} km/h shot!", "{p} hits it hard."],
      coach: ["Shot at {spd} km/h · {p}", "From {dist} m. Close the shooting lane quicker."],
      analyst: ["Shot speed {spd} km/h", "{p} · {dist} m · {xg} xG."],
    },
    pass: {
      own: ["Pass of the match: {p}", "{pdist} m, completed against {diff}/100 difficulty."], rival: ["{p} picks us apart", "{pdist} m pass with only a {xpp}% chance of arriving."],
      casual: ["What a pass from {p}!", "{pdist} m and right on target."],
      coach: ["Line-breaking pass · {p}", "{pdist} m, difficulty {diff}/100. Close the lane to {p2}."],
      analyst: ["Pass difficulty {diff}/100 · {p}", "{pdist} m to {p2}, completion probability {xpp}%."],
    },
    "milestone.km10": {
      own: ["{p} passes 10 km", "Working for the team: {km} km so far."], rival: ["{p} has run 10 km", "{t}'s hardest worker today."],
      casual: ["{p}: 10 km and counting", "The most distance in his team so far."],
      coach: ["Workload: {p} at 10 km", "Watch his recovery runs in the last 20 minutes."],
      analyst: ["{p} · {km} km", "Top distance for {t}. Sprints: {sprints}."],
    },
  },
  es: {
    goal: {
      own: ["¡GOOOL de {p}!", "{m} · {ownScore}"], rival: ["Gol de {t}. {p}.", "{m} · {rivalScore}"],
      casual: ["¡Gol de {t}!", "{p} marca en el {m}. {sa}–{sb}."],
      coach: ["Gol de {t}: {how}", "{p} define ({xg} xG). {o} adelantará su línea y arriesgará más con balón."],
      analyst: ["{t} {sa}–{sb} · {xg} xG", "{dist} m, {spd} km/h. Probabilidad de victoria de {t}: {wcB}% → {wcA}%."],
    },
    chance: {
      own: ["¡Casi, {p}!", "{m} · Se escapa una ocasión del {xgp}%."], rival: ["¡Nos salvamos! {p} falla", "{m} · Era una ocasión del {xgp}% en contra."],
      casual: ["Ocasión enorme de {p}", "{t} debió marcar ({m})."],
      coach: ["Ocasión clara {t}: {xg} xG", "{p} desde {dist} m. {o} debe cerrar esa zona antes."],
      analyst: ["Ocasión fallada · {xg} xG", "{p}, {dist} m, {spd} km/h. xG de {t}: {txg}."],
    },
    card: {
      own: ["Amarilla para {p}", "{m} · Cuidado, otra y se va."], rival: ["Amonestado {p}", "{m} · Tendrá que medir los duelos."],
      casual: ["Tarjeta amarilla para {p}", "{t} · {m}."],
      coach: ["Amarilla: {p} ({t})", "El riesgo de tarjeta limita su presión. Protégelo en los duelos."],
      analyst: ["Amarilla · {p}", "Faltas de {t} en los últimos 10′: {fouls}."],
    },
    sub: {
      own: ["Cambio nuestro: entra {p}", "Sale {p2} · {m}."], rival: ["Cambio en {t}: entra {p}", "Sale {p2} · {m}."],
      casual: ["Cambio en {t}", "{p} entra por {p2}."],
      coach: ["Cambio {t}: {p} por {p2}", "{subWhy}"],
      analyst: ["Cambio · {p} ↔ {p2}", "{p2} sale tras {km} km y {sprints} sprints."],
    },
    "card.red": {
      own: ["Roja para {p}", "{m} · Nos quedamos con diez. Todos a cubrir."], rival: ["¡Expulsado {p}!", "{m} · Se quedan con diez. Hay que aprovechar al hombre de más."],
      casual: ["Tarjeta roja para {p}", "{t} se queda con diez · {m}."],
      coach: ["Roja: {p} ({t})", "{t} debe reorganizarse con diez: quitar un delantero y juntar el bloque."],
      analyst: ["Roja · {p}", "Faltas de {t} en los últimos 10′: {fouls}."],
    },
    "flow.chaos": {
      own: ["Esto es un caos", "Pérdidas por todos lados: el partido se rompió."], rival: ["Esto es un caos", "Pérdidas por todos lados: el partido se rompió."],
      casual: ["El partido se volvió loco", "El balón cambia de dueño sin parar."],
      coach: ["Índice de caos {chaos}", "Pérdidas {tov}/min, transiciones {tr}/min. Ordenar: pases cortos, gente detrás del balón."],
      analyst: ["Caos {chaos}/100", "Pérdidas {tov}/min · duelos {du}/min · balones largos {lb}% · {seq} pases por posesión."],
    },
    "flow.control": {
      own: ["Manejamos el partido", "{t} controla {ctrl}/100 en los últimos 5 minutos."], rival: ["{t} tomó el control", "No retenemos el balón: control {ctrl}/100 para ellos."],
      casual: ["{t} domina", "Largas posesiones y pocas pérdidas."],
      coach: ["{t} controla ({ctrl})", "{poss}% de posesión, {acc}% de pases. {o} necesita un disparador de presión."],
      analyst: ["Control {t} {ctrl}/100", "Posesión {poss}%, precisión de pase {acc}%."],
    },
    "flow.rhythm": {
      own: ["Cambio de ritmo: {pattern}", "{patternDesc}"], rival: ["Cambio de ritmo: {pattern}", "{patternDesc}"],
      casual: ["El partido cambia: {pattern}", "{patternDesc}"],
      coach: ["Ritmo: {pattern}", "Tempo {tempo} pases/min, balón en juego {bip}%. {patternDesc}"],
      analyst: ["Patrón → {pattern}", "Tempo {tempo}/min · balón en juego {bip}% · {seq} pases por posesión."],
    },
    "shape.stretched": {
      own: ["Se abren huecos en nuestro bloque", "{t} ocupa {len} m. Un bloque compacto mide 35 m o menos."], rival: ["{t} está partido", "{len} m entre su último y su primer hombre: espacio entre líneas."],
      casual: ["{t} se ve largo", "Mucho espacio entre su defensa y su ataque."],
      coach: ["{t} largo: {len} m", "Distancia defensa–medio {gap} m. Juntar líneas: bajar la delantera o subir la defensa."],
      analyst: ["{t} profundidad {len} m · anchura {wid} m", "Referencia compacta ≤ 35 m × ≤ 40 m. Área {area} m²."],
    },
    "shape.lowblock": {
      own: ["Defendemos bien atrás", "Línea defensiva a {def} m del arco, bloque de {len} m."], rival: ["{t} se encierra", "Su línea está a {def} m del arco. Paciencia."],
      casual: ["{t} se mete atrás", "Todos detrás del balón."],
      coach: ["Bloque bajo {t}: línea a {def} m", "Profundidad {len} m, anchura {wid} m. Atacar los carriles interiores y cambiar de banda rápido."],
      analyst: ["Bloque bajo {t}", "Línea {def} m · profundidad {len} m · anchura {wid} m."],
    },
    "shape.highline": {
      own: ["Presionamos arriba", "Nuestra línea está en {def} m."], rival: ["{t} adelanta su línea", "A {def} m de su arco: hay espacio a la espalda."],
      casual: ["{t} sube todo", "Sus defensas están cerca de mitad de cancha."],
      coach: ["Línea alta {t}: {def} m", "Los desmarques a la espalda desde el lado débil les harán daño."],
      analyst: ["Línea {t} {def} m", "Distancia al medio {gap} m · profundidad {len} m."],
    },
    "speed.sprint": {
      own: ["¡{p} vuela: {spd} km/h!", "{m} · El sprint más rápido del partido."], rival: ["{p} llega a {spd} km/h", "El sprint más rápido del partido. Ojo a la espalda del lateral."],
      casual: ["¡{p} a {spd} km/h!", "El sprint más rápido del partido."],
      coach: ["Velocidad máx. {p}: {spd} km/h", "Desmarques repetidos a la espalda: seguir al corredor antes."],
      analyst: ["Vel. máx. {spd} km/h · {p}", "Sprints: {sprints}. Distancia {km} km."],
    },
    "speed.rocket": {
      own: ["¡Qué remate de {p}!", "{spd} km/h."], rival: ["{p} saca un misil", "{spd} km/h, demasiado cerca."],
      casual: ["¡Tiro a {spd} km/h!", "{p} le pega con todo."],
      coach: ["Tiro a {spd} km/h · {p}", "Desde {dist} m. Cerrar antes la línea de tiro."],
      analyst: ["Velocidad de tiro {spd} km/h", "{p} · {dist} m · {xg} xG."],
    },
    pass: {
      own: ["Pase del partido: {p}", "{pdist} m, completado con dificultad {diff}/100."], rival: ["{p} nos desarma", "Pase de {pdist} m con solo {xpp}% de probabilidad."],
      casual: ["¡Qué pase de {p}!", "{pdist} m y al pie."],
      coach: ["Pase que rompe líneas · {p}", "{pdist} m, dificultad {diff}/100. Cerrar la línea hacia {p2}."],
      analyst: ["Dificultad de pase {diff}/100 · {p}", "{pdist} m hacia {p2}, probabilidad de completarlo {xpp}%."],
    },
    "milestone.km10": {
      own: ["{p} supera los 10 km", "Trabajo para el equipo: {km} km."], rival: ["{p} ya corrió 10 km", "El más trabajador de {t} hoy."],
      casual: ["{p}: 10 km y sigue", "El que más corre de su equipo."],
      coach: ["Carga: {p} en 10 km", "Vigilar sus repliegues en los últimos 20 minutos."],
      analyst: ["{p} · {km} km", "Máxima distancia de {t}. Sprints: {sprints}."],
    },
  },
  hi: {
    goal: {
      own: ["गोल! {p}!", "{m} · {ownScore}"], rival: ["{t} का गोल। {p}।", "{m} · {rivalScore}"],
      casual: ["{t} का गोल!", "{m} पर {p} का गोल। स्कोर {sa}–{sb}।"],
      coach: ["{t} का गोल: {how}", "{p} का फ़िनिश ({xg} xG)। अब {o} अपनी बैक लाइन ऊपर करेगा और गेंद पर ज़्यादा जोखिम लेगा।"],
      analyst: ["{t} {sa}–{sb} · {xg} xG", "{dist} मी., {spd} किमी/घं.। {t} की जीत की संभावना {wcB}% → {wcA}%।"],
    },
    chance: {
      own: ["बाल-बाल चूके, {p}!", "{m} · {xgp}% का मौका हाथ से निकला।"], rival: ["बच गए! {p} चूके", "{m} · हमारे ख़िलाफ़ {xgp}% का मौका था।"],
      casual: ["{p} का बड़ा मौका", "{t} को यहाँ गोल करना चाहिए था ({m})।"],
      coach: ["{t} का बड़ा मौका: {xg} xG", "{dist} मी. से {p}। {o} को वह ज़ोन जल्दी बंद करना होगा।"],
      analyst: ["चूका मौका · {xg} xG", "{p}, {dist} मी., {spd} किमी/घं.। {t} का अब तक xG: {txg}।"],
    },
    card: {
      own: ["{p} को पीला कार्ड", "{m} · सावधान, एक और कार्ड और वो बाहर।"], rival: ["{p} बुक हुए", "{m} · अब उन्हें डुएल में संभलकर खेलना होगा।"],
      casual: ["{p} को पीला कार्ड", "{t} · {m}।"],
      coach: ["पीला कार्ड: {p} ({t})", "कार्ड का जोखिम उसकी प्रेसिंग सीमित करता है। डुएल में उसे बचाएँ।"],
      analyst: ["पीला कार्ड · {p}", "पिछले 10′ में {t} के फ़ाउल: {fouls}।"],
    },
    sub: {
      own: ["हमारा बदलाव: {p} अंदर", "{p2} बाहर · {m}।"], rival: ["{t} का बदलाव: {p} अंदर", "{p2} बाहर · {m}।"],
      casual: ["{t} का सब्स्टिट्यूशन", "{p2} की जगह {p}।"],
      coach: ["{t} सब: {p2} की जगह {p}", "{subWhy}"],
      analyst: ["सब · {p} ↔ {p2}", "{p2} ने {km} किमी और {sprints} स्प्रिंट के बाद मैदान छोड़ा।"],
    },
    "card.red": {
      own: ["{p} को लाल कार्ड", "{m} · अब हम दस खिलाड़ी। सबको कवर करना होगा।"], rival: ["{p} बाहर!", "{m} · वे दस रह गए। एक्स्ट्रा खिलाड़ी का फ़ायदा उठाएँ।"],
      casual: ["{p} को लाल कार्ड", "{t} अब दस खिलाड़ी · {m}।"],
      coach: ["लाल कार्ड: {p} ({t})", "{t} को दस के साथ शेप बदलनी होगी: एक फ़ॉरवर्ड कम करें, ब्लॉक कॉम्पैक्ट रखें।"],
      analyst: ["लाल कार्ड · {p}", "पिछले 10′ में {t} के फ़ाउल: {fouls}।"],
    },
    "flow.chaos": {
      own: ["मैदान पर अफ़रा-तफ़री", "हर तरफ़ टर्नओवर: खेल पूरी तरह खुल गया है।"], rival: ["मैदान पर अफ़रा-तफ़री", "हर तरफ़ टर्नओवर: खेल पूरी तरह खुल गया है।"],
      casual: ["खेल बेकाबू हो गया", "गेंद बार-बार छिन रही है, कुछ भी हो सकता है।"],
      coach: ["अफ़रा-तफ़री इंडेक्स {chaos}", "टर्नओवर {tov}/मिनट, ट्रांज़िशन {tr}/मिनट। ढाँचा वापस लाएँ: छोटे पास, गेंद के पीछे खिलाड़ी।"],
      analyst: ["अफ़रा-तफ़री {chaos}/100", "टर्नओवर {tov}/मिनट · डुएल {du}/मिनट · लंबे पास {lb}% · हर पज़ेशन में {seq} पास।"],
    },
    "flow.control": {
      own: ["खेल हमारे हाथ में", "पिछले 5 मिनट में {t} का नियंत्रण {ctrl}/100।"], rival: ["{t} ने नियंत्रण ले लिया", "हम गेंद नहीं रख पा रहे: उनका नियंत्रण {ctrl}/100।"],
      casual: ["{t} का दबदबा", "लंबे पज़ेशन, कम टर्नओवर।"],
      coach: ["{t} का नियंत्रण ({ctrl})", "{poss}% पज़ेशन, {acc}% पासिंग। {o} को लय तोड़ने के लिए प्रेसिंग ट्रिगर चाहिए।"],
      analyst: ["नियंत्रण {t} {ctrl}/100", "पज़ेशन {poss}%, पास सटीकता {acc}%।"],
    },
    "flow.rhythm": {
      own: ["रिद्म बदली: {pattern}", "{patternDesc}"], rival: ["रिद्म बदली: {pattern}", "{patternDesc}"],
      casual: ["खेल बदला: {pattern}", "{patternDesc}"],
      coach: ["रिद्म: {pattern}", "टेम्पो {tempo} पास/मिनट, गेंद खेल में {bip}%। {patternDesc}"],
      analyst: ["पैटर्न → {pattern}", "टेम्पो {tempo}/मिनट · गेंद खेल में {bip}% · हर पज़ेशन में {seq} पास।"],
    },
    "shape.stretched": {
      own: ["हमारे शेप में गैप खुल रहे हैं", "{t} {len} मी. में फैला है। कॉम्पैक्ट ब्लॉक 35 मी. या कम होता है।"], rival: ["{t} बिखरा हुआ है", "आख़िरी से पहले खिलाड़ी तक {len} मी.: लाइनों के बीच हमारे लिए जगह।"],
      casual: ["{t} बिखरा दिख रहा है", "डिफ़ेंस और अटैक के बीच बड़ा फ़ासला।"],
      coach: ["{t} लंबा फैला: {len} मी.", "डिफ़ेंस–मिडफ़ील्ड दूरी {gap} मी.। फिर से कॉम्पैक्ट करें: फ़्रंट लाइन नीचे या बैक लाइन ऊपर।"],
      analyst: ["{t} गहराई {len} मी. · चौड़ाई {wid} मी.", "कॉम्पैक्ट संदर्भ ≤ 35 मी. × ≤ 40 मी.। क्षेत्रफल {area} मी²।"],
    },
    "shape.lowblock": {
      own: ["हम गहराई में डिफ़ेंड कर रहे हैं", "बैक लाइन गोल से {def} मी., ब्लॉक {len} मी. लंबा।"], rival: ["{t} पीछे सिमटा", "उनकी बैक लाइन गोल से {def} मी. पर। धैर्य चाहिए।"],
      casual: ["{t} पीछे सिमट गया", "सब गेंद के पीछे।"],
      coach: ["{t} लो ब्लॉक: लाइन {def} मी. पर", "गहराई {len} मी., चौड़ाई {wid} मी.। हाफ़-स्पेस पर हमला करें, जल्दी साइड बदलें।"],
      analyst: ["{t} लो ब्लॉक", "बैक लाइन {def} मी. · गहराई {len} मी. · चौड़ाई {wid} मी.।"],
    },
    "shape.highline": {
      own: ["हम ऊँचा प्रेस कर रहे हैं", "हमारी बैक लाइन {def} मी. पर।"], rival: ["{t} ने लाइन ऊपर की", "उनके गोल से {def} मी.: पीछे दौड़ने की जगह है।"],
      casual: ["{t} पूरी तरह आगे", "उनके डिफ़ेंडर हाफ़वे के पास।"],
      coach: ["{t} की हाई लाइन: {def} मी.", "दूर की साइड से पीछे की दौड़ उन्हें नुकसान देगी। दौड़ का समय सही रखें।"],
      analyst: ["{t} बैक लाइन {def} मी.", "मिडफ़ील्ड से दूरी {gap} मी. · गहराई {len} मी.।"],
    },
    "speed.sprint": {
      own: ["{p} की उड़ान: {spd} किमी/घं.", "{m} · मैच का अब तक का सबसे तेज़ स्प्रिंट।"], rival: ["{p} {spd} किमी/घं. पर", "मैच का सबसे तेज़ स्प्रिंट। हमारे फ़ुल-बैक के पीछे की जगह पर नज़र।"],
      casual: ["{p} {spd} किमी/घं. पर!", "मैच का अब तक का सबसे तेज़ स्प्रिंट।"],
      coach: ["{p} की टॉप स्पीड: {spd} किमी/घं.", "बार-बार पीछे की दौड़: रनर को जल्दी पकड़ें।"],
      analyst: ["अधिकतम स्पीड {spd} किमी/घं. · {p}", "अब तक स्प्रिंट: {sprints}। दूरी {km} किमी।"],
    },
    "speed.rocket": {
      own: ["{p} का क्या शॉट!", "{spd} किमी/घं.।"], rival: ["{p} का ज़ोरदार शॉट", "{spd} किमी/घं., बाल-बाल बचे।"],
      casual: ["{spd} किमी/घं. का शॉट!", "{p} ने पूरी ताक़त लगाई।"],
      coach: ["{spd} किमी/घं. का शॉट · {p}", "{dist} मी. से। शूटिंग लेन जल्दी बंद करें।"],
      analyst: ["शॉट स्पीड {spd} किमी/घं.", "{p} · {dist} मी. · {xg} xG।"],
    },
    pass: {
      own: ["मैच का पास: {p}", "{pdist} मी., {diff}/100 कठिनाई के बावजूद सही।"], rival: ["{p} ने हमें चीर दिया", "{pdist} मी. का पास, पहुँचने की संभावना सिर्फ़ {xpp}%।"],
      casual: ["{p} का कमाल का पास!", "{pdist} मी. और एकदम सटीक।"],
      coach: ["लाइन तोड़ने वाला पास · {p}", "{pdist} मी., कठिनाई {diff}/100। {p2} तक की लेन बंद करें।"],
      analyst: ["पास कठिनाई {diff}/100 · {p}", "{p2} को {pdist} मी., पूरा होने की संभावना {xpp}%।"],
    },
    "milestone.km10": {
      own: ["{p} ने 10 किमी पार किए", "टीम के लिए मेहनत: अब तक {km} किमी।"], rival: ["{p} 10 किमी दौड़ चुके", "आज {t} के सबसे मेहनती खिलाड़ी।"],
      casual: ["{p}: 10 किमी और जारी", "अपनी टीम में सबसे ज़्यादा दौड़।"],
      coach: ["वर्कलोड: {p} 10 किमी पर", "आख़िरी 20 मिनट में उसकी रिकवरी दौड़ पर नज़र रखें।"],
      analyst: ["{p} · {km} किमी", "{t} में सबसे ज़्यादा दूरी। स्प्रिंट: {sprints}।"],
    },
  },
};
export const SUBWHY: Record<Lang, { chase: string; manage: string }> = {
  en: { chase: "Chasing the game: more attacking legs on the pitch.", manage: "Fresh legs to manage the game." },
  es: { chase: "Va por el partido: más piernas ofensivas.", manage: "Piernas frescas para gestionar el partido." },
  hi: { chase: "मैच में वापसी की कोशिश: मैदान पर ज़्यादा अटैकिंग खिलाड़ी।", manage: "मैच संभालने के लिए ताज़ा पैर।" },
};

export const RECAP: Record<Lang, RecapCopy> = {
  en: {
    title: { now: "The story so far", ht: "Half-time", ft: "Full-time" },
    lead: (o: LeadArgs) => o.spoiler ? `${o.a} v ${o.b}${o.scope === "ft" ? ": full-time" : ""}.` : `${o.a} ${o.sa}–${o.sb} ${o.b}${o.scope === "ft" ? " at full-time" : o.scope === "ht" ? " at half-time" : `, ${o.m}`}.`,
    fanLead: (o: FanLeadArgs) => o.spoiler ? `Here is how it went for ${o.us}.` : o.usS > o.themS ? `${o.us} are winning ${o.usS}–${o.themS}.` : o.usS === o.themS ? `${o.us} are level, ${o.usS}–${o.themS}.` : `${o.us} trail ${o.usS}–${o.themS}.`,
    then: ["First", "Then", "After that", "Later", "And", "Finally"],
    stats: (o: StatsArgs) => `Shots ${o.sh[0]}–${o.sh[1]}, expected goals ${o.xg[0]}–${o.xg[1]}, possession ${o.po[0]}%–${o.po[1]}%.`,
    rhythm: (o: RhythmArgs) => `The game was mostly ${o.p.toLowerCase()} (${o.share}% of the time).`,
    cta: { fan: "Back you go: next update when it matters.", casual: "Stay with us for the next big moment.", coach: "Key decision next: who wins the middle third.", analyst: "Full numbers in the Shape and Control tabs.", player: "We'll keep following him." },
    hashtag: (a: string, b: string) => `#${a}${b}`,
    push: (o: { text: string }) => o.text,
  },
  es: {
    title: { now: "Lo que va del partido", ht: "Descanso", ft: "Final" },
    lead: (o: LeadArgs) => o.spoiler ? `${o.a} vs ${o.b}${o.scope === "ft" ? ": final" : ""}.` : `${o.a} ${o.sa}–${o.sb} ${o.b}${o.scope === "ft" ? " al final" : o.scope === "ht" ? " al descanso" : `, ${o.m}`}.`,
    fanLead: (o: FanLeadArgs) => o.spoiler ? `Así le fue a ${o.us}.` : o.usS > o.themS ? `${o.us} gana ${o.usS}–${o.themS}.` : o.usS === o.themS ? `${o.us} empata ${o.usS}–${o.themS}.` : `${o.us} pierde ${o.usS}–${o.themS}.`,
    then: ["Primero", "Luego", "Después", "Más tarde", "Y", "Por último"],
    stats: (o: StatsArgs) => `Tiros ${o.sh[0]}–${o.sh[1]}, goles esperados ${o.xg[0]}–${o.xg[1]}, posesión ${o.po[0]}%–${o.po[1]}%.`,
    rhythm: (o: RhythmArgs) => `El partido fue sobre todo ${o.p.toLowerCase()} (${o.share}% del tiempo).`,
    cta: { fan: "Seguimos: te avisamos cuando importe.", casual: "Quédate para el próximo gran momento.", coach: "Próxima decisión: quién gana el tercio medio.", analyst: "Todos los números en Forma y Control.", player: "Lo seguimos de cerca." },
    hashtag: (a: string, b: string) => `#${a}${b}`,
    push: (o: { text: string }) => o.text,
  },
  hi: {
    title: { now: "अब तक की कहानी", ht: "हाफ़-टाइम", ft: "फ़ुल-टाइम" },
    lead: (o: LeadArgs) => o.spoiler ? `${o.a} बनाम ${o.b}${o.scope === "ft" ? ": फ़ुल-टाइम" : ""}।` : `${o.a} ${o.sa}–${o.sb} ${o.b}${o.scope === "ft" ? ", फ़ुल-टाइम" : o.scope === "ht" ? ", हाफ़-टाइम" : `, ${o.m}`}।`,
    fanLead: (o: FanLeadArgs) => o.spoiler ? `${o.us} के लिए मैच ऐसा रहा।` : o.usS > o.themS ? `${o.us} ${o.usS}–${o.themS} से आगे।` : o.usS === o.themS ? `${o.us} ${o.usS}–${o.themS} से बराबर।` : `${o.us} ${o.usS}–${o.themS} से पीछे।`,
    then: ["पहले", "फिर", "उसके बाद", "आगे चलकर", "और", "आख़िर में"],
    stats: (o: StatsArgs) => `शॉट ${o.sh[0]}–${o.sh[1]}, अपेक्षित गोल ${o.xg[0]}–${o.xg[1]}, पज़ेशन ${o.po[0]}%–${o.po[1]}%।`,
    rhythm: (o: RhythmArgs) => `ज़्यादातर समय खेल ${o.p} रहा (${o.share}% समय)।`,
    cta: { fan: "जुड़े रहिए: अहम पल पर अगला अपडेट।", casual: "अगले बड़े पल के लिए बने रहिए।", coach: "अगला अहम फ़ैसला: मिडफ़ील्ड कौन जीतता है।", analyst: "पूरे आँकड़े शेप और नियंत्रण टैब में।", player: "हम उन पर नज़र रखेंगे।" },
    hashtag: (a: string, b: string) => `#${a}${b}`,
    push: (o: { text: string }) => o.text,
  },
};
