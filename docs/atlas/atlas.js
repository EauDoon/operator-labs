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

function project(node) {
  const [x, y, z] = node.position;
  const width = field.clientWidth, height = field.clientHeight;
  // On narrow screens the two package lanes stack vertically.
  const narrow = width < 740;
  const single = Boolean(get('group').value);
  const left = node.pkg === 'corridor-lab';
  const localX = x + (left ? 1.3 : -1.3);
  const u = localX * Math.cos(angle) + z * Math.sin(angle);
  const depth = z * Math.cos(angle) - localX * Math.sin(angle);
  const perspective = 1 / (1.6 - depth * .23);
  const cx = single || narrow ? .5 : left ? .25 : .75;
  const cy = narrow && !single ? left ? .25 : .75 : .5;
  return {
    x: width * (cx + u * perspective * (single || narrow ? .66 : .32)),
    y: height * (cy - y * perspective * (narrow && !single ? .45 : .86)),
    depth
  };
}

function renderMap() {
  const visible = visibleNodes();
  const points = new Map(visible.map(node => [node.id, project(node)]));
  const lines = [];
  for (const node of nodes) {
    const button = buttons.get(node.id);
    const point = points.get(node.id);
    button.hidden = !point;
    if (!point) continue;
    button.style.left = point.x + 'px';
    button.style.top = point.y + 'px';
    button.style.zIndex = String(Math.round(10 + point.depth * 5));
    button.setAttribute('aria-pressed', String(selected === node.id));
    for (const dest of node.imports) {
      const target = points.get(dest);
      if (!target) continue;
      const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
      for (const [attr, value] of Object.entries({x1:point.x,y1:point.y,x2:target.x,y2:target.y})) line.setAttribute(attr,value);
      if (node.id === selected || dest === selected) line.classList.add('active');
      lines.push(line);
    }
  }
  get('wires').replaceChildren(...lines);
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
