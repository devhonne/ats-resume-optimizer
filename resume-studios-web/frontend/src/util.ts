export const words = (s: string) => (s.trim() ? s.trim().split(/\s+/).length : 0);

export const tone = (p: number) => (p >= 80 ? "var(--good)" : p >= 60 ? "var(--warn)" : "var(--bad)");
export const verdict = (p: number) => (p >= 85 ? "Strong" : p >= 70 ? "Good" : p >= 50 ? "Partial" : "Weak");

export const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40) || "job";
export const uid = () => Math.random().toString(36).slice(2, 10);

export function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/x-tex" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function confetti() {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const cv = document.getElementById("confetti") as HTMLCanvasElement | null;
  const x = cv?.getContext("2d");
  if (!cv || !x) return;
  cv.width = innerWidth;
  cv.height = innerHeight;
  const cols = ["#C8361F", "#E8573E", "#1C1915", "#D9A441", "#F4EFE6"];
  const ps = Array.from({ length: 120 }, () => ({
    x: innerWidth * (0.25 + Math.random() * 0.5), y: innerHeight * 0.3,
    vx: (Math.random() - 0.5) * 12, vy: -Math.random() * 11 - 3, r: Math.random() * 7 + 4,
    c: cols[(Math.random() * 5) | 0], a: Math.random() * 6, s: (Math.random() - 0.5) * 0.25,
  }));
  let t = 0;
  const f = () => {
    x.clearRect(0, 0, cv.width, cv.height);
    for (const p of ps) {
      p.vy += 0.3; p.x += p.vx; p.y += p.vy; p.vx *= 0.99; p.a += p.s;
      x.save(); x.translate(p.x, p.y); x.rotate(p.a);
      x.globalAlpha = Math.max(0, 1 - t / 120); x.fillStyle = p.c;
      x.beginPath(); x.ellipse(0, 0, p.r, p.r * 0.45, 0, 0, Math.PI * 2); x.fill(); x.restore();
    }
    if (++t < 130) requestAnimationFrame(f);
    else x.clearRect(0, 0, cv.width, cv.height);
  };
  f();
}

/** LaTeX syntax highlight -> safe HTML (escaped). */
export function highlightTex(src: string) {
  const esc = (s: string) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);
  return src
    .split("\n")
    .map((line) => {
      const m = line.match(/(^|[^\\])%/);
      let code = line, com = "";
      if (m && m.index !== undefined) {
        const i = m.index + m[1].length;
        code = line.slice(0, i);
        com = line.slice(i);
      }
      return esc(code).replace(/(\\[a-zA-Z]+\*?)/g, '<span class="k">$1</span>') + (com ? `<span class="c">${esc(com)}</span>` : "");
    })
    .join("\n");
}
