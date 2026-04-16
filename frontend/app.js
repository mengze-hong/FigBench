/* ═══════════════════════════════════════════════════════════════
   AcademicFigureGallery – Frontend Application
   ═══════════════════════════════════════════════════════════════ */

const API = window.location.origin;

// ── State ─────────────────────────────────────────────────────
let state = {
    page: 1,
    perPage: 24,
    query: "",
    selectedTags: new Set(),
    figureType: "",
    layoutType: "",
    venue: "",
    sort: "created_at",
    order: "DESC",
    totalPages: 1,
};

// ── DOM refs ──────────────────────────────────────────────────
const $grid       = document.getElementById("galleryGrid");
const $loading    = document.getElementById("loadingIndicator");
const $empty      = document.getElementById("emptyState");
const $pagination = document.getElementById("pagination");
const $search     = document.getElementById("searchInput");
const $filterType = document.getElementById("filterType");
const $filterLayout= document.getElementById("filterLayout");
const $filterVenue= document.getElementById("filterVenue");
const $filterSort = document.getElementById("filterSort");
const $tagsBar    = document.getElementById("tagsBar");
const $overlay    = document.getElementById("modalOverlay");
const $modal      = document.getElementById("figureModal");

// ── Init ──────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
    await loadStats();
    await loadFilters();
    await loadFigures();
    bindEvents();
});

// ── Data Loading ──────────────────────────────────────────────

async function api(path) {
    const res = await fetch(API + path);
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return res.json();
}

async function loadStats() {
    try {
        const s = await api("/api/stats");
        document.getElementById("statFigures").textContent = s.figures.toLocaleString();
        document.getElementById("statPapers").textContent = s.papers.toLocaleString();
        document.getElementById("statVenues").textContent = s.venues.length;
    } catch (e) {
        console.warn("Stats unavailable:", e);
    }
}

async function loadFilters() {
    try {
        const { types } = await api("/api/figure-types");
        types.forEach(t => {
            const opt = document.createElement("option");
            opt.value = t;
            opt.textContent = t.charAt(0).toUpperCase() + t.slice(1);
            $filterType.appendChild(opt);
        });
        const { tags } = await api("/api/tags");
        $tagsBar.innerHTML = tags.map(t =>
            `<span class="tag-chip" data-tag="${t}">${t}</span>`
        ).join("");
    } catch (e) {
        console.warn("Filters unavailable:", e);
    }
}

async function loadFigures() {
    $loading.style.display = "block";
    $empty.style.display = "none";
    $grid.innerHTML = "";

    const params = new URLSearchParams({
        page: state.page, per_page: state.perPage,
        sort: state.sort, order: state.order,
    });
    if (state.query) params.set("q", state.query);
    if (state.selectedTags.size) params.set("tags", [...state.selectedTags].join(","));
    if (state.figureType) params.set("figure_type", state.figureType);
    if (state.layoutType) params.set("layout_type", state.layoutType);
    if (state.venue) params.set("venue", state.venue);

    try {
        const data = await api(`/api/figures?${params}`);
        $loading.style.display = "none";
        if (!data.items.length) {
            $empty.style.display = "block";
            $pagination.innerHTML = "";
            return;
        }
        state.totalPages = data.pages;
        renderGrid(data.items);
        renderPagination(data);
    } catch (e) {
        $loading.style.display = "none";
        $empty.style.display = "block";
    }
}

// ── Render ────────────────────────────────────────────────────

function renderGrid(items) {
    $grid.innerHTML = items.map(fig => {
        const tags = Array.isArray(fig.tags) ? fig.tags : [];
        const displayTags = tags.slice(0, 4);
        const layout = fig.layout_type || '';
        return `
        <div class="figure-card" data-id="${fig.id}">
            <div class="card-image-wrap">
                <img src="${API}${fig.image_url}" alt="${escHtml(fig.description || '')}" loading="lazy">
                ${fig.figure_type ? `<span class="card-type">${escHtml(fig.figure_type)}</span>` : ''}
                ${layout ? `<span class="card-layout card-layout-${layout}">${layout}</span>` : ''}
                <button class="card-delete" data-id="${fig.id}" title="Flag as bad figure">\u00d7</button>
            </div>
            <div class="card-body">
                <p class="card-desc">${escHtml(fig.description || 'No description')}</p>
                <p class="card-paper">${escHtml(fig.paper_title || '')} \u00b7 ${escHtml(fig.venue || '')} ${fig.year || ''}</p>
                <div class="card-tags">
                    ${displayTags.map(t => `<span class="mini-tag">${escHtml(t)}</span>`).join("")}
                    ${tags.length > 4 ? `<span class="mini-tag">+${tags.length - 4}</span>` : ''}
                </div>
            </div>
        </div>`;
    }).join("");
}

function renderPagination(data) {
    if (data.pages <= 1) { $pagination.innerHTML = ""; return; }
    let html = `<button class="page-btn" ${data.page <= 1 ? 'disabled' : ''} data-page="${data.page - 1}">\u2190 Prev</button>`;
    const range = getPageRange(data.page, data.pages);
    for (const p of range) {
        if (p === "...") {
            html += `<span class="page-btn" style="border:none;cursor:default;">\u2026</span>`;
        } else {
            html += `<button class="page-btn ${p === data.page ? 'active' : ''}" data-page="${p}">${p}</button>`;
        }
    }
    html += `<button class="page-btn" ${data.page >= data.pages ? 'disabled' : ''} data-page="${data.page + 1}">Next \u2192</button>`;
    $pagination.innerHTML = html;
}

function getPageRange(current, total) {
    if (total <= 7) return Array.from({length: total}, (_, i) => i + 1);
    const pages = [];
    if (current <= 4) {
        for (let i = 1; i <= 5; i++) pages.push(i);
        pages.push("...", total);
    } else if (current >= total - 3) {
        pages.push(1, "...");
        for (let i = total - 4; i <= total; i++) pages.push(i);
    } else {
        pages.push(1, "...", current - 1, current, current + 1, "...", total);
    }
    return pages;
}

// ── Modal (Editable + Crop) ───────────────────────────────────

let currentFigure = null;
let cropMode = false;
let cropStart = null;
let cropRect = null;

async function openModal(figureId) {
    try {
        const fig = await api(`/api/figures/${figureId}`);
        currentFigure = fig;

        const imgEl = document.getElementById("modalImage");
        imgEl.src = API + fig.image_url + "?t=" + Date.now();

        document.getElementById("modalDescription").value = fig.description || "";
        document.getElementById("modalPaperTitle").textContent = fig.paper_title || "Unknown";
        document.getElementById("modalPaperTitle").href = fig.paper_url || "#";
        document.getElementById("modalAuthors").textContent = fig.authors || "\u2013";
        document.getElementById("modalVenue").textContent = `${fig.venue || ''} ${fig.year || ''}`;
        document.getElementById("modalType").value = fig.figure_type || "other";
        document.getElementById("modalLayout").value = fig.layout_type || "standalone";

        const captionRow = document.getElementById("modalCaptionRow");
        if (fig.caption) {
            document.getElementById("modalCaption").textContent = fig.caption;
            captionRow.style.display = "";
        } else {
            captionRow.style.display = "none";
        }

        const tags = Array.isArray(fig.tags) ? fig.tags : [];
        document.getElementById("modalTagsInput").value = tags.join(", ");

        exitCropMode();
        document.getElementById("saveStatus").textContent = "";

        $overlay.classList.add("open");
        document.body.style.overflow = "hidden";
    } catch (e) {
        console.error("Modal load error:", e);
    }
}

function closeModal() {
    exitCropMode();
    // Also exit paste mode
    const pz = document.getElementById("pasteZone");
    const br = document.getElementById("btnReplace");
    if (pz) pz.style.display = "none";
    if (br) br.textContent = "📋 Replace";
    currentFigure = null;
    $overlay.classList.remove("open");
    document.body.style.overflow = "";
}

async function saveEdits() {
    if (!currentFigure) return;
    const statusEl = document.getElementById("saveStatus");
    statusEl.textContent = "Saving...";
    statusEl.className = "save-status";

    const tagsRaw = document.getElementById("modalTagsInput").value;
    const tags = tagsRaw.split(",").map(t => t.trim()).filter(t => t.length > 0);

    const body = {
        description: document.getElementById("modalDescription").value.trim(),
        tags: tags,
        figure_type: document.getElementById("modalType").value,
        layout_type: document.getElementById("modalLayout").value,
    };

    try {
        const res = await fetch(`${API}/api/figures/${currentFigure.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            statusEl.textContent = "\u2713 Saved!";
            statusEl.className = "save-status save-ok";
            loadFigures();
        } else {
            statusEl.textContent = "\u2717 Save failed";
            statusEl.className = "save-status save-err";
        }
    } catch (e) {
        statusEl.textContent = "\u2717 " + e.message;
        statusEl.className = "save-status save-err";
    }
}

// ── Crop ──────────────────────────────────────────────────────

function enterCropMode() {
    if (!currentFigure) return;
    cropMode = true;
    cropRect = null;

    const imgEl = document.getElementById("modalImage");
    const wrap = imgEl.parentElement; // .modal-image-wrap
    const canvas = document.getElementById("cropCanvas");

    // Canvas covers the entire wrap container
    const wrapRect = wrap.getBoundingClientRect();
    canvas.width = wrapRect.width;
    canvas.height = wrapRect.height;
    canvas.style.display = "block";
    canvas.style.width = wrapRect.width + "px";
    canvas.style.height = wrapRect.height + "px";
    canvas.style.top = "0";
    canvas.style.left = "0";

    // Calculate where the actual image is rendered within the container
    // (accounting for object-fit: contain and padding)
    const natW = imgEl.naturalWidth;
    const natH = imgEl.naturalHeight;
    const style = getComputedStyle(imgEl);
    const padT = parseFloat(style.paddingTop) || 0;
    const padL = parseFloat(style.paddingLeft) || 0;
    const padR = parseFloat(style.paddingRight) || 0;
    const padB = parseFloat(style.paddingBottom) || 0;

    // The img element rect relative to wrap
    const imgRect = imgEl.getBoundingClientRect();
    const imgOffX = imgRect.left - wrapRect.left;
    const imgOffY = imgRect.top - wrapRect.top;

    // With object-fit: contain, the image fits inside the content box
    const contentW = imgRect.width - padL - padR;
    const contentH = imgRect.height - padT - padB;

    const scale = Math.min(contentW / natW, contentH / natH);
    const renderedW = natW * scale;
    const renderedH = natH * scale;

    // Actual image position within the canvas
    const imgX = imgOffX + padL + (contentW - renderedW) / 2;
    const imgY = imgOffY + padT + (contentH - renderedH) / 2;

    // Store image render info on canvas for coordinate mapping
    canvas._imgX = imgX;
    canvas._imgY = imgY;
    canvas._imgW = renderedW;
    canvas._imgH = renderedH;
    canvas._scaleX = natW / renderedW;
    canvas._scaleY = natH / renderedH;

    document.getElementById("btnCropStart").style.display = "none";
    document.getElementById("btnCropConfirm").style.display = "";
    document.getElementById("btnCropCancel").style.display = "";

    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "rgba(0,0,0,0.3)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    // Clear the image area to show it's the croppable region
    ctx.clearRect(imgX, imgY, renderedW, renderedH);
    ctx.fillStyle = "rgba(0,0,0,0.3)";
    ctx.fillRect(imgX, imgY, renderedW, renderedH);
}

function exitCropMode() {
    cropMode = false;
    cropRect = null;
    cropStart = null;
    const canvas = document.getElementById("cropCanvas");
    if (canvas) {
        canvas.style.display = "none";
    }
    const s = document.getElementById("btnCropStart");
    const c = document.getElementById("btnCropConfirm");
    const x = document.getElementById("btnCropCancel");
    if (s) s.style.display = "";
    if (c) c.style.display = "none";
    if (x) x.style.display = "none";
}

function drawCropOverlay(canvas, rect) {
    const ctx = canvas.getContext("2d");
    const imgX = canvas._imgX, imgY = canvas._imgY;
    const imgW = canvas._imgW, imgH = canvas._imgH;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Dark overlay on everything
    ctx.fillStyle = "rgba(0,0,0,0.5)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (rect && rect.w > 0 && rect.h > 0) {
        // Clear the selection area (make it bright)
        ctx.clearRect(rect.x, rect.y, rect.w, rect.h);
        // Draw selection border
        ctx.strokeStyle = "#2563eb";
        ctx.lineWidth = 2;
        ctx.setLineDash([6, 3]);
        ctx.strokeRect(rect.x, rect.y, rect.w, rect.h);
        ctx.setLineDash([]);
    } else {
        // Just show the image area slightly lighter
        ctx.clearRect(imgX, imgY, imgW, imgH);
        ctx.fillStyle = "rgba(0,0,0,0.25)";
        ctx.fillRect(imgX, imgY, imgW, imgH);
    }
}

async function applyCrop() {
    if (!cropRect || !currentFigure) return;
    const canvas = document.getElementById("cropCanvas");

    // Convert canvas coords to image-relative coords
    const relX = cropRect.x - canvas._imgX;
    const relY = cropRect.y - canvas._imgY;
    const relW = cropRect.w;
    const relH = cropRect.h;

    // Map to original image pixel coords
    const body = {
        x: Math.max(0, Math.round(relX * canvas._scaleX)),
        y: Math.max(0, Math.round(relY * canvas._scaleY)),
        width: Math.round(relW * canvas._scaleX),
        height: Math.round(relH * canvas._scaleY),
    };
    if (body.width < 50 || body.height < 50) { alert("Too small (min 50x50)"); return; }

    const statusEl = document.getElementById("saveStatus");
    statusEl.textContent = "Cropping...";
    try {
        const res = await fetch(`${API}/api/figures/${currentFigure.id}/crop`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (res.ok) {
            statusEl.textContent = "\u2713 Cropped!";
            statusEl.className = "save-status save-ok";
            document.getElementById("modalImage").src = API + currentFigure.image_url + "?t=" + Date.now();
            exitCropMode();
            loadFigures();
        } else {
            statusEl.textContent = "\u2717 Crop failed";
            statusEl.className = "save-status save-err";
        }
    } catch (e) {
        statusEl.textContent = "\u2717 " + e.message;
        statusEl.className = "save-status save-err";
    }
}

// ── Events ────────────────────────────────────────────────────

function bindEvents() {
    let debounce;
    $search.addEventListener("input", () => {
        clearTimeout(debounce);
        debounce = setTimeout(() => { state.query = $search.value.trim(); state.page = 1; loadFigures(); }, 350);
    });

    $filterType.addEventListener("change", () => { state.figureType = $filterType.value; state.page = 1; loadFigures(); });
    $filterLayout.addEventListener("change", () => { state.layoutType = $filterLayout.value; state.page = 1; loadFigures(); });

    api("/api/stats").then(s => {
        if (s.venues) s.venues.forEach(v => {
            const opt = document.createElement("option"); opt.value = v; opt.textContent = v;
            $filterVenue.appendChild(opt);
        });
    }).catch(() => {});
    $filterVenue.addEventListener("change", () => { state.venue = $filterVenue.value; state.page = 1; loadFigures(); });

    $filterSort.addEventListener("change", () => {
        const [s, o] = $filterSort.value.split("|");
        state.sort = s; state.order = o; state.page = 1; loadFigures();
    });

    $tagsBar.addEventListener("click", e => {
        const chip = e.target.closest(".tag-chip");
        if (!chip) return;
        const tag = chip.dataset.tag;
        if (state.selectedTags.has(tag)) { state.selectedTags.delete(tag); chip.classList.remove("active"); }
        else { state.selectedTags.add(tag); chip.classList.add("active"); }
        state.page = 1; loadFigures();
    });

    $grid.addEventListener("click", e => {
        const delBtn = e.target.closest(".card-delete");
        if (delBtn) { e.stopPropagation(); deleteFigure(delBtn.dataset.id, delBtn); return; }
        const card = e.target.closest(".figure-card");
        if (card) openModal(card.dataset.id);
    });

    $pagination.addEventListener("click", e => {
        const btn = e.target.closest(".page-btn[data-page]");
        if (!btn || btn.disabled) return;
        state.page = parseInt(btn.dataset.page); loadFigures();
        window.scrollTo({ top: 0, behavior: "smooth" });
    });

    // Modal close
    document.getElementById("modalClose").addEventListener("click", closeModal);
    $overlay.addEventListener("click", e => { if (e.target === $overlay) closeModal(); });
    document.addEventListener("keydown", e => { if (e.key === "Escape") closeModal(); });

    // Save edits
    document.getElementById("btnSave").addEventListener("click", saveEdits);

    // Crop buttons
    document.getElementById("btnCropStart").addEventListener("click", enterCropMode);
    document.getElementById("btnCropConfirm").addEventListener("click", applyCrop);
    document.getElementById("btnCropCancel").addEventListener("click", exitCropMode);

    // Replace via paste
    const pasteZone = document.getElementById("pasteZone");
    const btnReplace = document.getElementById("btnReplace");
    let pasteMode = false;

    btnReplace.addEventListener("click", () => {
        pasteMode = !pasteMode;
        pasteZone.style.display = pasteMode ? "flex" : "none";
        btnReplace.textContent = pasteMode ? "📋 Cancel Replace" : "📋 Replace";
    });

    document.addEventListener("paste", async (e) => {
        if (!pasteMode || !currentFigure) return;
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.type.startsWith("image/")) {
                e.preventDefault();
                const file = item.getAsFile();
                const reader = new FileReader();
                reader.onload = async () => {
                    const b64 = reader.result; // data:image/png;base64,...
                    try {
                        pasteZone.querySelector("p").textContent = "Uploading...";
                        const res = await fetch(`${API}/api/figures/${currentFigure.id}/replace`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ image_data: b64 }),
                        });
                        if (res.ok) {
                            // Refresh image
                            const modalImg = document.getElementById("modalImage");
                            modalImg.src = modalImg.src.split("?")[0] + "?t=" + Date.now();
                            pasteMode = false;
                            pasteZone.style.display = "none";
                            btnReplace.textContent = "📋 Replace";
                            loadFigures(); // refresh grid too
                        } else {
                            alert("Replace failed: " + (await res.text()));
                        }
                    } catch (err) {
                        alert("Replace error: " + err.message);
                    }
                    pasteZone.querySelector("p").textContent = "Paste image here";
                };
                reader.readAsDataURL(file);
                return;
            }
        }
    });

    // Crop canvas mouse events — clamp to image area
    const canvas = document.getElementById("cropCanvas");
    function clampToImg(x, y) {
        const ix = canvas._imgX || 0, iy = canvas._imgY || 0;
        const iw = canvas._imgW || canvas.width, ih = canvas._imgH || canvas.height;
        return {
            x: Math.max(ix, Math.min(ix + iw, x)),
            y: Math.max(iy, Math.min(iy + ih, y)),
        };
    }
    canvas.addEventListener("mousedown", e => {
        if (!cropMode) return;
        const r = canvas.getBoundingClientRect();
        const pt = clampToImg(e.clientX - r.left, e.clientY - r.top);
        cropStart = pt;
        cropRect = null;
    });
    canvas.addEventListener("mousemove", e => {
        if (!cropMode || !cropStart) return;
        const r = canvas.getBoundingClientRect();
        const pt = clampToImg(e.clientX - r.left, e.clientY - r.top);
        cropRect = {
            x: Math.min(cropStart.x, pt.x), y: Math.min(cropStart.y, pt.y),
            w: Math.abs(pt.x - cropStart.x), h: Math.abs(pt.y - cropStart.y),
        };
        drawCropOverlay(canvas, cropRect);
    });
    canvas.addEventListener("mouseup", () => { cropStart = null; });
}

// ── Delete (flag bad) ─────────────────────────────────────────

async function deleteFigure(figId, btnEl) {
    try {
        const res = await fetch(`${API}/api/figures/${figId}`, { method: "DELETE" });
        if (res.ok) {
            const card = btnEl.closest(".figure-card");
            card.style.transition = "opacity 0.3s, transform 0.3s";
            card.style.opacity = "0";
            card.style.transform = "scale(0.8)";
            setTimeout(() => { card.remove(); loadStats(); }, 300);
        }
    } catch (e) {
        console.error("Delete failed:", e);
    }
}

// ── Utils ─────────────────────────────────────────────────────

function escHtml(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
}
