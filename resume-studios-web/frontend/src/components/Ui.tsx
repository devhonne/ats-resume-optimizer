import { useEffect, useRef, type ReactNode } from "react";

/** Glass highlight that follows the pointer ("liquid" lensing). Call once at app root. */
export function useLiquidGlass() {
  useEffect(() => {
    const move = (e: PointerEvent) => {
      document.querySelectorAll<HTMLElement>(".glass").forEach((g) => {
        const r = g.getBoundingClientRect();
        g.style.setProperty("--mx", `${e.clientX - r.left}px`);
        g.style.setProperty("--my", `${e.clientY - r.top}px`);
      });
    };
    document.addEventListener("pointermove", move, { passive: true });
    return () => document.removeEventListener("pointermove", move);
  }, []);
}

export function Modal({ open, onClose, title, children, dismissable = true, className = "" }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode; dismissable?: boolean; className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape" && dismissable) onClose(); };
    document.addEventListener("keydown", key);
    setTimeout(() => ref.current?.querySelector<HTMLElement>("input,textarea,button.sun")?.focus(), 50);
    return () => document.removeEventListener("keydown", key);
  }, [open, dismissable, onClose]);
  if (!open) return null;
  return (
    <div className="scrim" role="dialog" aria-modal="true" aria-label={title}
      onClick={(e) => { if (e.target === e.currentTarget && dismissable) onClose(); }}>
      <div className={`modal ${className}`} ref={ref}>{children}</div>
    </div>
  );
}

export function Toast({ msg, err }: { msg: string; err?: boolean }) {
  if (!msg) return null;
  return <div className={`toast glass${err ? " err" : ""}`} role="status">{msg}</div>;
}
