"use client";

import { useEffect } from "react";

export function MotionController() {
  useEffect(() => {
    const root = document.documentElement;
    let animationFrame = 0;

    const updateScroll = () => {
      const max = root.scrollHeight - window.innerHeight;
      const progress = max > 0 ? window.scrollY / max : 0;
      root.style.setProperty("--scroll", progress.toFixed(4));
    };

    const queueScrollUpdate = () => {
      if (animationFrame) return;
      animationFrame = window.requestAnimationFrame(() => {
        updateScroll();
        animationFrame = 0;
      });
    };

    const revealObserver = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-visible");
          revealObserver.unobserve(entry.target);
        });
      },
      { threshold: 0.16 },
    );

    const revealElements = document.querySelectorAll<HTMLElement>(".reveal");
    revealElements.forEach((element) => {
      revealObserver.observe(element);
    });

    const details = Array.from(
      document.querySelectorAll<HTMLDetailsElement>(".questions details"),
    );
    const cleanupDetails = details.map((detail) => {
      const handleToggle = () => {
        if (!detail.open) return;
        details.forEach((otherDetail) => {
          if (otherDetail !== detail) otherDetail.removeAttribute("open");
        });
      };

      detail.addEventListener("toggle", handleToggle);
      return () => detail.removeEventListener("toggle", handleToggle);
    });

    updateScroll();
    window.addEventListener("scroll", queueScrollUpdate, { passive: true });
    window.addEventListener("resize", queueScrollUpdate);

    return () => {
      revealObserver.disconnect();
      cleanupDetails.forEach((cleanup) => cleanup());
      window.removeEventListener("scroll", queueScrollUpdate);
      window.removeEventListener("resize", queueScrollUpdate);
      window.cancelAnimationFrame(animationFrame);
    };
  }, []);

  return null;
}
