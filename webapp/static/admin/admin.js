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
