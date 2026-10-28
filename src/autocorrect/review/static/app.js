/* pevaluate review: overview, by question, by student, to review, and lab submissions.
   Every edit is saved to the result files at once; the page then reloads the model. */
"use strict";

const T = {
  es: {
    overview: "Resumen", questions: "Preguntas", students: "Estudiantes", review: "Por revisar", submissions: "Entregas",
    loading: "Cargando…", saved: "Guardado", saving: "Guardando…", error: "Error", mean: "Media", median: "Mediana",
    passed: "Aprobados (≥ 5)", marks: "Notas", mark: "Nota", question: "Pregunta", type: "Tipo", points: "Puntos",
    mc: "Test", open: "Abierta", correct: "Correcta", answered: "Contestada", blank: "En blanco", discrimination: "Discriminación",
    mean_score: "Media", full: "Máx.", zero: "Cero", edited: "Editada", flagged: "Avisos", reviewed: "Revisada",
    student: "Estudiante", id: "ID", name: "Nombre", class_list: "Lista de clase", not_in_list: "no está en la lista",
    in_list_no_work: "En la lista de clase sin examen ni entrega", save: "Guardar", score: "Puntuación",
    feedback: "Comentario (lo lee el estudiante)", preview: "Vista previa", model_original: "Original del modelo",
    transcription: "Transcripción", warnings: "Avisos del corrector", expected: "Respuesta esperada", rubric: "Rúbrica",
    explanation: "Explicación", statement: "Enunciado", all: "Todas", only_flagged: "Con avisos", only_edited: "Editadas",
    not_reviewed: "Sin revisar", sort_score: "Ordenar por puntuación", sort_name: "Ordenar por nombre",
    mark_page_reviewed: "Marcar todo lo visible como revisado", answer_sheet: "Ver la primera página escaneada (cabecera y respuestas del test, corregidas)",
    previous: "Anterior", next: "Siguiente", answer: "Respuesta", result: "Resultado", voided_all: "anulada",
    voided_nicely: "anulada (si favorece)", stale: "Hay cambios que aún no están en las notas ni en los PDF.",
    rebuild_running: "Reconstruyendo… (puede tardar un minuto)", members: "Integrantes (uno por línea)",
    submitter: "entregó", files: "Ficheros", no_files: "Sin ficheros", open_new: "Abrir en otra pestaña",
    unassigned: "Integrantes que no están en la lista de clase", twice: "En más de una entrega",
    no_submission: "Sin entrega", change_student: "Corregir el nombre o el ID del estudiante", read_from_scan: "leído del examen",
    save_student: "Guardar estudiante", conflict: "El fichero ha cambiado en disco. Recarga la página.",
    reasons: "Motivos", none: "Nada pendiente", reload: "Recargar", by: "por", of: "de", mc_part: "Test", open_part: "Abiertas",
    match_id: "por ID", match_name: "por nombre", rubric_file: "Rúbrica", what_model_saw: "corregida con el texto de fuera del recuadro",
    empty_feedback: "(sin comentario)", group: "Grupo", answers_n: "respuestas", keys: "Atajos",
    shortcut_help: "Ctrl+Enter guarda la tarjeta en la que estás escribiendo.",
    range: "Mín. – máx.", progress: "Progreso de la revisión", reviewed_plural: "revisadas", edited_plural: "editadas",
    flagged_pending: "con avisos sin revisar", open_answers: "respuestas abiertas", help: "Ayuda", theme: "Tema",
    theme_system: "Tema del sistema", theme_light: "Claro", theme_dark: "Oscuro",
    rubric_auto: "automática (según la pantalla)", rubric_right: "a la derecha", rubric_below: "debajo del comentario", rubric_hidden: "oculta",
    drag: "Arrastra para cambiar el tamaño", reviewed_next: "Revisada y siguiente →",
    remind_title: "¿Dejas esta sin marcar como revisada?",
    remind_text: "<p>Cuando hayas comprobado la nota y el comentario, marca la casilla <strong>Revisada</strong> (o usa <strong>Revisada y siguiente</strong>). Así el resumen muestra cuánto queda y nada se queda sin mirar.</p><p>Guardar un cambio la marca como revisada automáticamente.</p>",
    remind_stay: "Volver", remind_go: "Seguir sin marcar", remind_never: "Seguir y no volver a avisar",
    help_text: [
      ["Qué es", "<p>Una página local para revisar la corrección: nada sale de este ordenador. Los cambios se guardan directamente en los ficheros de resultados (los mismos que editaría un agente), así que las herramientas siguen funcionando igual.</p>"],
      ["Secciones", "<ul><li><strong>Resumen:</strong> notas, progreso de la revisión, preguntas y estudiantes, y la lista de clase (quién no tiene examen o entrega).</li><li><strong>Preguntas</strong> (exámenes): el enunciado, la respuesta esperada y la rúbrica, y la respuesta de cada estudiante con su recorte del escaneo.</li><li><strong>Estudiantes:</strong> todas las respuestas de un estudiante; en un examen escaneado, también su hoja de test y quién es (si se leyó mal el nombre o el ID).</li><li><strong>Entregas</strong> (prácticas): los ficheros a la izquierda y la nota y el comentario a la derecha; los bordes entre paneles se arrastran, y la rúbrica puede ir a la derecha, debajo u oculta.</li><li><strong>Por revisar:</strong> lo que el corrector marcó con avisos (baja confianza, texto cortado o fuera del recuadro…) y aún no has revisado.</li></ul>"],
      ["Editar", "<ul><li>Cambia la puntuación o el comentario y pulsa <strong>Guardar</strong> (o <span class='kbd'>Ctrl+Enter</span> en el comentario). El comentario lo lee el estudiante: la vista previa lo muestra como lo verá.</li><li>El original del modelo se conserva y se muestra debajo cuando has cambiado algo.</li><li>En el test, cambia la letra leída desde el menú; las letras son las del modelo de cada estudiante.</li><li>En las prácticas en grupo, edita los integrantes (uno por línea): todos reciben la misma nota y el mismo comentario.</li></ul>"],
      ["Revisada", "<p>Marca cada respuesta o entrega como <strong>Revisada</strong> cuando la hayas comprobado. No cambia la nota: solo sirve para saber qué falta. Guardar un cambio la marca sola.</p>"],
      ["Reconstruir", "<p>Las notas finales, los PDF de los estudiantes y los ficheros para subir se generan a partir de lo que editas. Cuando el aviso amarillo diga que hay cambios pendientes, pulsa <strong>Reconstruir</strong>. No se vuelve a llamar al modelo ni a leer los escaneos.</p>"],
      ["Si algo falla", "<p>Si otra herramienta o un agente cambia un fichero mientras tienes la página abierta, al guardar verás un aviso: recarga la página y vuelve a hacer el cambio. Antes del primer cambio se guarda una copia de cada fichero (<code>.before_review</code>). Para cambios de rúbrica, anular preguntas o volver a corregir, pídeselo al agente.</p>"],
    ],
    part: "Parte", unsaved_switch: "Hay cambios sin guardar. ¿Cambiar de parte y perderlos?",
    show_label: "Mostrar", sort_label: "Orden", mark_shown: "Marcar las {n} mostradas como revisadas",
    mark_shown_title: "Marca como revisadas todas las respuestas que se ven ahora con el filtro elegido (no cambia ninguna nota).",
    ctrl_enter: "Ctrl+Enter guarda", confidence: "confianza", confidence_title: "Confianza del corrector en su lectura y nota (0–1); por debajo de 0,75 se marca para revisar.",
    model_short: "Modelo", scan_page: "Modelo de examen · empieza en la página {p} del escaneo",
    change_student_help: "Si el nombre o el ID se leyeron mal del escaneo, corrígelos aquí (puedes elegir un nombre de la lista de clase). Las notas ya puestas se mantienen.",
    first_page: "Ver la primera página escaneada (cabecera)",
    reasons_map: [[/^grader warning: (.*)$/s, "aviso del corrector: {1}"], [/^low confidence \((.*)\)$/, "confianza baja ({1})"],
      [/^not graded \((.*)\)$/, "sin corregir ({1})"], [/^the crop does not match the printed box$/, "el recorte no coincide con el recuadro impreso"],
      [/^writing outside the box not seen by the grader.*$/, "hay texto fuera del recuadro que el corrector no vio"]],
    page: "Página", img_answer: "Recuadro", img_context: "Con lo de alrededor",
    upload_unreviewed: "Quedan {n} sin marcar como revisadas. Los ficheros para subir deberían llevar notas revisadas. ¿Construirlos igualmente?",
    review_done: "Revisión completa.", review_done_upload: "Ya puedes reconstruir los ficheros para subir (arriba a la derecha).",
    closing_notice: "Al cerrar esta pestaña se detiene el servidor de revisión. Todos los cambios ya están guardados. Para volver a abrirlo:",
    offline_title: "Sin conexión con el servidor de revisión.",
    offline_text: "Los cambios ya guardados están a salvo; lo que no hayas guardado sigue en la página. Se reintentará solo; si se detuvo, vuelve a lanzarlo con:",
    online_again: "Conexión recuperada",
    printed_letters: "Las letras son las impresas en el modelo de cada estudiante (las opciones se barajan entre modelos); entre paréntesis, la correcta en su modelo.",
  },
  en: {
    overview: "Overview", questions: "Questions", students: "Students", review: "To review", submissions: "Submissions",
    loading: "Loading…", saved: "Saved", saving: "Saving…", error: "Error", mean: "Mean", median: "Median",
    passed: "Passed (≥ 5)", marks: "Marks", mark: "Mark", question: "Question", type: "Type", points: "Points",
    mc: "Multiple choice", open: "Open", correct: "Correct", answered: "Answered", blank: "Blank", discrimination: "Discrimination",
    mean_score: "Mean", full: "Full", zero: "Zero", edited: "Edited", flagged: "Flags", reviewed: "Reviewed",
    student: "Student", id: "ID", name: "Name", class_list: "Class list", not_in_list: "not in the class list",
    in_list_no_work: "In the class list without exam or submission", save: "Save", score: "Score",
    feedback: "Feedback (the student reads it)", preview: "Preview", model_original: "Model's original",
    transcription: "Transcription", warnings: "Grader warnings", expected: "Expected answer", rubric: "Rubric",
    explanation: "Explanation", statement: "Statement", all: "All", only_flagged: "Flagged", only_edited: "Edited",
    not_reviewed: "Not reviewed", sort_score: "Sort by score", sort_name: "Sort by name",
    mark_page_reviewed: "Mark everything shown as reviewed", answer_sheet: "See the first scanned page (header and corrected multiple-choice answers)",
    previous: "Previous", next: "Next", answer: "Answer", result: "Result", voided_all: "voided",
    voided_nicely: "voided (if it helps)", stale: "There are changes not yet in the marks and PDFs.",
    rebuild_running: "Rebuilding… (may take a minute)", members: "Members (one per line)",
    submitter: "submitted", files: "Files", no_files: "No files", open_new: "Open in a new tab",
    unassigned: "Members not in the class list", twice: "In more than one submission",
    no_submission: "No submission", change_student: "Fix the student's name or ID", read_from_scan: "read from the exam",
    save_student: "Save student", conflict: "The file changed on disk. Reload the page.",
    reasons: "Reasons", none: "Nothing pending", reload: "Reload", by: "by", of: "of", mc_part: "Multiple choice", open_part: "Open",
    match_id: "by ID", match_name: "by name", rubric_file: "Rubric", what_model_saw: "graded with the writing outside the box",
    empty_feedback: "(no feedback)", group: "Group", answers_n: "answers", keys: "Shortcuts",
    shortcut_help: "Ctrl+Enter saves the card you are typing in.",
    range: "Min – max", progress: "Review progress", reviewed_plural: "reviewed", edited_plural: "edited",
    flagged_pending: "flagged, not reviewed", open_answers: "open answers", help: "Help", theme: "Theme",
    theme_system: "System theme", theme_light: "Light", theme_dark: "Dark",
    rubric_auto: "automatic (by screen size)", rubric_right: "on the right", rubric_below: "below the feedback", rubric_hidden: "hidden",
    drag: "Drag to resize", reviewed_next: "Reviewed and next →",
    remind_title: "Leave this one without marking it as reviewed?",
    remind_text: "<p>Once you have checked the mark and the feedback, tick <strong>Reviewed</strong> (or use <strong>Reviewed and next</strong>). The overview then shows what is left, and nothing goes unseen.</p><p>Saving a change marks it as reviewed automatically.</p>",
    remind_stay: "Go back", remind_go: "Continue without marking", remind_never: "Continue and don't remind me again",
    help_text: [
      ["What this is", "<p>A local page to review the correction: nothing leaves this computer. Changes go straight to the result files (the same an agent would edit), so the tools keep working as before.</p>"],
      ["Sections", "<ul><li><strong>Overview:</strong> marks, review progress, questions and students, and the class list (who has no exam or submission).</li><li><strong>Questions</strong> (exams): the statement, expected answer and rubric, and every student's answer with its scan crop.</li><li><strong>Students:</strong> all of a student's answers; for a scanned exam, also the answer sheet and who the student is (if the name or ID was misread).</li><li><strong>Submissions</strong> (lab work): files on the left, mark and feedback on the right; drag the borders between panes, and put the rubric on the right, below or hidden.</li><li><strong>To review:</strong> what the grader flagged (low confidence, cut text, writing outside the box…) and you have not reviewed yet.</li></ul>"],
      ["Editing", "<ul><li>Change the score or the feedback and press <strong>Save</strong> (or <span class='kbd'>Ctrl+Enter</span> in the feedback). Students read the feedback: the preview shows it as they will.</li><li>The model's original is kept and shown below once you change something.</li><li>In multiple choice, change the letter read from the menu; letters are those of each student's model.</li><li>In group work, edit the members (one per line): all of them get the same mark and feedback.</li></ul>"],
      ["Reviewed", "<p>Tick <strong>Reviewed</strong> once you have checked an answer or submission. It does not change the mark: it only tracks what is left. Saving a change ticks it.</p>"],
      ["Rebuild", "<p>Final marks, student PDFs and upload files are built from what you edit. When the yellow banner says there are pending changes, press <strong>Rebuild</strong>. The model is not called again and the scans are not read again.</p>"],
      ["If something fails", "<p>If another tool or an agent changes a file while the page is open, saving shows a warning: reload and make the change again. A copy of each file is kept before your first change (<code>.before_review</code>). For rubric changes, voiding questions or regrading, ask the agent.</p>"],
    ],
    part: "Part", unsaved_switch: "There are unsaved changes. Switch part and lose them?",
    show_label: "Show", sort_label: "Order", mark_shown: "Mark the {n} shown as reviewed",
    mark_shown_title: "Marks as reviewed every answer shown now with the chosen filter (no mark changes).",
    ctrl_enter: "Ctrl+Enter saves", confidence: "confidence", confidence_title: "The grader's confidence in its reading and grade (0–1); below 0.75 it is flagged for review.",
    model_short: "Model", scan_page: "Exam model · starts on page {p} of the scan",
    change_student_help: "If the name or ID was misread from the scan, fix it here (you can pick a name from the class list). The grades are kept.",
    first_page: "See the first scanned page (header)",
    page: "Page", img_answer: "Box", img_context: "With surroundings",
    upload_unreviewed: "{n} are not marked as reviewed. Upload files should carry reviewed grades. Build them anyway?",
    review_done: "Review complete.", review_done_upload: "You can now rebuild the upload files (top right).",
    closing_notice: "Closing this tab stops the review server. All changes are already saved. To open it again:",
    offline_title: "No connection to the review server.",
    offline_text: "Saved changes are safe; anything unsaved is still in the page. It retries by itself; if it was stopped, start it again with:",
    online_again: "Connection restored",
    printed_letters: "Letters as printed in each student's model (options are shuffled between models); in brackets, the right one in that model.",
  },
};

let M = null;            // the model from /api/model
let PART = null;         // the part shown (exam, lab...) when the assessment has several
let L = T.es;            // texts
const drafts = {};       // unsaved edits by answer/submission key, kept across re-renders
const ui = { filter: "all", sort: "name", tab: {} };

// --- Helpers ---------------------------------------------------------------------------------------
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (x, d = 2) => (x === null || x === undefined || Number.isNaN(x)) ? "–" : (Math.round(x * 10 ** d) / 10 ** d).toString();
const pct = (x) => (x === null || x === undefined) ? "–" : `${Math.round(100 * x)}%`;
const byKey = (list) => Object.fromEntries(list.map((x) => [x.key, x]));
const median = (v) => { if (!v.length) return null; const s = [...v].sort((a, b) => a - b); const m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const plainText = (html) => { const d = document.createElement("div"); d.innerHTML = html; return d.textContent.replace(/\s+/g, " ").trim(); };
const mean = (v) => v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;

function status(text, isError = false) {
  const el = $("#status");
  el.textContent = text;
  el.style.color = isError ? "var(--bad)" : "";
  if (!isError && text) setTimeout(() => { if (el.textContent === text) el.textContent = ""; }, 2500);
}

async function api(path, body) {
  if (PART && path.startsWith("/api/")) path += `${path.includes("?") ? "&" : "?"}part=${encodeURIComponent(PART)}`;
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) throw Object.assign(new Error(data.error || res.statusText), { status: res.status });
  return data;
}

async function loadModel() {
  M = await api("/api/model");
  PART = M.part;
  L = T[M.lang] || T.es;
  document.documentElement.lang = M.lang in T ? M.lang : "es";
  M.Q = byKey(M.questions);
  M.S = byKey(M.students);
  M.A = byKey(M.answers);
}

function typeset(el) {
  if (window.MathJax && MathJax.typesetPromise) MathJax.typesetPromise([el]).catch(() => {});
}

function isReviewed(key) { return !!(M.reviewed && M.reviewed[key]); }

async function save(kind, body, label) {
  status(L.saving);
  try {
    await api(`/api/edit/${kind}`, body);
    const y = window.scrollY;
    await loadModel();
    render(false);
    window.scrollTo(0, y);
    status(label || L.saved);
    return true;
  } catch (e) {
    status(e.status === 409 ? L.conflict : e instanceof TypeError ? L.offline_title : `${L.error}: ${e.message}`, true);
    return false;
  }
}

async function setReviewed(keys, value) {
  try {
    await api("/api/edit/reviewed", { keys, reviewed: value });
    keys.forEach((k) => { if (value) M.reviewed[k] = { at: new Date().toISOString() }; else delete M.reviewed[k]; });
    status(L.saved);
    return true;
  } catch (e) { status(`${L.error}: ${e.message}`, true); return false; }
}

function studentName(s) {
  if (!s) return "";
  const roster = M.roster && s.roster !== undefined ? M.roster.students[s.roster] : null;
  return roster ? roster.name : (s.name || s.id);
}

function rosterBadge(person) {
  if (!M.roster) return "";
  if (person.roster === undefined) return `<span class="badge bad">${esc(L.not_in_list)}</span>`;
  const how = person.match === "id" ? L.match_id : `${L.match_name} ${person.match_score}`;
  return `<span class="badge good" title="${esc(L.class_list)}">✓ ${esc(how)}</span>`;
}

function histogram(values, max = 10) {
  const bins = new Array(max).fill(0);
  values.forEach((v) => { if (v !== null && v !== undefined) bins[Math.min(max - 1, Math.max(0, Math.floor(v)))]++; });
  const top = Math.max(1, ...bins), w = 56, h = 170;
  const bars = bins.map((n, i) => {
    const bh = Math.round((h - 44) * n / top);
    const fail = i < 5 ? " fail" : "";
    return `<rect class="${fail}" x="${i * w + 6}" y="${h - 22 - bh}" width="${w - 12}" height="${Math.max(bh, n ? 2 : 0)}" rx="4"><title>${i}–${i + 1}: ${n}</title></rect>
      <text x="${i * w + w / 2}" y="${h - 6}" text-anchor="middle">${i}–${i + 1}</text>
      ${n ? `<text class="count" x="${i * w + w / 2}" y="${h - 28 - bh}" text-anchor="middle">${n}</text>` : ""}`;
  }).join("");
  return `<svg class="hist" viewBox="0 0 ${max * w} ${h}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(L.marks)}">${bars}</svg>`;
}

function sortable(table) {
  table.querySelectorAll("th").forEach((th, col) => th.addEventListener("click", () => {
    const body = table.tBodies[0], rows = [...body.rows];
    const dir = th.dataset.dir === "asc" ? -1 : 1;
    th.dataset.dir = dir === 1 ? "asc" : "desc";
    rows.sort((a, b) => {
      const x = a.cells[col].dataset.v ?? a.cells[col].textContent, y = b.cells[col].dataset.v ?? b.cells[col].textContent;
      const nx = parseFloat(x), ny = parseFloat(y);
      return (!Number.isNaN(nx) && !Number.isNaN(ny) ? nx - ny : x.localeCompare(y)) * dir;
    });
    rows.forEach((r) => body.appendChild(r));
  }));
}

// --- Shell -----------------------------------------------------------------------------------------
function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").map(decodeURIComponent);
  return { view: parts[0] || "", arg: parts.slice(1).join("/") };
}

function renderShell() {
  document.title = `${M.title} · review`;
  $("#title").textContent = M.title;
  $("#title").title = M.title;
  const partSelect = $("#parts");
  partSelect.hidden = !(M.parts && M.parts.length > 1);
  if (!partSelect.hidden) {
    partSelect.innerHTML = M.parts.map((x) => `<option value="${esc(x.id)}" ${x.id === M.part ? "selected" : ""}>${esc(x.label)}</option>`).join("");
    partSelect.setAttribute("aria-label", L.part);
    partSelect.onchange = () => switchPart(partSelect.value);
  }
  const r = route();
  const links = M.kind === "lab"
    ? [["", L.overview], ["sub", L.submissions], ["s", L.students], ["review", L.review], ["help", L.help]]
    : [["", L.overview], ["q", L.questions], ["s", L.students], ["review", L.review], ["help", L.help]];
  $("#nav").innerHTML = links.map(([v, label]) =>
    `<a href="#/${v}" class="${r.view === v ? "active" : ""}">${esc(label)}</a>`).join("");
  const theme = pref("theme", "system");
  $("#theme").innerHTML = [["system", L.theme_system], ["light", L.theme_light], ["dark", L.theme_dark]]
    .map(([v, l]) => `<option value="${v}" ${theme === v ? "selected" : ""}>${esc(l)}</option>`).join("");
  $("#theme").setAttribute("aria-label", L.theme);
  $("#theme").onchange = (ev) => { setPref("theme", ev.target.value); applyTheme(ev.target.value); };
  const banner = $("#banner");
  const parts = [];
  if (M.stale.length) parts.push(`<strong>${esc(L.stale)}</strong> <span>${M.stale.map(esc).join(" ")}</span>`);
  if (M.warnings.length) parts.push(M.warnings.map(esc).join(" "));
  banner.innerHTML = parts.join(" · ");
  $("#closing").innerHTML = `${esc(L.closing_notice)} <code>${esc(M.rerun || "")}</code>`;
  // Rebuild buttons live in the top bar; highlighted while there are changes not yet rebuilt.
  const actions = $("#actions");
  actions.innerHTML = M.rebuild.map((a) => `<button data-rebuild="${esc(a.id)}" class="${M.stale.length && a.id === "marks" ? "primary" : ""}" title="${esc(a.description)}">${esc(a.label)}</button>`).join("");
  actions.querySelectorAll("[data-rebuild]").forEach((b) => b.addEventListener("click", () => rebuild(b.dataset.rebuild, b)));
}

function unreviewedCount() {
  return M.kind === "lab" ? M.submissions.filter((s) => !isReviewed(s.key)).length
    : M.answers.filter((a) => a.type === "open" && !isReviewed(a.key)).length;
}

async function rebuild(id, button) {
  // Upload files are the last step: they should carry reviewed grades.
  const pending = unreviewedCount();
  if (id === "upload" && pending && !confirm(L.upload_unreviewed.replace("{n}", pending))) return;
  button.disabled = true;
  status(L.rebuild_running);
  try {
    const res = await api(`/api/rebuild/${id}`, {});
    await loadModel();
    render(false);
    status(res.ok ? L.saved : L.error, !res.ok);
    if (!res.ok || res.output) showDialog(res.output || "");
  } catch (e) { status(`${L.error}: ${e.message}`, true); }
  button.disabled = false;
}

async function switchPart(part) {
  if (Object.values(drafts).some((d) => d.dirty) && !confirm(L.unsaved_switch)) { $("#parts").value = PART; return; }
  Object.keys(drafts).forEach((k) => delete drafts[k]);
  PART = part;
  setPref(`part.${M.title}`, part);
  await loadModel();
  if (location.hash && location.hash !== "#/") location.hash = "#/"; else render();
}

function showDialog(text) { $("#dialog-text").textContent = text; $("#dialog").showModal(); }

function render(scrollTop = true) {
  renderShell();
  const r = route(), main = $("#main");
  if (M.kind === "lab" && r.view === "sub" && !r.arg && M.submissions.length) {
    const last = pref(`last.${M.title}.${M.part}`, null);
    const target = M.submissions.find((s) => s.key === last) || M.submissions[0];
    location.replace(`#/sub/${encodeURIComponent(target.key)}`);
    return;
  }
  const views = M.kind === "lab"
    ? { "": labOverview, sub: (a) => submissionView(a), s: (a) => a ? labStudentView(a) : labStudents(), review: labReview, help: helpView }
    : { "": examOverview, q: (a) => a ? questionView(a) : questionsTable(), s: (a) => a ? studentView(a) : studentsTable(), review: reviewView, help: helpView };
  main.innerHTML = (views[r.view] || views[""])(r.arg);
  main.classList.toggle("wide", !!main.querySelector("[data-panes], [data-wide]"));
  bind(main);
  bindLayout(main);
  bindCardGutters(main);
  typeset(main);
  if (scrollTop) window.scrollTo(0, 0);
}

// --- Exam: overview ----------------------------------------------------------------------------------
function examOverview() {
  const marks = M.students.map((s) => s.mark).filter((m) => m !== null && m !== undefined);
  const opens = M.answers.filter((a) => a.type === "open");
  const pending = opens.filter((a) => a.reasons.length && !isReviewed(a.key)).length;
  const reviewed = opens.filter((a) => isReviewed(a.key)).length;
  return `<h1>${esc(M.title)}</h1>
    <div class="overview">${marksPanel(marks, L.students.toLowerCase())}
      ${progressPanel(opens.length, reviewed, opens.filter((a) => a.edited).length, pending, L.open_answers)}</div>
    <h2>${esc(L.questions)}</h2>${questionsTable(true)}
    <h2>${esc(L.students)}</h2>${studentsTable(true)}${rosterPanel()}`;
}

function questionsTable(embedded = false) {
  const rows = M.questions.map((q) => {
    const s = q.stats || {};
    const void_ = q.voided ? ` <span class="badge warn">${esc(q.voided === "all" ? L.voided_all : L.voided_nicely)}</span>` : "";
    const perf = q.type === "mc" ? s.p_correct : (s.mean !== null && s.mean !== undefined && q.points ? s.mean / q.points : null);
    const text = plainText(q.text_html);
    return `<tr><td class="num" data-v="${parseFloat(q.number) || 0}"><a href="#/q/${encodeURIComponent(q.key)}">${esc(q.number)}</a></td>
      <td><a href="#/q/${encodeURIComponent(q.key)}">${esc(text.slice(0, 110))}${text.length > 110 ? "…" : ""}</a>${void_}</td>
      <td>${esc(q.type === "mc" ? L.mc : L.open)}</td><td class="num">${fmt(q.points)}</td>
      <td class="num" data-v="${perf ?? -1}">${pct(perf)}</td>
      <td class="num">${q.type === "mc" ? (s.blank ?? "–") : (s.zero ?? "–")}</td>
      <td class="num">${s.discrimination ?? "–"}</td>
      <td class="num">${q.type === "open" ? `${s.edited || 0} / ${s.flagged || 0}` : "–"}</td></tr>`;
  }).join("");
  const html = `<div class="tablewrap"><table class="sortable"><thead><tr><th class="num">#</th><th>${esc(L.question)}</th><th>${esc(L.type)}</th>
    <th class="num">${esc(L.points)}</th><th class="num" title="${esc(L.correct)} / ${esc(L.mean_score)}">%</th>
    <th class="num">${esc(L.blank)} / ${esc(L.zero)}</th><th class="num">${esc(L.discrimination)}</th>
    <th class="num">${esc(L.edited)} / ${esc(L.flagged)}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  return embedded ? html : `<h1>${esc(L.questions)}</h1>${html}`;
}

function studentsTable(embedded = false) {
  const rows = M.students.map((s) => {
    const opens = M.answers.filter((a) => a.student === s.key && a.type === "open");
    const flagged = opens.filter((a) => a.reasons.length && !isReviewed(a.key)).length;
    const reviewed = opens.filter((a) => isReviewed(a.key)).length;
    return `<tr><td><a href="#/s/${encodeURIComponent(s.key)}">${esc(studentName(s))}</a> ${rosterBadge(s)}</td><td>${esc(s.id)}</td>
      <td class="num">${s.mc && s.mc.max ? `${fmt(s.mc.score)} / ${fmt(s.mc.max)}` : "–"}</td>
      <td class="num">${s.open ? `${fmt(s.open.score)} / ${fmt(s.open.max)}` : "–"}</td>
      <td class="num" data-v="${s.mark ?? -1}"><strong>${fmt(s.mark)}</strong></td>
      <td class="num">${opens.length ? `${reviewed}/${opens.length}` : "–"}</td>
      <td class="num" data-v="${flagged}">${flagged ? `<span class="badge warn">${flagged}</span>` : ""}</td></tr>`;
  }).join("");
  const html = `<div class="tablewrap"><table class="sortable"><thead><tr><th>${esc(L.student)}</th><th>${esc(L.id)}</th>
    <th class="num">${esc(L.mc_part)}</th><th class="num">${esc(L.open_part)}</th><th class="num">${esc(L.mark)}</th>
    <th class="num">${esc(L.reviewed)}</th><th class="num">${esc(L.review)}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  return embedded ? html : `<h1>${esc(L.students)}</h1>${html}${rosterPanel()}`;
}

function rosterPanel() {
  if (!M.roster) return "";
  const matched = new Set(M.kind === "lab" ? Object.keys(M.roster.in_submissions || {}).map(Number) : M.roster.matched);
  const missing = M.roster.students.map((s, i) => [s, i]).filter(([, i]) => !matched.has(i));
  const outside = M.kind === "lab" ? [] : M.students.filter((s) => s.roster === undefined);
  return `<div class="panel"><h3>${esc(L.class_list)} <span class="muted small" title="${esc(M.roster.source)}">${esc(M.roster.source.split(/[\\/]/).pop())}</span></h3>
    <p>${esc(L.in_list_no_work)}: ${missing.length ? missing.map(([s]) => `<span class="badge">${esc(s.name)}</span>`).join(" ") : "—"}</p>
    ${outside.length ? `<p>${esc(L.not_in_list)}: ${outside.map((s) => `<a class="badge bad" href="#/s/${encodeURIComponent(s.key)}">${esc(s.name || s.id)}</a>`).join(" ")}</p>` : ""}</div>`;
}

// --- Exam: one question ------------------------------------------------------------------------------
function statementBlock(q) {
  const s = q.stats || {};
  const total = (s.n || 0) || 1;
  const options = q.options.length ? `<ul class="options">${q.options.map((o, i) => {
    const n = (s.counts || [])[i] || 0;
    return `<li class="${o.correct ? "correct" : ""}"><strong>${esc(o.letter)}</strong><span>${o.text_html}</span>
      <span title="${n}"><span class="barbox"><span class="bar" style="display:block;width:${Math.round(100 * n / total)}%"></span></span>
      <span class="small muted">${n} · ${pct(n / total)}</span></span></li>`;
  }).join("")}</ul>` : "";
  const void_ = q.voided ? `<span class="badge warn">${esc(q.voided === "all" ? L.voided_all : L.voided_nicely)}</span>` : "";
  const numbers = Object.keys(q.numbers || {}).length > 1 && new Set(Object.values(q.numbers)).size > 1
    ? `<span class="muted small">(${Object.entries(q.numbers).map(([m, n]) => `M${m}: ${n}`).join(", ")})</span>` : "";
  const stats = q.type === "mc"
    ? `${esc(L.correct)}: ${pct(s.p_correct)} · ${esc(L.blank)}: ${s.blank ?? 0} · ${esc(L.discrimination)}: ${s.discrimination ?? "–"}`
    : `${esc(L.mean_score)}: ${fmt(s.mean)} / ${fmt(q.points)} · ${esc(L.full)}: ${s.full ?? 0} · ${esc(L.zero)}: ${s.zero ?? 0} · ${esc(L.edited)}: ${s.edited ?? 0}`;
  return `<div class="panel"><div class="toolbar"><strong>${esc(L.question)} ${esc(q.number)}</strong> ${numbers} ${void_}
      <span class="badge">${esc(q.type === "mc" ? L.mc : L.open)} · ${fmt(q.points)} ${esc(L.points).toLowerCase()}</span>
      <span class="spacer"></span><span class="muted small">${stats}</span></div>
    <div class="statement">${q.text_html}${q.image ? `<img class="scan" src="${q.image}" alt="">` : ""}</div>${options}
    ${q.expected_html || q.rubric_html || q.explanation_html ? `<div class="cols">
      ${q.expected_html ? `<div><h3>${esc(L.expected)}</h3>${q.expected_html}</div>` : ""}
      ${q.rubric_html ? `<div><h3>${esc(L.rubric)}</h3>${q.rubric_html}</div>` : ""}
      ${q.explanation_html ? `<div><h3>${esc(L.explanation)}</h3>${q.explanation_html}</div>` : ""}</div>` : ""}</div>`;
}

function questionPager(q) {
  const i = M.questions.findIndex((x) => x.key === q.key);
  const prev = M.questions[i - 1], next = M.questions[i + 1];
  const options = M.questions.map((x) => `<option value="${esc(x.key)}" ${x.key === q.key ? "selected" : ""}>${esc(L.question)} ${esc(x.number)} · ${esc(plainText(x.text_html).slice(0, 70))}</option>`).join("");
  return `<div class="subbar">${prev ? `<a class="guard" href="#/q/${encodeURIComponent(prev.key)}" title="${esc(L.question)} ${esc(prev.number)}">←</a>` : `<span class="muted">←</span>`}
    <select class="jump" data-prefix="#/q/" aria-label="${esc(L.questions)}">${options}</select>
    ${next ? `<a class="guard" href="#/q/${encodeURIComponent(next.key)}" title="${esc(L.question)} ${esc(next.number)}">→</a>` : `<span class="muted">→</span>`}
    <span class="muted small">${i + 1} / ${M.questions.length}</span></div>`;
}

function filterBar(showSort = true, count = null) {
  const opt = (v, label) => `<option value="${v}" ${ui.filter === v ? "selected" : ""}>${esc(label)}</option>`;
  return `<div class="toolbar"><label class="small muted">${esc(L.show_label)} <select data-ui="filter">${opt("all", L.all)}${opt("flagged", L.only_flagged)}${opt("edited", L.only_edited)}${opt("todo", L.not_reviewed)}</select></label>
    ${showSort ? `<label class="small muted">${esc(L.sort_label)} <select data-ui="sort"><option value="name" ${ui.sort === "name" ? "selected" : ""}>${esc(L.sort_name)}</option>
      <option value="score" ${ui.sort === "score" ? "selected" : ""}>${esc(L.sort_score)}</option></select></label>` : ""}
    ${count !== null ? `<span class="muted small">${count} ${esc(L.answers_n)}</span>` : ""}
    <span class="spacer"></span><button data-mark-visible title="${esc(L.mark_shown_title)}">${esc(L.mark_shown)}</button></div>`;
}

function applyFilter(list) {
  if (ui.filter === "flagged") return list.filter((a) => a.reasons && a.reasons.length);
  if (ui.filter === "edited") return list.filter((a) => a.edited);
  if (ui.filter === "todo") return list.filter((a) => !isReviewed(a.key));
  return list;
}

function questionView(key) {
  const q = M.Q[key];
  if (!q) return `<p>${esc(L.question)} ${esc(key)}?</p>`;
  let answers = M.answers.filter((a) => a.question === key);
  let list;
  if (q.type === "mc") list = mcStudentsTable(q, answers);
  else {
    answers = applyFilter(answers);
    answers.sort(ui.sort === "score" ? (a, b) => (a.score ?? -1) - (b.score ?? -1)
      : (a, b) => studentName(M.S[a.student]).localeCompare(studentName(M.S[b.student])));
    list = `${filterBar(true, answers.length)}${answers.map((a) => openCard(a, { who: true })).join("")}`;
  }
  const layout = pref("qlayout", { statement: 38, answers: 62 });
  const total = (layout.statement || 38) + (layout.answers || 62);
  return `${questionPager(q)}<div class="panes" data-panes="qlayout">
      <div class="pane" data-pane="statement" style="flex-basis:${(100 * (layout.statement || 38) / total).toFixed(2)}%"><div class="pane-scroll">${statementBlock(q)}</div></div>
      <div class="gutter" data-gutter="0" role="separator" aria-orientation="vertical" title="${esc(L.drag)}"></div>
      <div class="pane" data-pane="answers" style="flex-basis:${(100 * (layout.answers || 62) / total).toFixed(2)}%"><div class="pane-scroll">${list}</div></div></div>`;
}

function mcStudentsTable(q, answers) {
  answers = [...answers].sort((a, b) => studentName(M.S[a.student]).localeCompare(studentName(M.S[b.student])));
  const rows = answers.map((a) => {
    const s = M.S[a.student];
    const cls = a.letter ? (a.correct ? "correct-cell" : "wrong-cell") : "muted";
    return `<tr><td><a href="#/s/${encodeURIComponent(s.key)}">${esc(studentName(s))}</a></td><td>M${esc(s.model_id)}</td>
      <td class="ans">${mcSelect(a, q, s)}</td><td class="${cls}">${a.letter ? (a.correct ? "✓" : "✗") : "–"} <span class="muted small">(${esc(a.correct_letter)})</span></td>
      <td class="num">${fmt(a.score)}</td></tr>`;
  }).join("");
  return `<div class="tablewrap"><table class="sortable mcgrid"><thead><tr><th>${esc(L.student)}</th><th>M</th>
    <th>${esc(L.answer)}</th><th>${esc(L.result)}</th><th class="num">${esc(L.points)}</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="muted small">${esc(L.printed_letters)}</p>`;
}

function mcSelect(a, q, s) {
  const letters = q.options.map((o) => o.letter);
  const options = ["", ...letters].map((l) => `<option value="${l}" ${a.letter === l ? "selected" : ""}>${l || "—"}</option>`).join("");
  return `<select data-mc="${esc(a.key)}" data-page="${esc(s.page)}" data-number="${esc(a.number)}" data-n="${letters.length}">${options}</select>`;
}

// --- Open-answer card --------------------------------------------------------------------------------
function openCard(a, { who = false, question = false, images: withImages = true } = {}) {
  const s = M.S[a.student], q = M.Q[a.question];
  const d = drafts[a.key] || {};
  const reviewed = isReviewed(a.key);
  const cls = ["answer", reviewed ? "reviewed" : a.edited ? "edited" : a.reasons.length ? "flagged" : "", withImages ? "" : "compact"].join(" ");
  let images = "";
  if (withImages && a.images.length && isPaged(a)) {
    images = `<div class="pages-box">${pagesColumn(a.images)}</div>`;
  } else if (withImages && a.images.length) {
    const tab = ui.tab[a.key] || 0;
    const image = a.images[Math.min(tab, a.images.length - 1)];
    images = `${a.images.length > 1 ? `<div class="imgtabs">${a.images.map((im, i) =>
        `<button data-imgtab="${esc(a.key)}" data-i="${i}" class="${i === tab ? "primary" : ""}">${esc(im.label === "answer" ? L.img_answer : L.img_context)}</button>`).join("")}</div>` : ""}
      <a href="${image.url}" target="_blank" rel="noopener" title="${esc(L.open_new)}"><img class="scan" loading="lazy" src="${image.url}" alt="${esc(L.answer)}"></a>`;
  }
  const head = [
    who ? `<a class="who" href="#/s/${encodeURIComponent(s.key)}">${esc(studentName(s))}</a> <span class="muted small">${esc(s.id)}</span>` : "",
    question ? `<a class="who" href="#/q/${encodeURIComponent(q.key)}">${esc(L.question)} ${esc(q.number)}</a>` : "",
    a.edited ? `<span class="badge edited">${esc(L.edited)}</span>` : "",
    a.graded_from === "context" ? `<span class="badge accent">${esc(L.what_model_saw)}</span>` : "",
  ].join(" ");
  const score = d.score ?? a.score ?? "";
  const feedback = d.feedback ?? a.feedback;
  // The grader's warnings, always visible, then the transcription (folded).
  const extras = `${a.warnings.length ? `<div class="warnings"><span class="small muted">${esc(L.warnings)}</span><ul class="small">${a.warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>` : ""}
    ${a.response_html ? `<details><summary>${esc(L.transcription)}</summary><div class="response">${a.response_html}</div></details>` : ""}`;
  const confidence = a.confidence !== null && a.confidence !== undefined
    ? `<span class="badge ${a.confidence < .75 ? "warn" : ""}" title="${esc(L.confidence_title)}">${esc(L.confidence)} ${fmt(a.confidence)}</span>` : "";
  const edit = `<div class="edit cell">
        <div class="row"><label>${esc(L.score)} <input type="number" step="0.05" min="0" max="${a.max ?? ""}" value="${esc(score)}" data-score="${esc(a.key)}"></label>
          <span class="muted">/ ${fmt(a.max)}</span>${confidence}<span class="spacer" style="flex:1"></span>
          <button class="primary" data-save-open="${esc(a.key)}" ${d.dirty ? "" : "disabled"}>${esc(L.save)}</button></div>
        <label class="small muted">${esc(L.feedback)}</label>
        <textarea data-feedback="${esc(a.key)}">${esc(feedback)}</textarea>
        <span class="hint">${esc(L.ctrl_enter)}</span>
        <div class="preview" data-preview="${esc(a.key)}" ${showPreview(d, feedback) ? "" : "hidden"}>${d.preview ?? a.feedback_html ?? ""}</div>
        ${a.llm_score !== null && a.llm_score !== undefined && a.edited ? `<div class="original"><strong>${esc(L.model_original)}:</strong> ${fmt(a.llm_score)} / ${fmt(a.max)}<br>${esc(a.llm_feedback || L.empty_feedback)}</div>` : ""}
        ${extras}
      </div>`;
  return `<section class="${cls}" data-card="${esc(a.key)}">
    <div class="head">${head}<span class="spacer" style="flex:1"></span>
      <label class="small"><input type="checkbox" data-reviewed="${esc(a.key)}" ${reviewed ? "checked" : ""}> ${esc(L.reviewed)}</label></div>
    ${a.reasons.length ? `<div class="reasons">⚠ ${a.reasons.map((r) => esc(reasonText(r))).join(" · ")}</div>` : ""}
    ${images ? `<div class="grid"><div class="cell">${images}</div>
      <div class="cgutter" data-cgutter role="separator" aria-orientation="vertical" title="${esc(L.drag)}"></div>${edit}</div>` : edit}</section>`;
}

function reasonText(reason) {
  // exam-open writes the review reasons in English; show them in the page's language.
  if (!L.reasons_map) return reason;
  for (const [pattern, text] of L.reasons_map) {
    const m = reason.match(pattern);
    if (m) return text.replace("{1}", m[1] ?? "");
  }
  return reason;
}

function showPreview(draft, text) {
  // Only when the student would see something else than the plain text: formatting, math, or while editing.
  return !!(draft && draft.dirty) || /[*_`$\\#|]|\\\(|\$\$/.test(text || "");
}

// --- Exam: one student -------------------------------------------------------------------------------
function studentPager(s) {
  const list = [...M.students].sort((a, b) => studentName(a).localeCompare(studentName(b)));
  const i = list.findIndex((x) => x.key === s.key);
  const prev = list[i - 1], next = list[i + 1];
  const options = list.map((x) => `<option value="${esc(x.key)}" ${x.key === s.key ? "selected" : ""}>${esc(studentName(x))}</option>`).join("");
  const from = `student:${s.key}`;
  return `<div class="subbar">${prev ? `<a class="guard" data-from="${esc(from)}" href="#/s/${encodeURIComponent(prev.key)}" title="${esc(studentName(prev))}">←</a>` : `<span class="muted">←</span>`}
    <select class="jump" data-from="${esc(from)}" data-prefix="#/s/" aria-label="${esc(L.students)}">${options}</select>
    ${next ? `<a class="guard" data-from="${esc(from)}" href="#/s/${encodeURIComponent(next.key)}" title="${esc(studentName(next))}">→</a>` : `<span class="muted">→</span>`}
    <span class="muted small">${i + 1} / ${list.length}</span></div>`;
}

function studentView(key) {
  const s = M.S[key];
  if (!s) return `<p>${esc(L.student)} ${esc(key)}?</p>`;
  const answers = M.answers.filter((a) => a.student === key);
  const mcs = answers.filter((a) => a.type === "mc").sort((a, b) => parseFloat(a.number) - parseFloat(b.number));
  const opens = answers.filter((a) => a.type === "open").sort((a, b) => parseFloat(a.number) - parseFloat(b.number));
  const hasMc = mcs.length > 0 && s.mc && s.mc.max;
  const roster = M.roster ? `<datalist id="roster-names">${M.roster.students.map((r) => `<option value="${esc(r.name)}" label="${esc(r.id)}"></option>`).join("")}</datalist>` : "";
  const read = s.read_id || s.read_name ? ` <span class="muted small">— ${esc(L.read_from_scan)}: ${esc([s.read_name, s.read_id].filter(Boolean).join(", "))}</span>` : "";
  const editStudent = s.page ? `<details class="panel"><summary>${esc(L.change_student)}${read}</summary>
      <p class="small muted">${esc(L.change_student_help)}</p>
      <div class="toolbar"><label>${esc(L.id)} <input data-sid value="${esc(s.id)}"></label>
      <label>${esc(L.name)} <input data-sname list="roster-names" size="34" value="${esc(s.name)}"></label>
      <button class="primary" data-save-student="${esc(s.key)}">${esc(L.save_student)}</button></div>${roster}</details>` : "";
  const mcTable = hasMc ? `<h2>${esc(L.mc_part)} · ${fmt(s.mc.score)} / ${fmt(s.mc.max)}
      <span class="muted small">(${s.mc.correct} ✓ · ${s.mc.incorrect} ✗ · ${s.mc.blank} ${esc(L.blank).toLowerCase()})</span></h2>
    <div class="tablewrap"><table class="mcgrid"><thead><tr><th class="num">#</th><th>${esc(L.question)}</th><th>${esc(L.answer)}</th>
      <th>${esc(L.correct)}</th><th class="num">${esc(L.points)}</th></tr></thead><tbody>${mcs.map((a) => {
        const q = M.Q[a.question];
        const text = plainText(q.text_html);
        const void_ = q.voided ? ` <span class="badge warn">${esc(q.voided === "all" ? L.voided_all : L.voided_nicely)}</span>` : "";
        return `<tr><td class="num">${esc(a.number)}</td><td><a href="#/q/${encodeURIComponent(q.key)}">${esc(text.slice(0, 90))}${text.length > 90 ? "…" : ""}</a>${void_}</td>
          <td class="ans">${mcSelect(a, q, s)}</td><td class="${a.letter ? (a.correct ? "correct-cell" : "wrong-cell") : ""}">${esc(a.correct_letter)}</td>
          <td class="num">${fmt(a.score)}</td></tr>`;
      }).join("")}</tbody></table></div>` : "";
  const cards = [
    [fmt(s.mark), `${L.mark} (0–10)`],
    hasMc ? [`${fmt(s.mc.score)} / ${fmt(s.mc.max)}`, L.mc_part] : null,
    s.open ? [`${fmt(s.open.score)} / ${fmt(s.open.max)}`, L.open_part] : null,
    s.model_id && s.page && new Set(M.students.map((x) => x.model_id)).size > 1 ? [`${L.model_short} ${s.model_id}`, L.scan_page.replace("{p}", s.page)] : null,
  ].filter(Boolean).map(([v, l]) => `<div class="card"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
  const header = `<h1>${esc(studentName(s))} <span class="muted small">${esc(s.id)}</span> ${rosterBadge(s)}</h1><div class="cards">${cards}</div>`;
  // Blank-paper exam: the whole exam once on the left, every correction on the right.
  const paged = opens.length && opens.every(isPaged);
  if (paged) {
    const seen = new Set(), pages = [];
    opens.forEach((a) => a.images.forEach((im) => { if (!seen.has(im.url)) { seen.add(im.url); pages.push(im); } }));
    const layout = pref("slayout", { pages: 55, corrections: 45 });
    const total = (layout.pages || 55) + (layout.corrections || 45);
    return `${studentPager(s)}<div class="panes" data-panes="slayout">
      <div class="pane" data-pane="pages" style="flex-basis:${(100 * (layout.pages || 55) / total).toFixed(2)}%"><div class="pane-scroll">${pagesColumn(pages)}</div></div>
      <div class="gutter" data-gutter="0" role="separator" aria-orientation="vertical" title="${esc(L.drag)}"></div>
      <div class="pane" data-pane="corrections" style="flex-basis:${(100 * (layout.corrections || 45) / total).toFixed(2)}%"><div class="pane-scroll">
        ${header}${editStudent}${filterBar(false)}${applyFilter(opens).map((a) => openCard(a, { question: true, images: false })).join("")}</div></div></div>`;
  }
  return `<div data-wide>${studentPager(s)}${header}
    ${editStudent}
    ${s.sheet ? `<details class="panel"><summary>${esc(hasMc ? L.answer_sheet : L.first_page)}</summary><a href="${s.sheet}" target="_blank" rel="noopener"><img class="scan" loading="lazy" src="${s.sheet}" alt=""></a></details>` : ""}
    ${mcTable}${opens.length ? `<h2>${esc(L.open_part)}</h2>${filterBar(false)}${applyFilter(opens).map((a) => openCard(a, { question: true })).join("")}` : ""}</div>`;
}

// --- Exam: to review -----------------------------------------------------------------------------------
function reviewView() {
  const items = M.answers.filter((a) => a.type === "open" && a.reasons.length && !isReviewed(a.key));
  const notInList = M.roster ? M.students.filter((s) => s.roster === undefined) : [];
  const double = M.students.filter((s) => s.multiple_marks);
  return `<h1>${esc(L.review)}</h1>
    ${notInList.length ? `<div class="panel"><strong>${esc(L.not_in_list)}:</strong> ${notInList.map((s) => `<a class="badge bad" href="#/s/${encodeURIComponent(s.key)}">${esc(s.name || s.id)}</a>`).join(" ")}</div>` : ""}
    ${double.length ? `<div class="panel"><strong>${esc(L.mc_part)}:</strong> ${double.map((s) => `<a class="badge warn" href="#/s/${encodeURIComponent(s.key)}">${esc(studentName(s))}: ${esc(s.multiple_marks)}</a>`).join(" ")}</div>` : ""}
    ${items.length ? items.map((a) => openCard(a, { who: true, question: true })).join("") : `<p class="muted">${esc(L.none)}</p>`}`;
}

// --- Lab ---------------------------------------------------------------------------------------------
function labPeople() {
  // Every person: roster students (with their submissions) and members not in the roster.
  const people = [];
  if (M.roster) {
    M.roster.students.forEach((r, i) => people.push({ key: `r${i}`, name: r.name, id: r.id, roster: i,
      subs: M.submissions.filter((s) => s.members.some((m) => m.roster === i)) }));
  }
  M.submissions.forEach((s) => s.members.forEach((m) => {
    if (m.roster === undefined) people.push({ key: `m:${s.key}:${m.name}`, name: m.name, id: m.id || "", subs: [s], outside: true });
  }));
  return people;
}

function labOverview() {
  const people = labPeople();
  const perStudent = M.roster ? people.filter((p) => !p.outside && p.subs.length).map((p) => Math.max(...p.subs.map((s) => s.mark ?? 0))) : null;
  const marks = perStudent || M.submissions.map((s) => s.mark).filter((m) => m !== null);
  const reviewed = M.submissions.filter((s) => isReviewed(s.key)).length;
  return `<h1>${esc(M.title)}</h1>
    <div class="overview">${marksPanel(marks, perStudent ? L.students.toLowerCase() : L.submissions.toLowerCase())}
      ${progressPanel(M.submissions.length, reviewed, M.submissions.filter((s) => s.edited).length, null, L.submissions.toLowerCase())}</div>
    <h2>${esc(L.submissions)}</h2>${submissionsTable()}${labRosterPanel(people)}
    ${M.rubric_html ? `<details class="panel"><summary>${esc(L.rubric_file)}</summary>${M.rubric_html}</details>` : ""}`;
}

function submissionsTable() {
  const rows = M.submissions.map((s) => `<tr><td><a href="#/sub/${encodeURIComponent(s.key)}">${s.members.map((m) => esc(m.name)).join(", ") || esc(s.submitter.name)}</a></td>
    <td class="small muted">${esc(s.submitter.name)}</td><td class="num" data-v="${s.mark ?? -1}"><strong>${fmt(s.mark)}</strong></td>
    <td>${s.edited ? `<span class="badge edited">${esc(L.edited)}</span>` : ""}</td>
    <td>${isReviewed(s.key) ? `<span class="badge good">✓</span>` : ""}</td>
    <td class="small">${s.members.some((m) => M.roster && m.roster === undefined) ? `<span class="badge bad">${esc(L.not_in_list)}</span>` : ""}</td></tr>`).join("");
  return `<div class="tablewrap"><table class="sortable"><thead><tr><th>${esc(L.group)}</th><th>${esc(L.submitter)}</th>
    <th class="num">${esc(L.mark)}</th><th>${esc(L.edited)}</th><th>${esc(L.reviewed)}</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function labRosterPanel(people) {
  if (!M.roster) return "";
  const none = people.filter((p) => !p.outside && !p.subs.length);
  const twice = people.filter((p) => !p.outside && p.subs.length > 1);
  const outside = people.filter((p) => p.outside);
  const list = (ps, cls) => ps.length ? ps.map((p) => `<a class="badge ${cls}" href="#/s/${encodeURIComponent(p.key)}">${esc(p.name)}</a>`).join(" ") : "—";
  return `<div class="panel"><h3>${esc(L.class_list)} <span class="muted small" title="${esc(M.roster.source)}">${esc(M.roster.source.split(/[\\/]/).pop())}</span></h3>
    <p>${esc(L.no_submission)}: ${list(none, "")}</p><p>${esc(L.twice)}: ${list(twice, "warn")}</p><p>${esc(L.unassigned)}: ${list(outside, "bad")}</p></div>`;
}

function labStudents() {
  const people = labPeople();
  const rows = (people.length ? people : M.submissions.flatMap((s) => s.members.map((m) => ({ key: `m:${s.key}:${m.name}`, name: m.name, id: m.id || "", subs: [s] }))))
    .map((p) => `<tr><td><a href="#/s/${encodeURIComponent(p.key)}">${esc(p.name)}</a> ${p.outside ? `<span class="badge bad">${esc(L.not_in_list)}</span>` : ""}</td>
      <td>${esc(p.id)}</td><td>${p.subs.map((s) => `<a href="#/sub/${encodeURIComponent(s.key)}">${esc(s.submitter.name || s.key)}</a>`).join(", ") || `<span class="muted">${esc(L.no_submission)}</span>`}</td>
      <td class="num" data-v="${p.subs.length ? p.subs[0].mark : -1}"><strong>${p.subs.length ? p.subs.map((s) => fmt(s.mark)).join(" / ") : "–"}</strong></td></tr>`).join("");
  return `<h1>${esc(L.students)}</h1><div class="tablewrap"><table class="sortable"><thead><tr><th>${esc(L.student)}</th><th>${esc(L.id)}</th>
    <th>${esc(L.submissions)}</th><th class="num">${esc(L.mark)}</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function labStudentView(key) {
  const p = labPeople().find((x) => x.key === key);
  if (!p) return `<p>${esc(key)}?</p>`;
  if (p.subs.length === 1) return submissionView(p.subs[0].key);
  return `<h1>${esc(p.name)} <span class="muted small">${esc(p.id)}</span></h1>
    ${p.subs.length ? `<p>${esc(L.twice)}:</p>${p.subs.map((s) => `<p><a href="#/sub/${encodeURIComponent(s.key)}">${esc(s.submitter.name)} · ${fmt(s.mark)}</a></p>`).join("")}`
      : `<p class="muted">${esc(L.no_submission)}</p>`}`;
}

function labReview() {
  const todo = M.submissions.filter((s) => !isReviewed(s.key));
  const people = labPeople();
  return `<h1>${esc(L.review)}</h1>${labRosterPanel(people)}
    ${todo.length ? `<div class="tablewrap"><table><tbody>${todo.map((s) => `<tr><td><a href="#/sub/${encodeURIComponent(s.key)}">${s.members.map((m) => esc(m.name)).join(", ")}</a></td><td class="num">${fmt(s.mark)}</td></tr>`).join("")}</tbody></table></div>`
      : `<p class="muted">${esc(L.none)}</p>`}`;
}

function fileViewer(sub) {
  if (!sub.files.length) return `<div class="viewer"><p class="muted" style="padding:1rem">${esc(L.no_files)}</p></div>`;
  const i = Math.min(ui.tab[sub.key] || 0, sub.files.length - 1), f = sub.files[i];
  const tabs = sub.files.map((x, j) => `<button data-filetab="${esc(sub.key)}" data-i="${j}" class="${i === j ? "active" : ""}" title="${esc(x.name)}">${esc(x.name)}</button>`).join("");
  let body;
  if (f.kind === "pdf" || f.kind === "html") body = `<iframe src="${f.url}" ${f.kind === "html" ? 'sandbox=""' : ""} title="${esc(f.name)}"></iframe>`;
  else if (f.kind === "rendered") body = `<iframe src="${f.render}" sandbox="allow-scripts" title="${esc(f.name)}"></iframe>`;
  else if (f.kind === "image") body = `<div class="scroll"><img class="scan" src="${f.url}" alt="${esc(f.name)}"></div>`;
  else if (f.kind === "text") body = `<pre class="code" data-load-text="${f.url}">${esc(L.loading)}</pre>`;
  else if (f.kind === "missing") body = `<p class="muted" style="padding:1rem">${esc(f.name)}: ${esc(L.no_files)}</p>`;
  else body = `<p style="padding:1rem"><a href="${f.url}" target="_blank">${esc(f.name)}</a></p>`;
  return `<div class="viewer"><div class="tabs">${tabs}<span style="flex:1"></span>${f.url ? `<a class="small" href="${f.url}" target="_blank" rel="noopener">${esc(L.open_new)}</a>` : ""}</div><div class="viewer-body">${body}</div></div>`;
}

function submissionView(key) {
  const s = M.submissions.find((x) => x.key === key);
  if (!s) return M.submissions.length ? `<p>${esc(key)}?</p>` : `<p class="muted">${esc(L.no_files)}</p>`;
  setPref(`last.${M.title}.${M.part}`, s.key);
  const d = drafts[s.key] || {};
  const i = M.submissions.indexOf(s), prev = M.submissions[i - 1], next = M.submissions[i + 1];
  const label = (x) => x.members.map((m) => m.name).join(", ") || x.submitter.name || x.key;
  const members = d.members ?? s.members.filter((m) => m.added !== "submitter").map((m) => m.name).join("\n");
  const layout = pref("layout", { files: 50, feedback: 30, rubric: 20 });
  // Own panel on wide screens, below the feedback otherwise, until the teacher chooses.
  const rubricMode = M.rubric_html ? (layout.rubricMode || (window.innerWidth >= 1600 ? "right" : "below")) : "hidden";
  const from = `sub:${s.key}`;
  const options = M.submissions.map((x) => `<option value="${esc(x.key)}" ${x.key === s.key ? "selected" : ""}>${isReviewed(x.key) ? "✓ " : ""}${esc(label(x))}</option>`).join("");
  const chosen = layout.rubricMode || "auto";
  const modeOptions = [["auto", L.rubric_auto], ["right", L.rubric_right], ["below", L.rubric_below], ["hidden", L.rubric_hidden]]
    .map(([v, l]) => `<option value="${v}" ${chosen === v ? "selected" : ""}>${esc(l)}</option>`).join("");
  const rubric = `<details ${rubricMode === "right" ? "open" : ""} class="rubric-box"><summary>${esc(L.rubric_file)}</summary>${M.rubric_html || ""}</details>`;
  const feedbackPane = `<section class="answer pane-card ${isReviewed(s.key) ? "reviewed" : s.edited ? "edited" : ""}" data-card="${esc(s.key)}">
      <div class="head"><span class="muted small">${esc(L.submitter)}: ${esc(s.submitter.name)} ${esc(s.submitter.id)}</span>
        ${s.edited ? `<span class="badge edited">${esc(L.edited)}</span>` : ""}<span style="flex:1"></span>
        <label class="small"><input type="checkbox" data-reviewed="${esc(s.key)}" ${isReviewed(s.key) ? "checked" : ""}> ${esc(L.reviewed)}</label></div>
      <div class="members">${s.members.map((m) => `<span class="badge ${m.roster !== undefined ? "good" : M.roster ? "bad" : ""}" title="${m.added === "submitter" ? esc(L.submitter) : ""}">${esc(m.name)}${m.added === "submitter" ? " ⤴" : ""}</span>`).join("")}</div>
      <div class="row"><label>${esc(L.mark)} <input type="number" step="0.05" min="0" max="10" value="${esc(d.mark ?? s.mark ?? "")}" data-lab-mark="${esc(s.key)}"></label>
        <span class="muted">/ 10</span><span style="flex:1"></span>
        <button class="primary" data-save-lab="${esc(s.key)}" ${d.dirty ? "" : "disabled"}>${esc(L.save)}</button></div>
      <details class="members-edit"><summary class="small">${esc(L.members)}</summary>
        <textarea data-lab-members="${esc(s.key)}" rows="3">${esc(members)}</textarea></details>
      <label class="small muted">${esc(L.feedback)}</label>
      <textarea class="grow" data-feedback="${esc(s.key)}">${esc(d.feedback ?? s.feedback)}</textarea>
      <details class="preview-box" ${showPreview(d, d.feedback ?? s.feedback) ? "open" : ""}><summary class="small">${esc(L.preview)}</summary>
        <div class="preview" data-preview="${esc(s.key)}">${d.preview ?? s.feedback_html}</div></details>
      ${s.edited && s.llm_mark !== null ? `<details class="original"><summary>${esc(L.model_original)}: ${fmt(s.llm_mark)} / 10</summary><pre class="rubric">${esc(s.llm_feedback || "")}</pre></details>` : ""}
      ${rubricMode === "below" ? rubric : ""}</section>`;
  const panes = rubricMode === "right"
    ? [["files", fileViewer(s)], ["feedback", feedbackPane], ["rubric", `<div class="pane-card rubric-pane">${rubric}</div>`]]
    : [["files", fileViewer(s)], ["feedback", feedbackPane]];
  const total = panes.reduce((t, [n]) => t + (layout[n] || 25), 0);
  const html = panes.map(([n, content], j) => `${j ? `<div class="gutter" data-gutter="${j - 1}" role="separator" aria-orientation="vertical" title="${esc(L.drag)}"></div>` : ""}
    <div class="pane pane-${n}" data-pane="${n}" style="flex-basis:${(100 * (layout[n] || 25) / total).toFixed(2)}%">${content}</div>`).join("");
  return `<div class="subbar">
      ${prev ? `<a class="guard" data-from="${esc(from)}" href="#/sub/${encodeURIComponent(prev.key)}" title="${esc(label(prev))}">←</a>` : `<span class="muted">←</span>`}
      <select class="jump" data-from="${esc(from)}" data-prefix="#/sub/" aria-label="${esc(L.submissions)}">${options}</select>
      ${next ? `<a class="guard" data-from="${esc(from)}" href="#/sub/${encodeURIComponent(next.key)}" title="${esc(label(next))}">→</a>` : `<span class="muted">→</span>`}
      <span class="muted small">${i + 1} / ${M.submissions.length}</span>
      ${next ? `<button data-reviewed-next="${esc(s.key)}" data-next="#/sub/${encodeURIComponent(next.key)}">${esc(L.reviewed_next)}</button>` : ""}
      <span style="flex:1"></span>
      ${M.rubric_html ? `<label class="small muted">${esc(L.rubric_file)} <select data-rubric-mode>${modeOptions}</select></label>` : ""}</div>
    <div class="panes" data-panes>${html}</div>`;
}

function pref(name, fallback) {
  try { const v = localStorage.getItem(`review.${name}`); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; }
}

function setPref(name, value) {
  try { localStorage.setItem(`review.${name}`, JSON.stringify(value)); } catch (e) { /* private mode: not kept */ }
}

function applyTheme(theme) {
  if (theme === "light" || theme === "dark") document.documentElement.dataset.theme = theme;
  else delete document.documentElement.dataset.theme;
}

function marksPanel(marks, unit) {
  const sorted = [...marks].sort((a, b) => a - b);
  const passed = marks.filter((m) => m >= 5).length;
  const stat = (v, l) => `<div class="stat"><span class="v">${esc(v)}</span><span class="l">${esc(l)}</span></div>`;
  return `<section class="panel"><h2 class="ph">${esc(L.marks)} <span class="muted small">${marks.length} ${esc(unit)}</span></h2>
    <div class="marks"><div class="stats">
      ${stat(fmt(mean(marks)), L.mean)}${stat(fmt(median(marks)), L.median)}
      ${stat(marks.length ? `${fmt(sorted[0])} – ${fmt(sorted[sorted.length - 1])}` : "–", L.range)}
      ${stat(`${passed} / ${marks.length}`, L.passed)}
      <div class="passbar" title="${esc(L.passed)}"><span style="width:${marks.length ? Math.round(100 * passed / marks.length) : 0}%"></span></div>
    </div><div class="histbox">${histogram(marks)}</div></div></section>`;
}

function progressPanel(total, reviewed, edited, pending, unit) {
  const p = total ? Math.round(100 * reviewed / total) : 0;
  const done = total && reviewed === total
    ? `<p class="done">✓ ${esc(L.review_done)}${M.rebuild.some((a) => a.id === "upload") ? ` ${esc(L.review_done_upload)}` : ""}</p>` : "";
  return `<section class="panel"><h2 class="ph">${esc(L.progress)}</h2>${done}
    <div class="progress"><div class="bar"><span style="width:${p}%"></span></div>
      <div class="progress-legend"><strong>${reviewed} / ${total}</strong> ${esc(unit)} ${esc(L.reviewed_plural)} (${p}%)
        · <span class="badge edited">${edited} ${esc(L.edited_plural)}</span>
        ${pending === null ? "" : pending ? `· <a class="badge warn" href="#/review">${pending} ${esc(L.flagged_pending)}</a>` : `· <span class="badge good">${esc(L.none)}</span>`}</div></div></section>`;
}

function helpView() {
  const h = L.help_text;
  return `<h1>${esc(L.help)}</h1>${h.map(([title, body]) => `<section class="panel"><h2 class="ph">${esc(title)}</h2>${body}</section>`).join("")}`;
}

function unreviewedFrom(from) {
  const [kind, key] = [from.slice(0, from.indexOf(":")), from.slice(from.indexOf(":") + 1)];
  if (kind === "sub") return !isReviewed(key);
  if (kind === "student") return M.answers.some((a) => a.student === key && a.type === "open" && !isReviewed(a.key));
  return false;
}

function guardedGo(from, href) {
  let shown = false;
  try { shown = sessionStorage.getItem("review.reminded") === "1"; } catch (e) { /* ignore */ }
  if (!from || !unreviewedFrom(from) || pref("noRemind", false) || shown) { location.hash = href; return; }
  try { sessionStorage.setItem("review.reminded", "1"); } catch (e) { /* ignore */ }
  const dialog = $("#remind");
  $("#remind-text").innerHTML = L.remind_text;
  $("#remind-title").textContent = L.remind_title;
  $("#remind-stay").textContent = L.remind_stay;
  $("#remind-go").textContent = L.remind_go;
  $("#remind-never").textContent = L.remind_never;
  dialog.onclose = () => {
    if (dialog.returnValue === "go") location.hash = href;
    else if (dialog.returnValue === "never") { setPref("noRemind", true); location.hash = href; }
    else render(false);  // stay: put the selector back on this student
  };
  dialog.showModal();
}

function bindLayout(root) {
  root.querySelectorAll("a.guard").forEach((a) => a.addEventListener("click", (ev) => {
    ev.preventDefault();
    guardedGo(a.dataset.from, a.getAttribute("href"));
  }));
  root.querySelectorAll("select.jump").forEach((sel) => sel.addEventListener("change", () =>
    guardedGo(sel.dataset.from, `${sel.dataset.prefix}${encodeURIComponent(sel.value)}`)));
  root.querySelectorAll("[data-reviewed-next]").forEach((b) => b.addEventListener("click", async () => {
    if (await setReviewed([b.dataset.reviewedNext], true)) location.hash = b.dataset.next;
  }));
  root.querySelectorAll("[data-rubric-mode]").forEach((sel) => sel.addEventListener("change", () => {
    const layout = { ...pref("layout", { files: 50, feedback: 30, rubric: 20 }), rubricMode: sel.value };
    if (sel.value === "auto") delete layout.rubricMode;
    setPref("layout", layout);
    render(false);
  }));
  const panes = root.querySelector("[data-panes]");
  if (!panes) return;
  panes.querySelectorAll(".gutter").forEach((gutter) => {
    gutter.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      const left = gutter.previousElementSibling, right = gutter.nextElementSibling;
      const startX = ev.clientX, lw = left.getBoundingClientRect().width, rw = right.getBoundingClientRect().width;
      const width = panes.getBoundingClientRect().width;
      panes.classList.add("dragging");
      gutter.setPointerCapture(ev.pointerId);
      const move = (e) => {
        const dx = Math.max(-lw + 180, Math.min(rw - 180, e.clientX - startX));
        left.style.flexBasis = `${(100 * (lw + dx) / width).toFixed(2)}%`;
        right.style.flexBasis = `${(100 * (rw - dx) / width).toFixed(2)}%`;
      };
      const up = () => {
        gutter.removeEventListener("pointermove", move);
        gutter.removeEventListener("pointerup", up);
        panes.classList.remove("dragging");
        const name = panes.dataset.panes || "layout";
        const layout = pref(name, {});
        panes.querySelectorAll("[data-pane]").forEach((p) => { layout[p.dataset.pane] = parseFloat(p.style.flexBasis); });
        setPref(name, layout);
      };
      gutter.addEventListener("pointermove", move);
      gutter.addEventListener("pointerup", up);
    });
  });
}

function bindCardGutters(root) {
  root.querySelectorAll("[data-cgutter]").forEach((gutter) => gutter.addEventListener("pointerdown", (ev) => {
    ev.preventDefault();
    const grid = gutter.parentElement, box = grid.getBoundingClientRect();
    gutter.setPointerCapture(ev.pointerId);
    document.body.classList.add("dragging");
    const move = (e) => {
      const p = Math.max(20, Math.min(80, 100 * (e.clientX - box.left) / box.width));
      document.documentElement.style.setProperty("--imgw", `${p.toFixed(1)}%`);
    };
    const up = () => {
      gutter.removeEventListener("pointermove", move);
      gutter.removeEventListener("pointerup", up);
      document.body.classList.remove("dragging");
      setPref("imgw", document.documentElement.style.getPropertyValue("--imgw"));
    };
    gutter.addEventListener("pointermove", move);
    gutter.addEventListener("pointerup", up);
  }));
}

function isPaged(a) {
  // Blank-paper exams: the answer is somewhere in the student's whole pages, not in a crop.
  return a.images.length > 0 && a.images.every((im) => /^page \d+$/.test(im.label));
}

function pageLabel(label) {
  return label.replace(/^page (\d+)$/, `${L.page} $1`);
}

function pagesColumn(images) {
  return `<div class="pages">${images.map((im) => `<figure><figcaption class="small muted">${esc(pageLabel(im.label))}</figcaption>
    <a href="${im.url}" target="_blank" rel="noopener" title="${esc(L.open_new)}"><img class="scan" loading="lazy" src="${im.url}" alt="${esc(pageLabel(im.label))}"></a></figure>`).join("")}</div>`;
}

// --- Events ------------------------------------------------------------------------------------------
let previewTimer = null;

function markDirty(key, patch) {
  drafts[key] = { ...(drafts[key] || {}), ...patch, dirty: true };
  const card = document.querySelector(`[data-card="${CSS.escape(key)}"]`);
  if (card) card.querySelectorAll("button.primary[data-save-open], button.primary[data-save-lab]").forEach((b) => { b.disabled = false; });
}

function bind(root) {
  root.querySelectorAll("table.sortable").forEach(sortable);
  root.querySelectorAll("[data-ui]").forEach((el) => el.addEventListener("change", () => { ui[el.dataset.ui] = el.value; render(false); }));
  root.querySelectorAll("[data-imgtab]").forEach((b) => b.addEventListener("click", () => { ui.tab[b.dataset.imgtab] = +b.dataset.i; render(false); }));
  root.querySelectorAll("[data-filetab]").forEach((b) => b.addEventListener("click", () => { ui.tab[b.dataset.filetab] = +b.dataset.i; render(false); }));
  root.querySelectorAll("[data-load-text]").forEach(async (pre) => {
    try { pre.textContent = await (await fetch(pre.dataset.loadText)).text(); } catch (e) { pre.textContent = e.message; }
  });
  root.querySelectorAll("[data-score]").forEach((el) => el.addEventListener("input", () => markDirty(el.dataset.score, { score: el.value })));
  root.querySelectorAll("[data-lab-mark]").forEach((el) => el.addEventListener("input", () => markDirty(el.dataset.labMark, { mark: el.value })));
  root.querySelectorAll("[data-lab-members]").forEach((el) => el.addEventListener("input", () => markDirty(el.dataset.labMembers, { members: el.value })));
  root.querySelectorAll("[data-feedback]").forEach((el) => {
    el.addEventListener("input", () => {
      const key = el.dataset.feedback;
      markDirty(key, { feedback: el.value });
      clearTimeout(previewTimer);
      previewTimer = setTimeout(async () => {
        try {
          const { html } = await api("/api/markdown", { text: el.value, mode: M.kind === "lab" ? "comment" : "markdown" });
          drafts[key].preview = html;
          const box = document.querySelector(`[data-preview="${CSS.escape(key)}"]`);
          if (box) { box.hidden = false; box.innerHTML = html; typeset(box); }
        } catch (e) { /* preview only */ }
      }, 350);
    });
    el.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
        ev.preventDefault();
        const card = el.closest("[data-card]");
        const button = card && card.querySelector("[data-save-open], [data-save-lab]");
        if (button) button.click();
      }
    });
  });
  root.querySelectorAll("[data-save-open]").forEach((b) => b.addEventListener("click", async () => {
    const a = M.A[b.dataset.saveOpen], d = drafts[a.key] || {};
    const ok = await save("open", { student_id: a.source.student_id, question_id: a.source.question_id,
      score: d.score ?? a.score, feedback: d.feedback ?? a.feedback, version: M.versions.open });
    if (ok) { delete drafts[a.key]; if (!isReviewed(a.key)) { await setReviewed([a.key], true); render(false); } }
  }));
  root.querySelectorAll("[data-save-lab]").forEach((b) => b.addEventListener("click", async () => {
    const s = M.submissions.find((x) => x.key === b.dataset.saveLab), d = drafts[s.key] || {};
    const members = (d.members ?? s.members.filter((m) => m.added !== "submitter").map((m) => m.name).join("\n")).split("\n").map((x) => x.trim()).filter(Boolean);
    const ok = await save("lab", { key: s.key, mark: d.mark ?? s.mark, feedback: d.feedback ?? s.feedback, members, version: s.version });
    if (ok) { delete drafts[s.key]; if (!isReviewed(s.key)) { await setReviewed([s.key], true); render(false); } }
  }));
  root.querySelectorAll("[data-reviewed]").forEach((el) => el.addEventListener("change", async () => {
    if (await setReviewed([el.dataset.reviewed], el.checked)) {
      const card = el.closest(".answer");
      if (card) card.classList.toggle("reviewed", el.checked);
    }
  }));
  root.querySelectorAll("[data-mark-visible]").forEach((b) => {
    b.textContent = L.mark_shown.replace("{n}", root.querySelectorAll("[data-reviewed]").length);
  });
  root.querySelectorAll("[data-mark-visible]").forEach((b) => b.addEventListener("click", async () => {
    const keys = [...root.querySelectorAll("[data-reviewed]")].map((el) => el.dataset.reviewed);
    if (await setReviewed(keys, true)) render(false);
  }));
  root.querySelectorAll("[data-mc]").forEach((el) => el.addEventListener("change", () =>
    save("mc", { page: el.dataset.page, number: el.dataset.number, letter: el.value, n_options: +el.dataset.n, version: M.versions.mc })));
  root.querySelectorAll("[data-save-student]").forEach((b) => b.addEventListener("click", () => {
    const s = M.S[b.dataset.saveStudent];
    const box = b.closest("details");
    let id = $("[data-sid]", box).value.trim(), name = $("[data-sname]", box).value.trim();
    const fromRoster = M.roster && M.roster.students.find((r) => r.name === name);
    if (fromRoster && fromRoster.id && id === s.id && !s.id.includes(fromRoster.id)) id = fromRoster.id;
    save("student", { page: s.page, student_id: id, student_name: name, versions: M.versions }).then((ok) => {
      if (ok && id !== s.key) location.hash = `#/s/${encodeURIComponent(id)}`;
    });
  }));
}

window.addEventListener("hashchange", () => render());
// Follow the screen size while the teacher has not chosen where the rubric goes.
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (M && !pref("layout", {}).rubricMode && document.querySelector("[data-rubric-mode]")) render(false); }, 300);
});
// Closing the tab stops the server (edits are already saved): the browser asks first. Its dialog
// cannot show our text, so the notice at the bottom of the page explains it.
window.addEventListener("beforeunload", (ev) => { ev.preventDefault(); ev.returnValue = ""; });

// The server stops when its page is closed: ping while open, say goodbye on close or reload.
// If the server stops (closed elsewhere, Ctrl+C, the computer slept), say so and keep checking:
// every 10 s while connected, every 3 s while disconnected; reload the data when it is back.
let offline = false;
async function ping() {
  let ok = false;
  try { ok = (await fetch("/api/ping", { cache: "no-store" })).ok; } catch (e) { ok = false; }
  if (!ok && !offline) {
    offline = true;
    $("#offline").hidden = false;
    $("#offline").innerHTML = `<strong>${esc(L.offline_title)}</strong> ${esc(L.offline_text)} <code>${esc((M && M.rerun) || "")}</code>`;
  } else if (ok && offline) {
    offline = false;
    $("#offline").hidden = true;
    try { await loadModel(); render(false); status(L.online_again); } catch (e) { /* next ping */ }
  }
  setTimeout(ping, offline ? 3000 : 10000);
}
setTimeout(ping, 10000);
window.addEventListener("pagehide", () => { try { navigator.sendBeacon("/api/bye"); } catch (e) { /* ignore */ } });

(async () => {
  const imgw = pref("imgw", null);
  if (imgw) document.documentElement.style.setProperty("--imgw", imgw);
  try {
    await loadModel();
    const last = pref(`part.${M.title}`, null);
    if (last && last !== M.part && M.parts.some((x) => x.id === last)) { PART = last; await loadModel(); }
    render();
  }
  catch (e) { $("#main").innerHTML = `<p style="color:var(--bad)">${esc(e.message)}</p>`; }
})();
