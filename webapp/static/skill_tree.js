/* Interactivité de l'arbre — souris ET tactile (mobile).
 *   - Pan : 1 doigt / clic-glisser
 *   - Zoom : pincement 2 doigts / molette / boutons +/−
 *   - Détails : tap (mobile) ou survol (desktop) sur un nœud → tooltip
 *   - Recentrer : bouton ⟳ ou double-tap
 * Implémenté via Pointer Events pour unifier souris + tactile + multi-touch.
 */

(function () {
    const container = document.getElementById('tree-container');
    let svg = container && container.querySelector('svg');  // remplacé après un investissement
    const tooltip = document.getElementById('tooltip');
    if (!svg || !tooltip) return;

    const tooltipTitle = tooltip.querySelector('.tooltip-title');
    const tooltipState = tooltip.querySelector('.tooltip-state');
    const tooltipDescription = tooltip.querySelector('.tooltip-description');
    const tooltipLevel = tooltip.querySelector('.tooltip-level');
    const tooltipCost = tooltip.querySelector('.tooltip-cost');
    const tooltipPrereqs = tooltip.querySelector('.tooltip-prereqs');
    const tooltipClose = tooltip.querySelector('.tooltip-close');
    const tooltipAction = tooltip.querySelector('.tooltip-action');
    const toast = document.getElementById('toast');
    const PAGE = window.SKILL_PAGE || {};
    let pinned = false;        // fiche ouverte par un clic : reste à l'écran
    let currentCode = null;    // case affichée dans la fiche
    let investing = false;

    const isMobile = () => window.matchMedia('(max-width: 700px)').matches;
    // Feuille du bas dès qu'on est sur un appareil TACTILE (fiable partout :
    // tablettes, webview Discord, etc.) ou un petit écran. Ne dépend plus
    // uniquement de la largeur CSS (qui peut être trompeuse).
    const wantsSheet = () =>
        window.matchMedia('(pointer: coarse)').matches ||
        ('ontouchstart' in window) ||
        isMobile();
    const isFinePointer = () =>
        window.matchMedia('(hover: hover) and (pointer: fine)').matches;

    const STATE_LABELS = {
        maxed: 'Niveau maximum', in_progress: 'En cours',
        unlockable: 'Débloquable', locked: 'Verrouillée',
    };

    /* ----- Tooltip ----- */
    function fillTooltip(skill) {
        tooltipTitle.textContent = `${skill.icon} ${skill.name}`;
        tooltipState.textContent = STATE_LABELS[skill.state] || skill.state;
        tooltipState.className = 'tooltip-state ' + skill.state;
        const effects = (skill.effects_text || []).join(' · ');
        tooltipDescription.textContent = [skill.description, effects].filter(Boolean).join('\n');
        tooltipDescription.style.whiteSpace = 'pre-line';
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
            h.textContent = skill.unlock_rule === 'any' && skill.prereqs_detail.length > 1
                ? 'Prérequis (un seul suffit, au niveau max) :'
                : 'Prérequis (au niveau max) :';
            tooltipPrereqs.appendChild(h);
            skill.prereqs_detail.forEach(p => {
                const line = document.createElement('p');
                line.className = 'tooltip-prereq ' + (p.satisfied ? 'satisfied' : 'missing');
                line.textContent = `${p.satisfied ? '✅' : '❌'} ${p.icon} ${p.name} (${p.current_level}/${p.max_level ?? '?'})`;
                tooltipPrereqs.appendChild(line);
            });
        }
        if (skill.rule_lock) {
            const lock = document.createElement('p');
            lock.className = 'tooltip-prereq missing';
            lock.textContent = `🔒 ${skill.rule_lock}`;
            tooltipPrereqs.appendChild(lock);
        }
        fillAction(skill);
    }

    /* ----- Investir depuis le web ----- */
    function actionNote(text) {
        const p = document.createElement('p');
        p.className = 'tooltip-action-note';
        p.textContent = text;
        return p;
    }

    function fillAction(skill) {
        tooltipAction.innerHTML = '';
        // Survol simple (souris) : on indique seulement qu'un clic ouvre l'action.
        if (!pinned) {
            if (skill.state === 'unlockable' || skill.state === 'in_progress') {
                tooltipAction.appendChild(actionNote('🖱️ Clique sur la case pour l\'investir.'));
            }
            return;
        }
        if (skill.start || skill.state === 'maxed') return;

        if (!PAGE.logged_in) {
            tooltipAction.appendChild(actionNote(
                'Pour investir pour de vrai, connecte-toi avec ton compte Discord.'));
            const a = document.createElement('a');
            a.className = 'action-btn action-btn--discord';
            a.href = PAGE.login_url;
            a.textContent = '🔐 Se connecter avec Discord';
            tooltipAction.appendChild(a);
            return;
        }
        if (!PAGE.is_owner) {
            tooltipAction.appendChild(actionNote(
                'Ce n\'est pas ton arbre : tu ne peux investir que dans le tien.'));
            const a = document.createElement('a');
            a.className = 'action-btn';
            a.href = '/skill/' + PAGE.viewer_id;
            a.textContent = '🌳 Ouvrir mon arbre';
            tooltipAction.appendChild(a);
            return;
        }

        const cost = (skill.costs || [])[skill.current_level];
        const points = PAGE.available_points;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'action-btn action-btn--invest';
        btn.textContent = investing ? 'Investissement…'
            : `✨ Investir (${cost ?? '?'} pt${cost > 1 ? 's' : ''})`;
        let reason = '';
        if (skill.state === 'locked') reason = 'Débloque d\'abord les prérequis.';
        else if (cost != null && points < cost) reason = `Il te manque ${cost - points} point(s) (${points} disponible${points > 1 ? 's' : ''}).`;
        btn.disabled = investing || !!reason;
        btn.addEventListener('click', () => invest(skill.code));
        tooltipAction.appendChild(btn);
        if (reason) tooltipAction.appendChild(actionNote(reason));
    }

    function showToast(text, ok) {
        if (!toast) return;
        toast.textContent = text;
        toast.className = 'toast ' + (ok ? 'toast--ok' : 'toast--bad');
        toast.hidden = false;
        clearTimeout(showToast.timer);
        showToast.timer = setTimeout(() => { toast.hidden = true; }, 3200);
    }

    function swapSvg(markup) {
        const holder = document.createElement('div');
        holder.innerHTML = markup;
        const fresh = holder.querySelector('svg');
        if (!fresh) return;
        fresh.setAttribute('viewBox', viewBox.join(' '));  // garde le zoom en cours
        svg.replaceWith(fresh);
        svg = fresh;
    }

    async function invest(code) {
        if (investing) return;
        investing = true;
        refreshTooltip();
        try {
            const resp = await fetch(`/api/skill/${PAGE.discord_id}/invest`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'same-origin',
                body: JSON.stringify({ code }),
            });
            const data = await resp.json().catch(() => ({}));
            if (resp.status === 401) {
                PAGE.logged_in = false;
                showToast(data.message || 'Session expirée : reconnecte-toi.', false);
            } else {
                if (data.nodes) window.SKILL_NODES = data.nodes;
                if (data.svg) swapSvg(data.svg);
                if (typeof data.available_points === 'number') {
                    PAGE.available_points = data.available_points;
                    const a = document.getElementById('points-available');
                    const sp = document.getElementById('points-spent');
                    if (a) a.textContent = data.available_points;
                    if (sp && typeof data.spent_points === 'number') sp.textContent = data.spent_points;
                }
                showToast(data.message || (data.ok ? 'Investi !' : 'Impossible d\'investir.'), !!data.ok);
            }
        } catch (err) {
            showToast('Connexion perdue, réessaie.', false);
        } finally {
            investing = false;
            refreshTooltip();
        }
    }

    function refreshTooltip() {
        if (tooltip.hidden || !currentCode) return;
        const skill = (window.SKILL_NODES || []).find(s => s.code === currentCode);
        if (skill) fillTooltip(skill);
    }

    function showTooltip(node, clientX, clientY, pin = false) {
        const skill = (window.SKILL_NODES || []).find(s => s.code === node.dataset.code);
        if (!skill) return;
        if (pinned && !pin) return;  // une fiche épinglée ne bouge pas au survol
        pinned = pin;
        currentCode = skill.code;
        tooltip.classList.toggle('tooltip--pinned', pin);
        fillTooltip(skill);

        const sheet = wantsSheet();
        tooltip.classList.toggle('tooltip--sheet', sheet);
        tooltip.hidden = false;

        if (sheet) {
            // Feuille du bas : pleine largeur, toujours entièrement à l'écran
            // (position gérée par le CSS .tooltip--sheet). On neutralise l'inline.
            tooltip.style.left = '';
            tooltip.style.top = '';
        } else {
            // Bulle flottante près du curseur, CLAMPÉE intégralement dans la fenêtre.
            const pad = 14;
            const w = tooltip.offsetWidth || 340;
            const h = tooltip.offsetHeight || 280;
            let left = (clientX ?? window.innerWidth / 2) + pad;
            let top = (clientY ?? window.innerHeight / 2) + pad;
            left = Math.min(left, window.innerWidth - w - pad);
            top = Math.min(top, window.innerHeight - h - pad);
            tooltip.style.left = Math.max(pad, left) + 'px';
            tooltip.style.top = Math.max(pad, top) + 'px';
        }
    }
    const hideTooltip = () => {
        tooltip.hidden = true;
        pinned = false;
        currentCode = null;
        tooltip.classList.remove('tooltip--pinned');
    };
    if (tooltipClose) tooltipClose.addEventListener('click', hideTooltip);

    // Survol : seulement sur souris/desktop (pointeur fin). Sur tactile, on
    // passe par le tap (feuille du bas).
    // Délégation sur le conteneur : le SVG est remplacé après chaque
    // investissement, des écouteurs posés sur ses cases seraient perdus.
    container.addEventListener('mousemove', e => {
        if (!isFinePointer() || activePointers.size !== 0 || pinned) return;
        const node = e.target.closest && e.target.closest('.skill-node');
        if (node) showTooltip(node, e.clientX, e.clientY);
        else if (!tooltip.hidden) hideTooltip();
    });
    container.addEventListener('mouseleave', () => {
        if (isFinePointer() && !pinned) hideTooltip();
    });

    /* ----- ViewBox (pan + zoom) ----- */
    // Sur un petit écran, on ouvre sur l'arbre principal plutôt que sur tout
    // l'arbre (qui tiendrait dans un timbre-poste) ; le reste est à portée de doigt.
    const fullViewBox = svg.getAttribute('viewBox').split(/\s+/).map(Number);
    const mainView = (svg.dataset.mainView || '').split(/\s+/).map(Number);
    const initialViewBox = (window.innerWidth < 700 && mainView.length === 4 && mainView.every(Number.isFinite))
        ? mainView : fullViewBox;
    svg.setAttribute('viewBox', initialViewBox.join(' '));
    let viewBox = [...initialViewBox];
    const MIN_W = 250;
    const MAX_W = Math.max(initialViewBox[2], fullViewBox[2]) * 4;

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
    let dragged = false;               // le dernier geste était un glissement
    let downAt = null;

    function pointersArray() {
        return [...activePointers.values()];
    }

    container.addEventListener('pointerdown', e => {
        container.setPointerCapture?.(e.pointerId);
        activePointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (activePointers.size === 1) { dragged = false; downAt = { x: e.clientX, y: e.clientY }; }
        else dragged = true;

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
        if (downAt && (Math.abs(e.clientX - downAt.x) > TAP_TOLERANCE ||
                       Math.abs(e.clientY - downAt.y) > TAP_TOLERANCE)) dragged = true;

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
            // Un clic / tap épingle la fiche : c'est là qu'on investit.
            showTooltip(tapCandidate.node, tapCandidate.x, tapCandidate.y, true);
        } else if (!dragged && activePointers.size === 1) {
            // Clic / tap dans le vide : referme la fiche. Géré ici et pas sur
            // « click » : la capture du pointeur attribue le click au conteneur,
            // même quand on a touché une case.
            hideTooltip();
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

    document.addEventListener('keydown', e => { if (e.key === 'Escape') hideTooltip(); });

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
