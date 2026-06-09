/**

 * Mega pipeline map — grey data → green pipelines → purple ML → legendary orange Droid.

 */

import { LAYER_COLORS, MEGA_LAYOUT, PIPELINE_EDGES, FEEDBACK_EDGES, nodeById } from './rh-arch-data.js';



const COL_W = 212;

const ROW_H = 54;

const PAD_X = 28;

const PAD_Y = 44;

const FEEDBACK_H = 64;

const NODE_W = 172;

const NODE_H = 42;



const LAYER_STROKE = {

  data: LAYER_COLORS.data.stroke,

  pipeline: LAYER_COLORS.pipeline.stroke,

  ml: LAYER_COLORS.ml.stroke,

  droid: LAYER_COLORS.droid.stroke,

  loop: LAYER_COLORS.loop.stroke,

};



function nodePos(colIdx, rowIdx) {

  return {

    x: PAD_X + colIdx * COL_W + (COL_W - NODE_W) / 2,

    y: PAD_Y + rowIdx * ROW_H,

    cx: PAD_X + colIdx * COL_W + COL_W / 2,

    cy: PAD_Y + rowIdx * ROW_H + NODE_H / 2,

  };

}



function buildPositions() {

  const pos = {};

  MEGA_LAYOUT.columns.forEach((col, colIdx) => {

    col.nodes.forEach((id, rowIdx) => {

      pos[id] = { ...nodePos(colIdx, rowIdx), colIdx, rowIdx, layer: col.layer };

    });

  });

  return pos;

}



function edgeStroke(fromId, toId, positions, feedback = false) {

  if (feedback) return LAYER_COLORS.loop.stroke;

  const b = positions[toId];

  if (!b) return 'rgba(148, 163, 184, 0.35)';

  return LAYER_STROKE[b.layer] || LAYER_STROKE.data;

}



function layerGradientDef(svg, width) {

  const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');



  const story = document.createElementNS('http://www.w3.org/2000/svg', 'linearGradient');

  story.setAttribute('id', 'td-pipe-grad');

  story.setAttribute('x1', '0%');

  story.setAttribute('y1', '0%');

  story.setAttribute('x2', '100%');

  story.setAttribute('y2', '0%');

  [

    ['0%', LAYER_COLORS.data.stroke],

    ['32%', LAYER_COLORS.pipeline.stroke],

    ['66%', LAYER_COLORS.ml.stroke],

    ['100%', LAYER_COLORS.droid.stroke],

  ].forEach(([off, col]) => {

    const stop = document.createElementNS('http://www.w3.org/2000/svg', 'stop');

    stop.setAttribute('offset', off);

    stop.setAttribute('stop-color', col);

    story.appendChild(stop);

  });

  defs.appendChild(story);



  const glow = document.createElementNS('http://www.w3.org/2000/svg', 'filter');

  glow.setAttribute('id', 'td-legendary-glow');

  glow.setAttribute('x', '-40%');

  glow.setAttribute('y', '-40%');

  glow.setAttribute('width', '180%');

  glow.setAttribute('height', '180%');

  glow.innerHTML = `

    <feGaussianBlur stdDeviation="4" result="b"/>

    <feColorMatrix in="b" type="matrix" values="1 0 0 0 0  0 0.5 0 0 0  0 0 0 0 0  0 0 0 0.9 0" result="o"/>

    <feMerge><feMergeNode in="o"/><feMergeNode in="SourceGraphic"/></feMerge>`;

  defs.appendChild(glow);



  const mlGlow = document.createElementNS('http://www.w3.org/2000/svg', 'filter');

  mlGlow.setAttribute('id', 'td-purple-glow');

  mlGlow.innerHTML = '<feGaussianBlur stdDeviation="2.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>';

  defs.appendChild(mlGlow);



  const flowGrad = document.createElementNS('http://www.w3.org/2000/svg', 'linearGradient');

  flowGrad.setAttribute('id', 'td-flow-active');

  flowGrad.setAttribute('gradientUnits', 'userSpaceOnUse');

  flowGrad.setAttribute('x1', '0');

  flowGrad.setAttribute('y1', '0');

  flowGrad.setAttribute('x2', String(width));

  flowGrad.setAttribute('y2', '0');

  [

    ['0%', '#9ca3af'],

    ['30%', '#22c55e'],

    ['65%', '#c084fc'],

    ['100%', '#ff9500'],

  ].forEach(([off, col]) => {

    const stop = document.createElementNS('http://www.w3.org/2000/svg', 'stop');

    stop.setAttribute('offset', off);

    stop.setAttribute('stop-color', col);

    flowGrad.appendChild(stop);

  });

  defs.appendChild(flowGrad);



  svg.appendChild(defs);

}



function edgePath(from, to, positions, feedback = false) {

  const a = positions[from];

  const b = positions[to];

  if (!a || !b) return '';

  if (feedback && b.colIdx < a.colIdx) {

    const yArc = PAD_Y + ROW_H * Math.max(a.rowIdx, b.rowIdx) + NODE_H + FEEDBACK_H - 14;

    return `M ${a.cx} ${a.y + NODE_H} C ${a.cx} ${yArc}, ${b.cx} ${yArc}, ${b.cx} ${b.y + NODE_H}`;

  }

  const x1 = a.x + NODE_W;

  const y1 = a.cy;

  const x2 = b.x;

  const y2 = b.cy;

  const mx = (x1 + x2) / 2;

  return `M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`;

}



function appendEdges(svg, positions, edgeList, { feedback = false, edgeStore } = {}) {

  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');

  g.setAttribute('class', feedback ? 'td-mega-edges td-mega-edges--feedback' : 'td-mega-edges');

  edgeList.forEach(([from, to]) => {

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');

    path.setAttribute('d', edgePath(from, to, positions, feedback));

    path.setAttribute('fill', 'none');

    path.setAttribute('stroke', edgeStroke(from, to, positions, feedback));

    path.setAttribute('stroke-width', feedback ? '1.3' : '1.6');

    path.setAttribute('stroke-linecap', 'round');

    if (feedback) {

      path.setAttribute('stroke-dasharray', '7 5');

      path.setAttribute('opacity', '0.7');

    } else {

      path.setAttribute('opacity', '0.42');

    }

    path.dataset.edgeFrom = from;

    path.dataset.edgeTo = to;

    path.dataset.edgeFeedback = feedback ? '1' : '0';

    g.appendChild(path);

    edgeStore.push({ el: path, from, to, feedback });

  });

  svg.appendChild(g);

}



function columnZones(svg, positions, height) {

  const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');

  g.setAttribute('class', 'td-mega-zones');

  MEGA_LAYOUT.columns.forEach((col, i) => {

    const lc = LAYER_COLORS[col.layer];

    const x = PAD_X + i * COL_W + 6;

    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');

    rect.setAttribute('x', x);

    rect.setAttribute('y', PAD_Y - 12);

    rect.setAttribute('width', COL_W - 12);

    rect.setAttribute('height', height - PAD_Y - FEEDBACK_H - 8);

    rect.setAttribute('rx', '14');

    rect.setAttribute('fill', lc.fill);

    rect.setAttribute('opacity', col.layer === 'droid' ? '0.22' : '0.14');

    rect.setAttribute('stroke', lc.stroke);

    rect.setAttribute('stroke-width', '0.6');

    rect.setAttribute('stroke-opacity', '0.35');

    g.appendChild(rect);

  });

  svg.insertBefore(g, svg.firstChild?.nextSibling || null);

}



export function renderMegaChart(wrap, { onSelect } = {}) {

  const positions = buildPositions();

  const maxRows = Math.max(...MEGA_LAYOUT.columns.map((c) => c.nodes.length));

  const width = PAD_X * 2 + COL_W * MEGA_LAYOUT.columns.length;

  const height = PAD_Y * 2 + ROW_H * maxRows + FEEDBACK_H + 28;

  const edgeStore = [];



  wrap.innerHTML = '';

  const scroll = document.createElement('div');

  scroll.className = 'td-mega-scroll';

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');

  svg.setAttribute('class', 'td-mega-svg');

  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);

  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');

  layerGradientDef(svg, width);



  const band = document.createElementNS('http://www.w3.org/2000/svg', 'rect');

  band.setAttribute('class', 'td-mega-story-band');

  band.setAttribute('x', PAD_X);

  band.setAttribute('y', PAD_Y - 8);

  band.setAttribute('width', width - PAD_X * 2);

  band.setAttribute('height', height - PAD_Y - FEEDBACK_H - 16);

  band.setAttribute('rx', '16');

  band.setAttribute('fill', 'url(#td-pipe-grad)');

  band.setAttribute('opacity', '0.09');

  svg.appendChild(band);



  columnZones(svg, positions, height);



  MEGA_LAYOUT.columns.forEach((col, i) => {

    const lc = LAYER_COLORS[col.layer];

    const tx = document.createElementNS('http://www.w3.org/2000/svg', 'text');

    tx.setAttribute('x', PAD_X + i * COL_W + COL_W / 2);

    tx.setAttribute('y', 24);

    tx.setAttribute('text-anchor', 'middle');

    tx.setAttribute('class', 'td-mega-col-label');

    tx.setAttribute('fill', lc.stroke);

    tx.textContent = lc.label;

    svg.appendChild(tx);

  });



  appendEdges(svg, positions, PIPELINE_EDGES, { edgeStore });

  appendEdges(svg, positions, FEEDBACK_EDGES, { feedback: true, edgeStore });



  const feedbackLabel = document.createElementNS('http://www.w3.org/2000/svg', 'text');

  feedbackLabel.setAttribute('x', width / 2);

  feedbackLabel.setAttribute('y', height - 10);

  feedbackLabel.setAttribute('text-anchor', 'middle');

  feedbackLabel.setAttribute('fill', LAYER_COLORS.loop.stroke);

  feedbackLabel.setAttribute('font-size', '9');

  feedbackLabel.setAttribute('opacity', '0.85');

  feedbackLabel.textContent = 'dashed arcs = recursive learning loops';

  svg.appendChild(feedbackLabel);



  const nodesG = document.createElementNS('http://www.w3.org/2000/svg', 'g');

  const highlightEdges = (nodeId) => {

    edgeStore.forEach(({ el, from, to, feedback }) => {

      const hit = from === nodeId || to === nodeId;

      el.setAttribute('stroke-width', hit ? (feedback ? '2.2' : '3') : (feedback ? '1.3' : '1.6'));

      el.setAttribute('opacity', hit ? '1' : (feedback ? '0.3' : '0.18'));

      if (hit && !feedback) el.setAttribute('stroke', 'url(#td-flow-active)');

      else el.setAttribute('stroke', edgeStroke(from, to, positions, feedback));

    });

  };



  Object.entries(positions).forEach(([id, p]) => {

    const node = nodeById(id);

    if (!node) return;

    const lc = LAYER_COLORS[node.layer] || LAYER_COLORS.data;

    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');

    g.setAttribute('class', `td-mega-node td-mega-node--${node.layer}`);

    g.setAttribute('data-node-id', id);

    g.setAttribute('cursor', 'pointer');

    g.setAttribute('tabindex', '0');

    g.setAttribute('role', 'button');



    const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');

    rect.setAttribute('x', p.x);

    rect.setAttribute('y', p.y);

    rect.setAttribute('width', NODE_W);

    rect.setAttribute('height', NODE_H);

    rect.setAttribute('rx', '9');

    rect.setAttribute('fill', lc.fill);

    rect.setAttribute('stroke', lc.stroke);

    rect.setAttribute('stroke-width', node.layer === 'droid' ? '2.2' : node.layer === 'ml' ? '1.8' : '1.3');

    if (node.layer === 'droid') rect.setAttribute('filter', 'url(#td-legendary-glow)');

    if (node.layer === 'ml') rect.setAttribute('filter', 'url(#td-purple-glow)');



    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');

    label.setAttribute('x', p.x + NODE_W / 2);

    label.setAttribute('y', p.y + NODE_H / 2 + 4);

    label.setAttribute('text-anchor', 'middle');

    label.setAttribute('fill', lc.text);

    label.setAttribute('class', 'td-mega-node-label');

    label.textContent = node.short || node.label;



    g.appendChild(rect);

    g.appendChild(label);



    const activate = () => {

      wrap.querySelectorAll('.td-mega-node--active').forEach((el) => el.classList.remove('td-mega-node--active'));

      g.classList.add('td-mega-node--active');

      highlightEdges(id);

      onSelect?.(node);

    };

    g.addEventListener('mouseenter', activate);

    g.addEventListener('focus', activate);

    g.addEventListener('click', activate);

    nodesG.appendChild(g);

  });

  svg.appendChild(nodesG);



  scroll.appendChild(svg);

  wrap.appendChild(scroll);

  return { positions, svg };

}



export function tooltipHtml(node) {

  if (!node) return '<p class="rh-muted">Hover or tap any node in the mega map.</p>';

  const lc = LAYER_COLORS[node.layer];

  return `

    <div class="td-tip__head" style="border-color:${lc.stroke}">

      <span class="td-tip__layer" style="background:${lc.fill};color:${lc.text};border:1px solid ${lc.stroke}">${lc.label}</span>

      <h3 class="td-tip__title">${node.label}</h3>

    </div>

    <dl class="td-tip__dl">

      <dt>Update cadence</dt><dd>${node.cadence}</dd>

      <dt>Data sources</dt><dd><ul>${node.sources.map((s) => `<li>${s}</li>`).join('')}</ul></dd>

      <dt>Downstream use</dt><dd><ul>${node.downstream.map((s) => `<li>${s}</li>`).join('')}</ul></dd>

      <dt>Edge provided</dt><dd>${node.edge}</dd>

      ${node.theory ? `<dt>Theory</dt><dd>${node.theory}</dd>` : ''}

      ${node.equation ? `<dt>Equation</dt><dd><pre class="td-tip__eq">${node.equation}</pre></dd>` : ''}

      ${node.script ? `<dt>Script</dt><dd><code>${node.script}</code></dd>` : ''}

    </dl>`;

}


