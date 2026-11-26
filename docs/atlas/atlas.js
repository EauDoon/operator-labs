'use strict';

// The static directory supplies every node, import and source link.
const get = id => document.getElementById(id);
const nodes = [...document.querySelectorAll('.directory li')].map(item => ({
  id: item.id,
  label: item.querySelector('strong').textContent,
  description: item.querySelector('p').textContent,
  path: item.querySelector('.source').getAttribute('href'),
  pkg: item.dataset.package,
  position: item.dataset.point.split(',').map(Number),
  imports: [...item.querySelectorAll('.imports a')].map(a => a.hash.slice(1))
}));
const buttons = new Map();
let angle = 0, selected = nodes[0].id;
const field = get('field');

function visibleNodes() {
  return nodes.filter(node => !get('group').value || node.pkg === get('group').value);
}

function project(node, lane) {
  const [x, y, z] = node.position;
  const localX = x + (node.pkg === 'corridor-lab' ? 1.3 : -1.3);
  const u = localX * Math.cos(angle) + z * Math.sin(angle);
  const depth = z * Math.cos(angle) - localX * Math.sin(angle);
  const perspective = 1 / (1.6 - depth * .23);
  return {
    x: lane.x + lane.width * (.5 + u * perspective * .78),
    y: lane.y + lane.height * (.5 - y * perspective * .88),
    depth
  };
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

// Project each module into its package. Preserve the projected location where
// possible; labels near a sightline collision need space for both touch targets.
function placeNodes(visible) {
  const points = new Map();
  const origin = field.getBoundingClientRect();
  for (const panel of field.querySelectorAll('.lane')) {
    const members = visible.filter(node => node.pkg === panel.dataset.package);
    panel.hidden = members.length === 0;
  }
  for (const panel of field.querySelectorAll('.lane:not([hidden])')) {
    const bounds = panel.getBoundingClientRect();
    const lane = {x: bounds.left-origin.left, y: bounds.top-origin.top + 32,
      width: bounds.width, height: bounds.height - 32};
    const placed = [];
    for (const node of visible.filter(node => node.pkg === panel.dataset.package)) {
      const button = buttons.get(node.id);
      const w = button.offsetWidth, h = button.offsetHeight;
      const anchor = project(node, lane);
      const minX = lane.x + w/2 + 9, maxX = lane.x + lane.width - w/2 - 9;
      const minY = lane.y + h/2 + 8, maxY = lane.y + lane.height - h/2 - 8;
      const x = clamp(anchor.x, minX, maxX), y = clamp(anchor.y, minY, maxY);
      // Boundaries of the existing labels are the closest legal alternatives.
      const xs = [x, minX, maxX], ys = [y, minY, maxY];
      for (const other of placed) {
        const dx = (w + other.w)/2 + 13, dy = (h + other.h)/2 + 13;
        xs.push(other.x - dx, other.x + dx);
        ys.push(other.y - dy, other.y + dy);
      }
      let best = {x, y}, score = Infinity;
      for (const cy of ys) for (const cx of xs) {
        if (cx < minX || cx > maxX || cy < minY || cy > maxY) continue;
        let cost = (cx - x)**2 + (cy - y)**2;
        for (const other of placed) {
          const ox = (w + other.w)/2 + 12 - Math.abs(cx - other.x);
          const oy = (h + other.h)/2 + 12 - Math.abs(cy - other.y);
          if (ox > 0 && oy > 0) cost += 1e6 + ox * oy * 100;
        }
        if (cost < score) { best = {x: cx, y: cy}; score = cost; }
      }
      const point = {...best, depth: anchor.depth, w, h};
      points.set(node.id, point);
      placed.push(point);
    }
  }
  return points;
}

function edgePoint(from, to, padding) {
  const dx = to.x - from.x, dy = to.y - from.y;
  const fraction = Math.min(from.w / (2 * Math.abs(dx)), from.h / (2 * Math.abs(dy)));
  const gap = padding / Math.hypot(dx, dy);
  return {x: from.x + dx * (fraction + gap), y: from.y + dy * (fraction + gap)};
}

function renderMap() {
  const visible = visibleNodes();
  for (const node of nodes) buttons.get(node.id).hidden = !visible.includes(node);
  const points = placeNodes(visible);
  const lines = [];
  for (const node of visible) {
    const button = buttons.get(node.id);
    const point = points.get(node.id);
    button.style.left = point.x + 'px';
    button.style.top = point.y + 'px';
    button.style.zIndex = String(Math.round(10 + point.depth * 5));
    button.setAttribute('aria-pressed', String(selected === node.id));
    for (const dest of node.imports) {
      const target = points.get(dest);
      if (!target) continue;
      const start = edgePoint(point, target, 3);
      const end = edgePoint(target, point, 5);
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      for (const [attr, value] of Object.entries({x1:start.x,y1:start.y,x2:end.x,y2:end.y})) line.setAttribute(attr,value);
      const active = node.id === selected || dest === selected;
      if (active) line.classList.add('active');
      line.setAttribute('marker-end', active ? 'url(#active-tip)' : 'url(#tip)');
      lines.push(line);
    }
  }
  get('edges').replaceChildren(...lines);
}

function choose(id) {
  selected = id;
  const item = get(id);
  const title = item.querySelector('strong').cloneNode(true);
  const info = item.querySelector('p').cloneNode(true);
  const source = item.querySelector('.source').cloneNode(true);
  const imports = item.querySelector('.imports').cloneNode(true);
  for (const link of imports.querySelectorAll('a')) {
    link.onclick = event => {
      event.preventDefault();
      choose(link.hash.slice(1));
      buttons.get(selected).focus();
    };
  }
  get('selection-name').textContent = title.textContent;
  get('detail').replaceChildren(title, info, source, imports);
  renderMap();
}

function updateResponse() {
  const visible = visibleNodes();
  const ids = new Set(visible.map(node => node.id));
  const graph = {
    nodes: visible.map(({id,label,pkg,path}) => ({id,label,package:pkg,path:path.slice(6)})),
    edges: visible.flatMap(node => node.imports.filter(id => ids.has(id)).map(to => ({from:node.id,to})))
  };
  const body = JSON.stringify({data:{architecture:graph}},null,2);
  get('projection').textContent = body;
  get('save').href = 'data:application/json;charset=utf-8,' + encodeURIComponent(body);
}

for (const node of nodes) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'point';
  button.textContent = node.label;
  button.dataset.package = node.pkg;
  button.onclick = () => choose(node.id);
  buttons.set(node.id, button);
  field.append(button);
}

for (const id of ['map','query','order-label','picks']) get(id).hidden = false;
get('modules').open = false;
get('left').onclick = () => { angle -= Math.PI/12; renderMap(); };
get('right').onclick = () => { angle += Math.PI/12; renderMap(); };
get('reset').onclick = () => { angle = 0; renderMap(); };
get('group').onchange = () => {
  const visible = visibleNodes();
  angle = 0;
  choose(visible.some(node => node.id === selected) ? selected : visible[0].id);
  updateResponse();
};

let drag = null;
field.addEventListener('pointerdown', event => {
  if (event.target.closest('button') || !event.isPrimary || event.button !== 0) return;
  drag = {x:event.clientX, angle};
  field.setPointerCapture(event.pointerId);
});
field.addEventListener('pointermove', event => {
  if (!drag || !event.isPrimary) return;
  angle = drag.angle + (event.clientX - drag.x) * .009;
  renderMap();
});
field.addEventListener('lostpointercapture', () => { drag = null; });
window.addEventListener('resize', renderMap);
choose(selected);
updateResponse();

get('order').onchange = () => {
  const index = Number(get('order').value);
  const body = document.querySelector('tbody');
  const rows = [...body.rows].sort((a,b) => {
    const left = a.cells[index].textContent, right = b.cells[index].textContent;
    if (index === 0) return left.localeCompare(right,'en');
    return (Number(left) - Number(right)) * (index === 1 ? -1 : 1);
  });
  body.replaceChildren(...rows);
};

// Read the published, rounded case metrics directly from the evidence table.
const routes = [...get('routes').tBodies[0].rows].map(row => ({
  id: row.dataset.routeId, label: row.cells[0].textContent,
  metrics: [...row.cells].slice(1,4).map(cell => Number(cell.textContent))
}));
for (const id of ['route-a','route-b']) {
  routes.forEach((route,index) => get(id).add(new Option(route.label, index)));
  get(id).onchange = comparePair;
}
get('route-a').value = '2';
get('route-b').value = '3';
get('pair').hidden = false;
function comparePair() {
  const a = routes[get('route-a').value], b = routes[get('route-b').value];
  if (a === b) {
    get('delta').textContent = 'Choose two different routes to compare.';
    get('pair-flags').textContent = '';
    return;
  }
  const change = b.metrics.map((value,i) => {
    const delta = value - a.metrics[i];
    return (delta > 0 ? '+' : '') + delta.toFixed(2);
  });
  get('delta').textContent = 'Candidate minus baseline, using displayed figures: ' +
    change[0] + ' BRC expected recipient, ' + change[1] + ' AMR expected sender cost, ' + change[2] + ' hours tail time.';
  const flags = [a,b].map(route => '--route-id ' + route.id);
  get('pair-flags').textContent = 'Append these flags to the Corridor Lab compare command.\n' + flags.join(' ');
}
comparePair();

const traceArgs = ' --contract examples/collector-regression/contract.json --baseline examples/collector-regression/baseline.json --candidate examples/collector-regression/candidate.json';
const cases = [
  {dir:'corridor-lab',status:0,command:'corridor_lab compare examples/fictional-corridor/scenario.json --routes examples/fictional-corridor/routes --format markdown'},
  {dir:'tracecanary',status:1,command:'tracecanary diff' + traceArgs},
  {dir:'tracecanary',status:2,command:'tracecanary coverage-diff' + traceArgs + ' --format json'}
];
function replay() {
  const item = cases[Number(get('case').value)];
  get('folder').textContent = 'From packages/' + item.dir + ' · expected exit ' + item.status;
  const prefix = get('shell').value === 'ps' ? '$env:PYTHONPATH = "src"\n' : 'PYTHONPATH=src ';
  get('command').textContent = prefix + 'python -m ' + item.command;
}
get('case').onchange = replay;
get('shell').onchange = replay;
