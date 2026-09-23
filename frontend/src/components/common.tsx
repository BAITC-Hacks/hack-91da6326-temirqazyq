"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { AlertTriangle, LoaderCircle, Sparkles, X } from "lucide-react";
import type { Advisor } from "@/lib/types";

export function Spinner({ text = "Рассчитываем…" }: { text?: string }) {
  return (
    <span className="loading-inline">
      <LoaderCircle size={16} className="spin" />
      {text}
    </span>
  );
}
export function ErrorBox({
  text,
  retry,
}: {
  text: string;
  retry?: () => void;
}) {
  return (
    <div className="error-box" role="alert">
      <AlertTriangle size={17} />
      <span>{text}</span>
      {retry && <button onClick={retry}>Повторить</button>}
    </div>
  );
}

export function Modal({
  title,
  eyebrow,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  eyebrow: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    ref.current?.focus();
    const handler = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
      if (event.key === "Tab") {
        const elements = ref.current?.querySelectorAll<HTMLElement>(
          'button:not(:disabled), a[href], input, select, [tabindex="0"]',
        );
        if (!elements?.length) return;
        const first = elements[0],
          last = elements[elements.length - 1];
        if (
          event.shiftKey &&
          (document.activeElement === first ||
            document.activeElement === ref.current)
        ) {
          event.preventDefault();
          last.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            document.activeElement === ref.current)
        ) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handler);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handler);
      previous?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className={`modal ${wide ? "modal-wide" : ""}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        ref={ref}
      >
        <header className="modal-head">
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h2>{title}</h2>
          </div>
          <button
            className="icon-button"
            onClick={onClose}
            aria-label="Закрыть окно"
          >
            <X size={20} />
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function AdvisorContent({
  advisor,
  compact = false,
}: {
  advisor: Advisor;
  compact?: boolean;
}) {
  const sections: { title: string; items: string[] }[] = [
    { title: "Сильные стороны", items: advisor.strengths },
    { title: "Риски", items: advisor.risks },
    { title: "Компромиссы", items: advisor.tradeoffs },
    { title: "Следующий шаг", items: advisor.recommendations },
  ];
  return (
    <div className={`advisor-content ${compact ? "compact" : ""}`}>
      <div className="advisor-source">
        <Sparkles size={12} />
        {advisor.source === "openai"
          ? "AI-анализ · OpenAI"
          : "Аналитик · шаблонное объяснение"}
      </div>
      <p>{advisor.summary}</p>
      {sections
        .filter((section) => section.items.length)
        .map((section) => (
          <div key={section.title}>
            <h4>{section.title}</h4>
            <ul>
              {(compact ? section.items.slice(0, 1) : section.items).map(
                (item, i) => (
                  <li key={i}>{item}</li>
                ),
              )}
            </ul>
          </div>
        ))}
    </div>
  );
}
