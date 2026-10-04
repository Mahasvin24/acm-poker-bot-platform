"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

export function MobileMenu() {
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeMenu = () => setIsOpen(false);

  useEffect(() => {
    if (!isOpen) return;

    const handlePointerDown = (event: PointerEvent) => {
      if (
        event.target instanceof Node &&
        !containerRef.current?.contains(event.target)
      ) {
        setIsOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setIsOpen(false);
      triggerRef.current?.focus();
    };

    document.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("pointerdown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [isOpen]);

  return (
    <div className="mobile-menu" ref={containerRef}>
      <button
        ref={triggerRef}
        className="mobile-menu__trigger"
        type="button"
        aria-expanded={isOpen}
        aria-controls="mobile-navigation"
        onClick={() => setIsOpen((open) => !open)}
      >
        Menu <span aria-hidden="true">{isOpen ? "−" : "+"}</span>
      </button>
      {isOpen && (
        <nav id="mobile-navigation" aria-label="Mobile navigation">
          <a href="#format" onClick={closeMenu}>
            Format
          </a>
          <a href="#timeline" onClick={closeMenu}>
            Timeline
          </a>
          <a href="#faq" onClick={closeMenu}>
            FAQ
          </a>
          <Link href="/dashboard" onClick={closeMenu}>
            Play
          </Link>
          <Link href="/account" onClick={closeMenu}>
            Sign in / Register
          </Link>
        </nav>
      )}
    </div>
  );
}
