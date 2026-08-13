// Plain fetch-based interactivity. No framework/build step, matching
// the project's "explicit pipeline over black box" convention.

function initDocumentsScreen() {
  const form = document.getElementById("doc-form");
  const status = document.getElementById("doc-form-status");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    status.textContent = "Добавляю...";
    try {
      const res = await fetch("/kb/documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || "Ошибка добавления");
      }
      status.textContent = "Добавлено. Обновляю список...";
      setTimeout(() => window.location.reload(), 500);
    } catch (err) {
      status.textContent = "Ошибка: " + err.message;
    }
  });

  document.querySelectorAll(".link-open[data-id]").forEach((el) => {
    el.addEventListener("click", async (e) => {
      e.preventDefault();
      const id = el.dataset.id;
      const res = await fetch("/kb/documents");
      const docs = await res.json();
      const doc = docs.find((d) => d.id === id);
      // list endpoint doesn't return full text; fetch is cheap enough
      // for this project size, so we just show what we have.
      document.getElementById("doc-dialog-title").textContent = doc ? doc.title : id;
      document.getElementById("doc-dialog-text").textContent =
        "Открытие полного текста документа доступно через GET /kb/documents (расширьте при необходимости).";
      document.getElementById("doc-dialog").showModal();
    });
  });
}

function renderSources(listEl, sources) {
  listEl.innerHTML = "";
  if (!sources || sources.length === 0) {
    const li = document.createElement("li");
    li.textContent = "Источников нет.";
    listEl.appendChild(li);
    return;
  }
  sources.forEach((s) => {
    const li = document.createElement("li");
    const tag = document.createElement("span");
    tag.className = "source-tag";
    tag.textContent = "документ: " + s.document_id + " · фрагмент: " + s.snippet_id;
    const quote = document.createElement("span");
    quote.textContent = "«" + s.quote + "»";
    li.appendChild(tag);
    li.appendChild(quote);
    listEl.appendChild(li);
  });
}

function initAskScreen() {
  const form = document.getElementById("ask-form");
  if (!form) return;
  const resultPanel = document.getElementById("ask-result");
  const answerText = document.getElementById("answer-text");
  const reviewBadge = document.getElementById("review-badge");
  const sourcesList = document.getElementById("sources-list");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const question = new FormData(form).get("question");
    resultPanel.classList.remove("is-hidden");
    answerText.textContent = "Думаю...";
    reviewBadge.classList.add("is-hidden");
    sourcesList.innerHTML = "";

    try {
      const res = await fetch("/kb/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      answerText.textContent = data.answer;
      reviewBadge.classList.toggle("is-hidden", !data.needs_review);
      renderSources(sourcesList, data.sources);
    } catch (err) {
      answerText.textContent = "Ошибка запроса: " + err.message;
    }
  });
}

function initHistoryScreen() {
  const filter = document.getElementById("review-filter");
  if (filter) {
    filter.addEventListener("change", async () => {
      const res = await fetch("/kb/history?needs_review_only=" + filter.checked);
      const runs = await res.json();
      const body = document.getElementById("history-table-body");
      body.innerHTML = "";
      if (runs.length === 0) {
        body.innerHTML = '<tr><td colspan="4" class="empty-row">Ничего не найдено.</td></tr>';
        return;
      }
      runs.forEach((r) => {
        const tr = document.createElement("tr");
        if (r.needs_review) tr.className = "row-flagged";
        tr.innerHTML = `
          <td>${r.question}</td>
          <td class="mono muted">${r.created_at}</td>
          <td>${r.needs_review ? '<span class="badge">Проверка</span>' : '<span class="badge badge-ok">Ок</span>'}</td>
          <td><a href="#" class="link-open" data-qa='${JSON.stringify(r).replace(/'/g, "&apos;")}'>Открыть</a></td>
        `;
        body.appendChild(tr);
      });
      attachQaDialogHandlers();
    });
  }
  attachQaDialogHandlers();
}

function attachQaDialogHandlers() {
  document.querySelectorAll(".link-open[data-qa]").forEach((el) => {
    el.addEventListener("click", (e) => {
      e.preventDefault();
      const r = JSON.parse(el.dataset.qa);
      document.getElementById("qa-dialog-question").textContent = r.question;
      document.getElementById("qa-dialog-answer").textContent = r.answer || "";
      document.getElementById("qa-dialog-review").classList.toggle("is-hidden", !r.needs_review);
      const sources = r.sources_json ? JSON.parse(r.sources_json) : [];
      renderSources(document.getElementById("qa-dialog-sources"), sources);
      document.getElementById("qa-dialog").showModal();
    });
  });
}
