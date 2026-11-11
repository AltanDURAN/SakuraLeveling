// Sakura Admin — sortable tables (DOM-only, pas de requête réseau).
// Activé via <table data-sortable> + <th data-sort-key="..."> dans le HTML.
// Le type de tri est inféré : numérique si tous les non-vides parsent en
// nombre, sinon comparaison de chaînes localisée FR.

(function () {
    function parseValue(text) {
        const cleaned = (text || "").trim().replace(/ |\s/g, "");
        if (cleaned === "" || cleaned === "—") return null;
        const num = parseFloat(cleaned.replace(",", "."));
        if (!isNaN(num) && /^[-+]?[\d.]+%?$/.test(cleaned.replace("%", ""))) {
            return num;
        }
        return text.trim();
    }

    function sortTable(table, key, dir) {
        const headers = Array.from(table.querySelectorAll("thead th[data-sort-key]"));
        const idx = headers.findIndex((h) => h.dataset.sortKey === key);
        if (idx < 0) return;
        const colIndex = Array.from(table.querySelectorAll("thead th")).indexOf(headers[idx]);
        const tbody = table.querySelector("tbody");
        const rows = Array.from(tbody.querySelectorAll("tr"));
        const sign = dir === "asc" ? 1 : -1;

        rows.sort((a, b) => {
            const av = parseValue(a.children[colIndex]?.innerText);
            const bv = parseValue(b.children[colIndex]?.innerText);
            if (av === null && bv === null) return 0;
            if (av === null) return 1;
            if (bv === null) return -1;
            if (typeof av === "number" && typeof bv === "number") {
                return (av - bv) * sign;
            }
            return String(av).localeCompare(String(bv), "fr", { numeric: true }) * sign;
        });

        rows.forEach((row) => tbody.appendChild(row));

        // Met à jour les indicateurs visuels
        table.querySelectorAll("thead th[data-sort-key]").forEach((th) => {
            const indicator = th.querySelector(".sort-indicator");
            if (!indicator) return;
            if (th.dataset.sortKey === key) {
                indicator.textContent = dir === "asc" ? "↑" : "↓";
                th.classList.add("th-sorted");
            } else {
                indicator.textContent = "⇅";
                th.classList.remove("th-sorted");
            }
        });
    }

    function initSortable(table) {
        const state = { key: null, dir: "asc" };
        table.querySelectorAll("thead th[data-sort-key]").forEach((th) => {
            // Injecte un indicateur si absent
            if (!th.querySelector(".sort-indicator")) {
                const span = document.createElement("span");
                span.className = "sort-indicator";
                span.textContent = "⇅";
                th.appendChild(document.createTextNode(" "));
                th.appendChild(span);
            }
            th.style.cursor = "pointer";
            th.addEventListener("click", () => {
                if (state.key === th.dataset.sortKey) {
                    state.dir = state.dir === "asc" ? "desc" : "asc";
                } else {
                    state.key = th.dataset.sortKey;
                    state.dir = "asc";
                }
                sortTable(table, state.key, state.dir);
            });
        });
    }

    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("table[data-sortable]").forEach(initSortable);
    });
})();

/* ---------------------------------------------------------------------------
 * imageField — composant Alpine PARTAGÉ par toutes les surfaces d'upload
 * d'image de l'admin (items, monstres, décors de zone/spot, événements).
 * Fournit : aperçu live du fichier déposé, génération via le module d'IA
 * (POST /admin/image-gen/<kind>/<code>) et téléchargement (lien natif).
 * Cf. templates/admin/_image_field.html
 * ------------------------------------------------------------------------- */
function imageField(cfg) {
    return {
        kind: cfg.kind,
        code: cfg.code || "",
        current: cfg.current || "",
        assetDir: cfg.assetDir,
        defaultPrompt: cfg.defaultPrompt || "",
        prompt: cfg.defaultPrompt || "",
        showPrompt: false,
        generating: false,
        error: "",
        get previewUrl() {
            if (this._objectUrl) return this._objectUrl;
            if (!this.current) return "";
            // cache-bust : après régénération, le nom de fichier est identique
            return "/assets/" + this.assetDir + "/" + this.current + "?v=" + (this._v || 0);
        },
        _objectUrl: "",
        _v: 0,
        onFile(event) {
            const file = event.target.files && event.target.files[0];
            if (!file) return;
            if (this._objectUrl) URL.revokeObjectURL(this._objectUrl);
            this._objectUrl = URL.createObjectURL(file);
        },
        async generate() {
            if (!this.code || this.generating) return;
            this.generating = true;
            this.error = "";
            try {
                const res = await fetch(
                    "/admin/image-gen/" + this.kind + "/" + encodeURIComponent(this.code),
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ prompt: this.prompt }),
                    },
                );
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    this.error = data.error || "Génération impossible.";
                } else {
                    // le fichier déposé manuellement (s'il y en avait un) n'est
                    // plus la vérité : on repasse sur l'asset fraîchement écrit
                    if (this._objectUrl) { URL.revokeObjectURL(this._objectUrl); this._objectUrl = ""; }
                    this.current = data.filename;
                    this._v = Date.now();
                }
            } catch (e) {
                this.error = "Erreur réseau pendant la génération.";
            } finally {
                this.generating = false;
            }
        },
    };
}

// Sakura Admin — visionneuse d'images (demande de l'auteur, 11/11/2026) :
// un clic sur une image l'affiche en grand. ← → passent aux autres images de
// la page, Échap (ou un clic à côté) ferme. Laissées tranquilles : les images
// d'un bouton ou d'un sélecteur, des éditeurs où l'on fait glisser (scènes,
// images en lot), les petites icônes, et tout ce qui porte `data-no-zoom`.
// Une image dans un lien (carte, fiche) garde le lien dans la visionneuse.
(function () {
    const MIN_SIDE = 28;
    let box = null, current = null, list = [];

    function draggable(el) {
        for (let node = el; node && node !== document.body; node = node.parentElement) {
            if (node.hasAttribute("draggable") && node.getAttribute("draggable") !== "false") return true;
            for (const attr of node.attributes) {
                if (/^(x-on:|@)(mousedown|pointerdown|touchstart|dragstart)/.test(attr.name)) return true;
            }
        }
        return false;
    }

    function zoomable(img) {
        if (!(img instanceof HTMLImageElement) || !img.currentSrc && !img.src) return false;
        if (img.closest("[data-no-zoom], button, label, .zoom-box, select")) return false;
        const r = img.getBoundingClientRect();
        if (r.width < MIN_SIDE && r.height < MIN_SIDE) return false;
        if (getComputedStyle(img).pointerEvents === "none") return false;
        return !draggable(img);
    }

    function build() {
        box = document.createElement("div");
        box.className = "zoom-box";
        box.setAttribute("role", "dialog");
        box.setAttribute("aria-modal", "true");
        box.innerHTML =
            '<button type="button" class="zoom-close" aria-label="Fermer">✕</button>' +
            '<button type="button" class="zoom-nav zoom-prev" aria-label="Image précédente">‹</button>' +
            '<button type="button" class="zoom-nav zoom-next" aria-label="Image suivante">›</button>' +
            '<figure class="zoom-figure"><div class="zoom-stage"><img alt=""></div>' +
            '<figcaption><span class="zoom-name"></span><span class="zoom-size"></span>' +
            '<span class="zoom-count"></span><a class="zoom-open" target="_blank" rel="noopener">Ouvrir l\'original ↗</a>' +
            '<a class="zoom-link">Ouvrir la fiche →</a></figcaption></figure>';
        document.body.appendChild(box);
        box.addEventListener("click", (e) => {
            if (e.target === box || e.target.classList.contains("zoom-stage")) close();
        });
        box.querySelector(".zoom-close").addEventListener("click", close);
        box.querySelector(".zoom-prev").addEventListener("click", () => step(-1));
        box.querySelector(".zoom-next").addEventListener("click", () => step(1));
        box.querySelector(".zoom-stage img").addEventListener("load", fit);
        window.addEventListener("resize", () => { if (box.classList.contains("is-open")) fit(); });
    }

    function fit() {
        const img = box.querySelector(".zoom-stage img");
        const nw = img.naturalWidth || 1, nh = img.naturalHeight || 1;
        // Agrandie jusqu'à remplir l'écran (×3 au plus pour une petite icône).
        const scale = Math.min(window.innerWidth * 0.9 / nw, window.innerHeight * 0.8 / nh, 3);
        img.style.width = Math.round(nw * scale) + "px";
        img.style.height = Math.round(nh * scale) + "px";
        box.querySelector(".zoom-size").textContent = nw + " × " + nh + " px";
    }

    function show(img) {
        if (!box) build();
        current = img;
        const src = img.currentSrc || img.src;
        const view = box.querySelector(".zoom-stage img");
        view.src = src;
        view.alt = img.alt || "";
        let name = img.alt || "";
        if (!name) {
            try { name = decodeURIComponent(new URL(src, location.href).pathname.split("/").pop()); } catch (e) { name = ""; }
        }
        box.querySelector(".zoom-name").textContent = name;
        box.querySelector(".zoom-open").href = src;
        const link = img.closest("a[href]");
        const go = box.querySelector(".zoom-link");
        go.hidden = !link;
        if (link) go.href = link.href;
        const i = list.indexOf(img);
        box.querySelector(".zoom-count").textContent = list.length > 1 ? (i + 1) + " / " + list.length : "";
        box.querySelectorAll(".zoom-nav").forEach((b) => { b.hidden = list.length < 2; });
        box.classList.add("is-open");
        document.documentElement.classList.add("zoom-lock");
        if (view.complete) fit();
    }

    function step(delta) {
        if (list.length < 2) return;
        const i = (list.indexOf(current) + delta + list.length) % list.length;
        show(list[i]);
    }

    function close() {
        if (!box) return;
        box.classList.remove("is-open");
        document.documentElement.classList.remove("zoom-lock");
        current = null;
    }

    // Phase de CAPTURE : passe avant les clics de la page (ouvrir une fiche,
    // suivre un lien), qui n'ont donc pas lieu quand on agrandit l'image.
    document.addEventListener("click", (e) => {
        const img = e.target;
        if (!(img instanceof HTMLImageElement) || !zoomable(img)) return;
        if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;   // Ctrl+clic : le lien s'ouvre
        e.preventDefault();
        e.stopPropagation();
        list = Array.from(document.querySelectorAll("img")).filter((el) => el.offsetParent !== null && zoomable(el));
        show(img);
    }, true);

    document.addEventListener("mouseover", (e) => {
        const img = e.target;
        if (img instanceof HTMLImageElement && !img.dataset.zoomChecked) {
            img.dataset.zoomChecked = "1";
            if (zoomable(img)) img.classList.add("zoom-in");
        }
    });

    document.addEventListener("keydown", (e) => {
        if (!box || !box.classList.contains("is-open")) return;
        if (e.key === "Escape") { close(); e.preventDefault(); }
        else if (e.key === "ArrowLeft") { step(-1); e.preventDefault(); }
        else if (e.key === "ArrowRight") { step(1); e.preventDefault(); }
    });
})();
