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
