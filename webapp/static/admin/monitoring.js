/* Surveillance — survol des graphiques, tri des tableaux, recherche.
   Les libellés viennent de la base : insérés en textContent, jamais en HTML. */
(function () {
    "use strict";
    let tip = null;

    function tipEl() {
        if (!tip) {
            tip = document.createElement("div");
            tip.className = "viz-tip";
            tip.setAttribute("role", "tooltip");
            document.body.appendChild(tip);
        }
        return tip;
    }

    function place(x, y) {
        const t = tipEl();
        const pad = 14;
        const w = t.offsetWidth, h = t.offsetHeight;
        let left = x + pad, top = y + pad;
        if (left + w > window.innerWidth - 8) left = x - w - pad;
        if (top + h > window.innerHeight - 8) top = y - h - pad;
        t.style.left = Math.max(8, left) + "px";
        t.style.top = Math.max(8, top) + "px";
    }

    function showText(text, x, y) {
        const t = tipEl();
        t.textContent = text;
        t.classList.add("is-on");
        place(x, y);
    }

    function hide() {
        if (tip) tip.classList.remove("is-on");
    }

    // Barres, cases, segments : data-tip.
    document.addEventListener("pointermove", function (ev) {
        const target = ev.target.closest && ev.target.closest("[data-tip]");
        if (target && !target.closest(".viz-line")) {
            showText(target.getAttribute("data-tip"), ev.clientX, ev.clientY);
        } else if (!(ev.target.closest && ev.target.closest(".viz-line"))) {
            hide();
        }
    });
    document.addEventListener("focusin", function (ev) {
        const target = ev.target.closest && ev.target.closest("[data-tip]");
        if (target) {
            const r = target.getBoundingClientRect();
            showText(target.getAttribute("data-tip"), r.left + r.width / 2, r.bottom);
        }
    });
    document.addEventListener("focusout", hide);

    // Courbes : réticule calé sur le point le plus proche, toutes les séries.
    function fmt(v) {
        if (v === null || v === undefined) return "—";
        const a = Math.abs(v);
        let s;
        if (a >= 1e6) s = (v / 1e6).toFixed(1).replace(".", ",") + " M";
        else if (a >= 1e4) s = Math.round(v / 1e3) + " k";
        else if (a >= 100 || Number.isInteger(v)) s = Math.round(v).toLocaleString("fr-FR");
        else s = v.toFixed(1).replace(".", ",");
        return s;
    }

    document.querySelectorAll("svg.viz-line").forEach(function (svg) {
        let data;
        try { data = JSON.parse(svg.getAttribute("data-series")); } catch (e) { return; }
        const left = +svg.getAttribute("data-left"), plot = +svg.getAttribute("data-plot"), n = +svg.getAttribute("data-n");
        const cross = svg.querySelector(".viz-cross");
        const vb = svg.viewBox.baseVal;
        function move(ev) {
            const r = svg.getBoundingClientRect();
            const sx = (ev.clientX - r.left) * vb.width / r.width;
            const i = Math.max(0, Math.min(n - 1, Math.round((sx - left) / plot * (n - 1))));
            const cx = left + (n > 1 ? plot * i / (n - 1) : plot / 2);
            cross.setAttribute("x1", cx); cross.setAttribute("x2", cx);
            cross.setAttribute("visibility", "visible");
            const t = tipEl();
            t.textContent = "";
            const head = document.createElement("div");
            head.className = "tip-head";
            head.textContent = data.labels[i];
            t.appendChild(head);
            data.series.forEach(function (s) {
                const row = document.createElement("div");
                row.className = "tip-row";
                const key = document.createElement("span");
                key.className = "tip-key s" + s.slot;
                const val = document.createElement("b");
                val.textContent = fmt(s.values[i]);
                const name = document.createElement("span");
                name.textContent = s.name;
                row.append(key, val, name);
                t.appendChild(row);
            });
            t.classList.add("is-on");
            place(ev.clientX, ev.clientY);
        }
        svg.addEventListener("pointermove", move);
        svg.addEventListener("pointerleave", function () { cross.setAttribute("visibility", "hidden"); hide(); });
    });

    // Tableaux triables : <th data-sort="num|text">, valeur dans data-v sinon le texte.
    document.querySelectorAll("table.mtable").forEach(function (table) {
        table.querySelectorAll("th[data-sort]").forEach(function (th, idx) {
            th.addEventListener("click", function () {
                const col = Array.prototype.indexOf.call(th.parentNode.children, th);
                const asc = th.classList.contains("is-sorted") ? !th.classList.contains("is-asc") : th.dataset.sort === "text";
                table.querySelectorAll("th").forEach(function (o) { o.classList.remove("is-sorted", "is-asc"); });
                th.classList.add("is-sorted");
                if (asc) th.classList.add("is-asc");
                const body = table.tBodies[0];
                const rows = Array.from(body.rows);
                rows.sort(function (a, b) {
                    const ca = a.cells[col], cb = b.cells[col];
                    const va = ca.dataset.v !== undefined ? ca.dataset.v : ca.textContent.trim();
                    const vb2 = cb.dataset.v !== undefined ? cb.dataset.v : cb.textContent.trim();
                    let d;
                    if (th.dataset.sort === "num") d = (parseFloat(va) || 0) - (parseFloat(vb2) || 0);
                    else d = va.localeCompare(vb2, "fr");
                    return asc ? d : -d;
                });
                rows.forEach(function (r) { body.appendChild(r); });
            });
        });
    });

    // Recherche dans un tableau : <input data-filter-table="#id">.
    document.querySelectorAll("input[data-filter-table]").forEach(function (input) {
        const table = document.querySelector(input.dataset.filterTable);
        if (!table) return;
        input.addEventListener("input", function () {
            const q = input.value.trim().toLowerCase();
            Array.from(table.tBodies[0].rows).forEach(function (r) {
                r.hidden = q && !r.textContent.toLowerCase().includes(q);
            });
        });
    });

    // Téléphone : un graphique qui défile s'ouvre sur les jours les plus récents.
    document.querySelectorAll(".viz-wrap").forEach(function (w) {
        if (w.scrollWidth > w.clientWidth) w.scrollLeft = w.scrollWidth;
    });

    // Segments de joueurs (liste) : <button data-segment="...">.
    document.querySelectorAll("[data-segment-target]").forEach(function (bar) {
        const table = document.querySelector(bar.dataset.segmentTarget);
        bar.querySelectorAll("button[data-segment]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                bar.querySelectorAll("button").forEach(function (b) { b.classList.remove("is-on"); });
                btn.classList.add("is-on");
                const seg = btn.dataset.segment;
                Array.from(table.tBodies[0].rows).forEach(function (r) {
                    r.hidden = seg !== "all" && !(r.dataset.segments || "").split(" ").includes(seg);
                });
            });
        });
    });
})();
