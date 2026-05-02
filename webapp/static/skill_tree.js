/* Interactivité de la page d'arbre :
 *   - Hover sur un nœud → tooltip avec détails
 *   - Glisser-déposer pour panner
 *   - Molette pour zoomer
 */

(function () {
    const container = document.getElementById('tree-container');
    const svg = container.querySelector('svg');
    const tooltip = document.getElementById('tooltip');
    const tooltipTitle = tooltip.querySelector('.tooltip-title');
    const tooltipState = tooltip.querySelector('.tooltip-state');
    const tooltipDescription = tooltip.querySelector('.tooltip-description');
    const tooltipLevel = tooltip.querySelector('.tooltip-level');

    if (!svg) return;

    /* ----- Tooltip ----- */

    const STATE_LABELS = {
        maxed: 'Niveau maximum',
        in_progress: 'En cours',
        unlockable: 'Débloquable',
        locked: 'Verrouillée',
    };

    const showTooltip = (node, x, y) => {
        const code = node.dataset.code;
        const skill = (window.SKILL_NODES || []).find(s => s.code === code);
        if (!skill) return;

        tooltipTitle.textContent = `${skill.icon} ${skill.name}`;
        tooltipState.textContent = STATE_LABELS[skill.state] || skill.state;
        tooltipState.className = 'tooltip-state ' + skill.state;
        tooltipDescription.textContent = skill.description || '';
        tooltipLevel.textContent =
            `Niveau : ${skill.current_level} / ${skill.max_level}`;

        const padding = 12;
        let left = x + padding;
        let top = y + padding;
        if (left + 360 > window.innerWidth) left = x - 360;
        if (top + 200 > window.innerHeight) top = y - 200;
        tooltip.style.left = left + 'px';
        tooltip.style.top = top + 'px';
        tooltip.hidden = false;
    };

    const hideTooltip = () => {
        tooltip.hidden = true;
    };

    svg.querySelectorAll('.skill-node').forEach(node => {
        node.addEventListener('mousemove', e => showTooltip(node, e.clientX, e.clientY));
        node.addEventListener('mouseleave', hideTooltip);
    });

    /* ----- Pan & zoom (manipulation de viewBox) ----- */

    const initialViewBox = svg.getAttribute('viewBox').split(/\s+/).map(Number);
    let viewBox = [...initialViewBox];

    const setViewBox = (vb) => {
        svg.setAttribute('viewBox', vb.join(' '));
    };

    let isPanning = false;
    let panStart = null;

    container.addEventListener('mousedown', e => {
        if (e.button !== 0) return;
        if (e.target.closest('.skill-node')) return; // ne pas panner sur un nœud
        isPanning = true;
        panStart = { x: e.clientX, y: e.clientY, vb: [...viewBox] };
    });

    window.addEventListener('mousemove', e => {
        if (!isPanning) return;
        const rect = container.getBoundingClientRect();
        const scaleX = viewBox[2] / rect.width;
        const scaleY = viewBox[3] / rect.height;
        viewBox[0] = panStart.vb[0] - (e.clientX - panStart.x) * scaleX;
        viewBox[1] = panStart.vb[1] - (e.clientY - panStart.y) * scaleY;
        setViewBox(viewBox);
    });

    window.addEventListener('mouseup', () => {
        isPanning = false;
        panStart = null;
    });

    container.addEventListener('wheel', e => {
        e.preventDefault();
        const factor = e.deltaY < 0 ? 0.9 : 1.1;
        const rect = container.getBoundingClientRect();
        const cursorX = (e.clientX - rect.left) / rect.width;
        const cursorY = (e.clientY - rect.top) / rect.height;

        const newW = viewBox[2] * factor;
        const newH = viewBox[3] * factor;
        viewBox[0] += (viewBox[2] - newW) * cursorX;
        viewBox[1] += (viewBox[3] - newH) * cursorY;
        viewBox[2] = newW;
        viewBox[3] = newH;
        setViewBox(viewBox);
    }, { passive: false });

    /* Reset au double-clic */
    container.addEventListener('dblclick', e => {
        if (e.target.closest('.skill-node')) return;
        viewBox = [...initialViewBox];
        setViewBox(viewBox);
    });
})();
