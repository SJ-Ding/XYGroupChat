import React from "react";
import { Bot, X } from "lucide-react";
export function Avatar({
  id,
  name,
  small = false,
}: {
  id: number;
  name: string;
  small?: boolean;
}) {
  return (
    <span className={`avatar color-${id % 4} ${small ? "small" : ""}`}>
      {id === 0 ? <Bot size={small ? 19 : 23} /> : name.slice(0, 1)}
    </span>
  );
}

export function Empty({
  icon,
  text,
  detail,
}: {
  icon: React.ReactNode;
  text: string;
  detail: string;
}) {
  return (
    <div className="empty-panel">
      {icon}
      <strong>{text}</strong>
      <p>{detail}</p>
    </div>
  );
}
export function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="modal-backdrop" onClick={close}>
      <section
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="modal"
        onClick={(e) => e.stopPropagation()}
      >
        <header>
          <h2>{title}</h2>
          <button aria-label="关闭弹窗" onClick={close}>
            <X size={21} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
