/**
 * Layered animated starfield — twinkle, parallax drift, shooting stars.
 * Sits behind the static starfield.png for depth.
 */
const LAYERS = [
  { n: 140, speed: 0.015, r: [0.4, 1.1], a: [0.15, 0.45] },
  { n: 90, speed: 0.04, r: [0.6, 1.6], a: [0.25, 0.65] },
  { n: 45, speed: 0.09, r: [1, 2.8], a: [0.45, 1] },
];

const TINTS = [
  [255, 255, 255],
  [255, 228, 138],
  [168, 139, 250],
  [45, 212, 167],
  [255, 149, 0],
];

let raf = 0;
let stars = [];
let shooters = [];
let w = 0;
let h = 0;
let ctx = null;
let canvas = null;
let t0 = 0;

function pickTint() {
  const c = TINTS[Math.floor(Math.random() * TINTS.length)];
  return c;
}

function spawnStars() {
  stars = [];
  LAYERS.forEach((layer, li) => {
    for (let i = 0; i < layer.n; i += 1) {
      const tint = pickTint();
      stars.push({
        x: Math.random() * w,
        y: Math.random() * h,
        layer: li,
        r: layer.r[0] + Math.random() * (layer.r[1] - layer.r[0]),
        baseA: layer.a[0] + Math.random() * (layer.a[1] - layer.a[0]),
        phase: Math.random() * Math.PI * 2,
        twinkle: 0.6 + Math.random() * 1.4,
        tint,
        drift: (Math.random() - 0.5) * layer.speed,
      });
    }
  });
}

function maybeShoot() {
  if (shooters.length > 2 || Math.random() > 0.0025) return;
  const tint = pickTint();
  shooters.push({
    x: Math.random() * w * 0.7,
    y: Math.random() * h * 0.35,
    vx: 4 + Math.random() * 6,
    vy: 1.5 + Math.random() * 3,
    len: 40 + Math.random() * 90,
    life: 1,
    tint,
  });
}

function resize() {
  if (!canvas) return;
  w = window.innerWidth;
  h = window.innerHeight;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  spawnStars();
}

function draw(now) {
  if (!ctx) return;
  const elapsed = (now - t0) / 1000;
  ctx.clearRect(0, 0, w, h);

  stars.forEach((s) => {
    const layer = LAYERS[s.layer];
    s.y += layer.speed * 0.35;
    s.x += s.drift;
    if (s.y > h + 4) { s.y = -4; s.x = Math.random() * w; }
    if (s.x < -4) s.x = w + 4;
    if (s.x > w + 4) s.x = -4;
    const tw = 0.55 + 0.45 * Math.sin(elapsed * s.twinkle + s.phase);
    const a = s.baseA * tw;
    const [r, g, b] = s.tint;
    ctx.beginPath();
    ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${r},${g},${b},${a})`;
    ctx.fill();
    if (s.r > 1.6 && tw > 0.85) {
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.r * 2.2, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${r},${g},${b},${a * 0.12})`;
      ctx.fill();
    }
  });

  shooters = shooters.filter((sh) => {
    sh.x += sh.vx;
    sh.y += sh.vy;
    sh.life -= 0.018;
    if (sh.life <= 0) return false;
    const [r, g, b] = sh.tint;
    const grad = ctx.createLinearGradient(sh.x, sh.y, sh.x - sh.len, sh.y - sh.len * 0.4);
    grad.addColorStop(0, `rgba(${r},${g},${b},${sh.life * 0.9})`);
    grad.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.strokeStyle = grad;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(sh.x, sh.y);
    ctx.lineTo(sh.x - sh.len, sh.y - sh.len * 0.4);
    ctx.stroke();
    return true;
  });
  maybeShoot();
  raf = requestAnimationFrame(draw);
}

export function initStarfield() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  canvas = document.getElementById('td-starfield');
  if (!canvas) return;
  ctx = canvas.getContext('2d');
  t0 = performance.now();
  resize();
  window.addEventListener('resize', resize);
  raf = requestAnimationFrame(draw);
}

export function destroyStarfield() {
  cancelAnimationFrame(raf);
  window.removeEventListener('resize', resize);
}
