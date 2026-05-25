/* Interactivité de l'arbre — souris ET tactile (mobile).
 *   - Pan : 1 doigt / clic-glisser
 *   - Zoom : pincement 2 doigts / molette / boutons +/−
 *   - Détails : tap (mobile) ou survol (desktop) sur un nœud → tooltip
 *   - Recentrer : bouton ⟳ ou double-tap
 * Implémenté via Pointer Events pour unifier souris + tactile + multi-touch.
 */

(function () {
    const container = document.getElementById('tree-container');
    const svg = container && container.querySelector('svg');
    const tooltip = document.getElementById('tooltip');
    if (!svg || !tooltip) return;

    const tooltipTitle = tooltip.querySelector('.tooltip-title');
    const tooltipState = tooltip.querySelector('.tooltip-state');
    const tooltipDescription = tooltip.querySelector('.tooltip-description');
    const tooltipLevel = tooltip.querySelector('.tooltip-level');
    const tooltipCost = tooltip.querySelector('.tooltip-cost');
    const tooltipPrereqs = tooltip.querySelector('.tooltip-prereqs');
    const tooltipClose = tooltip.querySelector('.tooltip-close');

    const isMobile = () => window.matchMedia('(max-width: 700px)').matches;

    const STATE_LABELS = {
        maxed: 'Niveau maximum', in_progress: 'En cours',
        unlockable: 'Débloquable', locked: 'Verrouillée',
    };

    /* ----- Tooltip ----- */
    function fillTooltip(skill) {
        tooltipTitle.textContent = `${skill.icon} ${skill.name}`;
        tooltipState.textContent = STATE_LABELS[skill.state] || skill.state;
        tooltipState.className = 'tooltip-state ' + skill.state;
        tooltipDescription.textContent = skill.description || '';
        tooltipLevel.textContent = `Niveau : ${skill.current_level} / ${skill.max_level}`;

        if (skill.state === 'maxed') {
            tooltipCost.textContent = '✅ Niveau maximum atteint';
            tooltipCost.className = 'tooltip-cost maxed';
        } else if (skill.costs && skill.costs.length > skill.current_level) {
            tooltipCost.textContent = `💎 Prochain niveau : ${skill.costs[skill.current_level]} pt(s)`;
            tooltipCost.className = 'tooltip-cost';
        } else {
            tooltipCost.textContent = '';
        }

        tooltipPrereqs.innerHTML = '';
        if (skill.prereqs_detail && skill.prereqs_detail.length > 0) {
            const h = document.createElement('p');
            h.className = 'tooltip-prereqs-heading';
            h.textContent = 'Prérequis :';
            tooltipPrereqs.appendChild(h);
            skill.prereqs_detail.forEach(p => {
                const line = document.createElement('p');
                line.className = 'tooltip-prereq ' + (p.satisfied ? 'satisfied' : 'missing');
                line.textContent = `${p.satisfied ? '✅' : '❌'} ${p.icon} ${p.name} (niv. ${p.current_level})`;
                tooltipPrereqs.appendChild(line);
            });
        }
    }

    function showTooltip(node, clientX, clientY) {
        const skill = (window.SKILL_NODES || []).find(s => s.code === node.dataset.code);
        if (!skill) return;
        fillTooltip(skill);
        tooltip.hidden = false;

        if (isMobile()) {
            // Bottom sheet (positionné par le CSS) — on neutralise left/top.
            tooltip.style.left = '';
            tooltip.style.top = '';
        } else {
            // Près du curseur / nœud, clampé dans la fenêtre.
            const pad = 14;
            let left = (clientX ?? 0) + pad;
            let top = (clientY ?? 0) + pad;
            const w = tooltip.offsetWidth || 340;
            const h = tooltip.offsetHeight || 280;
            if (left + w > window.innerWidth) left = window.innerWidth - w - pad;
            if (top + h > window.innerHeight) top = window.innerHeight - h - pad;
            tooltip.style.left = Math.max(pad, left) + 'px';
            tooltip.style.top = Math.max(pad, top) + 'px';
        }
    }
    const hideTooltip = () => { tooltip.hidden = true; };
    if (tooltipClose) tooltipClose.addEventListener('click', hideTooltip);

    // Survol desktop (en plus du tap)
    svg.querySelectorAll('.skill-node').forEach(node => {
        node.addEventListener('mousemove', e => {
            if (!isMobile() && activePointers.size === 0) showTooltip(node, e.clientX, e.clientY);
        });
        node.addEventListener('mouseleave', () => {
            if (!isMobile()) hideTooltip();
        });
    });

    /* ----- ViewBox (pan + zoom) ----- */
    const initialViewBox = svg.getAttribute('viewBox').split(/\s+/).map(Number);
    let viewBox = [...initialViewBox];
    const MIN_W = 250;
    const MAX_W = initialViewBox[2] * 4;

    const setViewBox = (vb) => svg.setAttribute('viewBox', vb.join(' '));

    function clientToView(clientX, clientY) {
        const rect = container.getBoundingClientRect();
        return {
            x: viewBox[0] + ((clientX - rect.left) / rect.width) * viewBox[2],
            y: viewBox[1] + ((clientY - rect.top) / rect.height) * viewBox[3],
        };
    }

    function zoomAt(factor, clientX, clientY) {
        let newW = viewBox[2] * factor;
        let newH = viewBox[3] * factor;
        // clamp sur la largeur
        if (newW < MIN_W) { factor = MIN_W / viewBox[2]; newW = MIN_W; newH = viewBox[3] * factor; }
        if (newW > MAX_W) { factor = MAX_W / viewBox[2]; newW = MAX_W; newH = viewBox[3] * factor; }
        const before = clientToView(clientX, clientY);
        viewBox[2] = newW;
        viewBox[3] = newH;
        const after = clientToView(clientX, clientY);
        viewBox[0] += before.x - after.x;
        viewBox[1] += before.y - after.y;
        setViewBox(viewBox);
    }

    function panByClient(dx, dy) {
        const rect = container.getBoundingClientRect();
        viewBox[0] -= dx * (viewBox[2] / rect.width);
        viewBox[1] -= dy * (viewBox[3] / rect.height);
        setViewBox(viewBox);
    }

    function reset() {
        viewBox = [...initialViewBox];
        setViewBox(viewBox);
    }

    /* ----- Pointer Events (souris + tactile + pinch) ----- */
    const activePointers = new Map();  // id -> {x, y}
    let panLast = null;                // {x, y} pour le pan 1-pointeur
    let pinchStart = null;             // {dist, w, h, cx, cy}
    let tapCandidate = null;           // {node, x, y} pour distinguer tap/drag
    const TAP_TOLERANCE = 10;

    function pointersArray() {
        return [...activePointers.values()];
    }

    container.addEventListener('pointerdown', e => {
        container.setPointerCapture?.(e.pointerId);
        activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

        const node = e.target.closest && e.target.closest('.skill-node');
        if (node && activePointers.size === 1) {
            tapCandidate = { node, x: e.clientX, y: e.clientY };
        }
        if (activePointers.size === 1) {
            panLast = { x: e.clientX, y: e.clientY };
        } else if (activePointers.size === 2) {
            const [a, b] = pointersArray();
            pinchStart = {
                dist: Math.hypot(a.x - b.x, a.y - b.y),
                cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2,
            };
            panLast = null;          // on bascule du pan vers le pinch
            tapCandidate = null;
        }
    });

    container.addEventListener('pointermove', e => {
        if (!activePointers.has(e.pointerId)) return;
        activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });

        if (activePointers.size >= 2 && pinchStart) {
            const [a, b] = pointersArray();
            const dist = Math.hypot(a.x - b.x, a.y - b.y);
            if (dist > 0 && pinchStart.dist > 0) {
                const cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
                zoomAt(pinchStart.dist / dist, cx, cy);
                pinchStart.dist = dist;  // incrémental
            }
            tapCandidate = null;
            return;
        }

        if (panLast && activePointers.size === 1) {
            const dx = e.clientX - panLast.x;
            const dy = e.clientY - panLast.y;
            if (tapCandidate &&
                (Math.abs(e.clientX - tapCandidate.x) > TAP_TOLERANCE ||
                 Math.abs(e.clientY - tapCandidate.y) > TAP_TOLERANCE)) {
                tapCandidate = null;  // c'est un glissement, pas un tap
            }
            panByClient(dx, dy);
            panLast = { x: e.clientX, y: e.clientY };
        }
    });

    function endPointer(e) {
        // tap sur un nœud → tooltip ; tap dans le vide → masquer
        if (tapCandidate) {
            showTooltip(tapCandidate.node, tapCandidate.x, tapCandidate.y);
        } else if (activePointers.size === 1 && panLast &&
                   Math.abs(e.clientX - panLast.x) < TAP_TOLERANCE) {
            // (cas géré par tapCandidate ; rien)
        }
        activePointers.delete(e.pointerId);
        if (activePointers.size < 2) pinchStart = null;
        if (activePointers.size === 0) { panLast = null; }
        else {
            const p = pointersArray()[0];
            panLast = { x: p.x, y: p.y };
        }
        tapCandidate = null;
    }
    container.addEventListener('pointerup', endPointer);
    container.addEventListener('pointercancel', e => {
        activePointers.delete(e.pointerId);
        pinchStart = null; panLast = null; tapCandidate = null;
    });

    // Tap dans le vide masque le tooltip (mobile)
    container.addEventListener('click', e => {
        if (isMobile() && !(e.target.closest && e.target.closest('.skill-node'))) {
            hideTooltip();
        }
    });

    /* ----- Molette (desktop) ----- */
    container.addEventListener('wheel', e => {
        e.preventDefault();
        zoomAt(e.deltaY < 0 ? 0.9 : 1.1, e.clientX, e.clientY);
    }, { passive: false });

    /* ----- Double-tap / double-clic : recentrer ----- */
    container.addEventListener('dblclick', e => {
        if (e.target.closest && e.target.closest('.skill-node')) return;
        reset();
    });

    /* ----- Boutons de contrôle ----- */
    function centerXY() {
        const r = container.getBoundingClientRect();
        return [r.left + r.width / 2, r.top + r.height / 2];
    }
    document.getElementById('zoom-in')?.addEventListener('click', () => {
        const [cx, cy] = centerXY(); zoomAt(0.8, cx, cy);
    });
    document.getElementById('zoom-out')?.addEventListener('click', () => {
        const [cx, cy] = centerXY(); zoomAt(1.25, cx, cy);
    });
    document.getElementById('zoom-reset')?.addEventListener('click', reset);
})();
